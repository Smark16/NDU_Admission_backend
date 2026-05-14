"""
Read-only audit (and optional import) of ARMS v2 curriculum from legacy MySQL.

Examples:
  python manage.py audit_arms_curriculum --password '***'
  python manage.py audit_arms_curriculum --password '***' --program-core BBA
  python manage.py audit_arms_curriculum --password '***' --program-core-id 12 --json-out arms_bba.json
  python manage.py audit_arms_curriculum --password '***' --import --master-program-id 38 --dry-run
"""
from __future__ import annotations

import json
from collections import defaultdict
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from Programs.legacy_arms.connection import connect_arms_mysql, fetch_all
from Programs.legacy_arms.curriculum_queries import (
    COURSE_SLOT_SQL,
    PROGRAM_CORE_CAMPUS_SQL,
    PROGRAM_CORE_SUMMARY_SQL,
    SPECIALISATION_CORE_SQL,
    compare_campus_curricula,
    map_legacy_course_type,
)


class Command(BaseCommand):
    help = "Audit ARMS v2 curriculum duplication across campuses; optionally import into portal programmes."

    def add_arguments(self, parser):
        parser.add_argument("--host", default=None, help="ARMS MySQL host (default env ARMS_MYSQL_HOST or localhost).")
        parser.add_argument("--port", type=int, default=None, help="ARMS MySQL port (default 3306).")
        parser.add_argument("--user", default=None, help="ARMS MySQL user (default env ARMS_MYSQL_USER or admin).")
        parser.add_argument("--password", default=None, help="ARMS MySQL password (or ARMS_MYSQL_PASSWORD).")
        parser.add_argument("--database", default=None, help="ARMS database name (default arms_v2).")
        parser.add_argument(
            "--program-core",
            dest="program_core_name",
            default=None,
            help="Filter program_core.name with SQL LIKE %%value%%.",
        )
        parser.add_argument(
            "--program-core-id",
            type=int,
            default=None,
            help="Audit one program_core id (overrides --program-core when set).",
        )
        parser.add_argument("--json-out", default=None, help="Write audit payload to a JSON file.")
        parser.add_argument(
            "--import",
            dest="do_import",
            action="store_true",
            help="Import curriculum lines from the selected program_core into portal programmes.",
        )
        parser.add_argument(
            "--master-program-id",
            type=int,
            default=None,
            help="Portal Program pk that owns the imported master curriculum version.",
        )
        parser.add_argument(
            "--version-name",
            default="Imported from ARMS",
            help="Name for the created or reused ProgramCurriculumVersion on import.",
        )
        parser.add_argument(
            "--link-inherited",
            action="store_true",
            help="After import, link other campus programmes under the same program_core to inherit the master.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="With --import, report actions without writing to the portal database.",
        )

    def handle(self, *args, **options):
        with connect_arms_mysql(
            host=options["host"],
            port=options["port"],
            user=options["user"],
            password=options["password"],
            database=options["database"],
        ) as connection:
            with connection.cursor() as cursor:
                summary = fetch_all(cursor, PROGRAM_CORE_SUMMARY_SQL)
                if options["program_core_id"]:
                    core_rows = [row for row in summary if int(row["program_core_id"]) == options["program_core_id"]]
                elif options["program_core_name"]:
                    needle = options["program_core_name"].strip().lower()
                    core_rows = [
                        row for row in summary if needle in (row.get("program_core_name") or "").lower()
                    ]
                else:
                    core_rows = summary

                if not core_rows:
                    raise CommandError("No program_core rows matched the filter.")

                audit_payload = {
                    "program_cores": core_rows,
                    "details": [],
                }

                for core in core_rows:
                    core_id = int(core["program_core_id"])
                    campuses = fetch_all(cursor, PROGRAM_CORE_CAMPUS_SQL, (core_id,))
                    slots = fetch_all(cursor, COURSE_SLOT_SQL, (core_id,))
                    specs = fetch_all(cursor, SPECIALISATION_CORE_SQL, (core_id,))
                    comparisons = compare_campus_curricula(slots)
                    detail = {
                        "program_core": core,
                        "campus_programs": campuses,
                        "specialisation_categories": specs,
                        "course_slot_count": len(slots),
                        "campus_comparisons": comparisons,
                        "_slot_rows": slots,
                    }
                    audit_payload["details"].append(detail)
                    self._print_core_report(detail)

                if options["json_out"]:
                    with open(options["json_out"], "w", encoding="utf-8") as handle:
                        json.dump(audit_payload, handle, indent=2, default=str)
                    self.stdout.write(self.style.SUCCESS(f"Wrote audit JSON to {options['json_out']}"))

                if options["do_import"]:
                    if len(audit_payload["details"]) != 1:
                        raise CommandError("Import requires exactly one program_core match.")
                    self._import_core(
                        audit_payload["details"][0],
                        master_program_id=options["master_program_id"],
                        version_name=options["version_name"],
                        link_inherited=options["link_inherited"],
                        dry_run=options["dry_run"],
                    )

    def _print_core_report(self, detail: dict) -> None:
        core = detail["program_core"]
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(f"{core['program_core_name']} (program_core id={core['program_core_id']})"))
        self.stdout.write(
            f"  Duration: {core.get('minimum_duration')} years | "
            f"Campus programmes: {core.get('campus_program_count')} | "
            f"Course rows: {core.get('course_count')}"
        )

        for campus in detail["campus_programs"]:
            self.stdout.write(
                f"  - {campus.get('campus_name')}: program id={campus.get('program_id')} "
                f"code={campus.get('program_code')} courses={campus.get('course_count')}"
            )

        specs = detail["specialisation_categories"]
        if specs:
            self.stdout.write("  Specialisation categories:")
            for spec in specs:
                self.stdout.write(f"    - {spec.get('name')}")

        comparisons = detail["campus_comparisons"]
        if comparisons:
            self.stdout.write("  Campus curriculum overlap (by code/year/term/specialisation):")
            for item in comparisons:
                left = item["left"]
                right = item["right"]
                self.stdout.write(
                    f"    {left.get('campus_name')} ({left.get('program_code')}) vs "
                    f"{right.get('campus_name')} ({right.get('program_code')}): "
                    f"{item['overlap_pct']}% shared, "
                    f"only-left={item['only_left']}, only-right={item['only_right']}"
                )
        else:
            self.stdout.write("  Only one campus programme under this core; no overlap comparison.")

    def _import_core(
        self,
        detail: dict,
        *,
        master_program_id: int | None,
        version_name: str,
        link_inherited: bool,
        dry_run: bool,
    ) -> None:
        from Programs.curriculum_inheritance import link_program_to_curriculum_source
        from Programs.models import CourseCatalogUnit, Program, ProgramCurriculumLine, ProgramCurriculumVersion

        campuses = detail["campus_programs"]
        if not campuses:
            raise CommandError("No campus programmes found in ARMS for import.")

        master_row = None
        if master_program_id:
            master_program = Program.objects.filter(pk=master_program_id).first()
            if not master_program:
                raise CommandError(f"Portal programme id={master_program_id} not found.")
            master_row = next(
                (row for row in campuses if (row.get("program_code") or "").strip() == master_program.code),
                campuses[0],
            )
        else:
            master_row = campuses[0]
            master_program = Program.objects.filter(code=master_row.get("program_code")).first()
            if not master_program:
                raise CommandError(
                    "Pass --master-program-id or create a portal programme whose code matches the ARMS master campus programme."
                )

        master_legacy_id = int(master_row["program_id"])
        slot_rows = [
            row for row in self._load_slots_for_import(detail) if int(row["program_id"]) == master_legacy_id
        ]
        if not slot_rows:
            raise CommandError("No ARMS course rows found for the selected master campus programme.")

        created_catalog = 0
        created_lines = 0
        skipped_lines = 0

        def import_lines(version: ProgramCurriculumVersion) -> None:
            nonlocal created_catalog, created_lines, skipped_lines
            for row in slot_rows:
                code = (row.get("course_code") or "").strip()
                if not code:
                    skipped_lines += 1
                    continue
                title = (row.get("course_name") or code).strip()
                credit_units = row.get("credit_units")
                if credit_units is None:
                    credit_units = Decimal("0")
                else:
                    credit_units = Decimal(str(credit_units))

                catalog, catalog_created = CourseCatalogUnit.objects.get_or_create(
                    code=code,
                    defaults={
                        "title": title,
                        "credit_units": credit_units,
                        "is_active": True,
                    },
                )
                if catalog_created:
                    created_catalog += 1
                elif catalog.title != title and not dry_run:
                    catalog.title = title
                    catalog.credit_units = credit_units
                    catalog.save(update_fields=["title", "credit_units", "updated_at"])

                line_defaults = {
                    "program": master_program,
                    "catalog_course": catalog,
                    "year_of_study": int(row["year_of_study"]),
                    "term_number": int(row["term_number"]),
                    "course_type": map_legacy_course_type(row.get("course_type")),
                    "specialization": (row.get("specialization_name") or None),
                    "is_active": int(row.get("course_status") or 0) == 0,
                }
                _, line_created = ProgramCurriculumLine.objects.get_or_create(
                    curriculum_version=version,
                    catalog_course=catalog,
                    year_of_study=line_defaults["year_of_study"],
                    term_number=line_defaults["term_number"],
                    defaults=line_defaults,
                )
                if line_created:
                    created_lines += 1
                else:
                    skipped_lines += 1

        self.stdout.write("")
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Import from ARMS master campus {master_row.get('campus_name')} "
                f"(legacy program id={master_legacy_id}) -> portal programme {master_program.code}"
            )
        )

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run: no portal rows will be written."))
            self.stdout.write(f"Would import {len(slot_rows)} curriculum slots.")
            if link_inherited:
                for row in campuses:
                    if int(row["program_id"]) == master_legacy_id:
                        continue
                    self.stdout.write(
                        f"Would link inherited programme for campus {row.get('campus_name')} "
                        f"(legacy program id={row.get('program_id')})."
                    )
            return

        with transaction.atomic():
            master_program.curriculum_mode = Program.CURRICULUM_MODE_MASTER
            master_program.curriculum_source_program = None
            master_program.save(update_fields=["curriculum_mode", "curriculum_source_program", "updated_at"])

            version, _ = ProgramCurriculumVersion.objects.get_or_create(
                program=master_program,
                name=version_name,
                defaults={"is_active": True},
            )
            import_lines(version)

            linked = 0
            if link_inherited:
                for row in campuses:
                    legacy_id = int(row["program_id"])
                    if legacy_id == master_legacy_id:
                        continue
                    child = Program.objects.filter(code=(row.get("program_code") or "").strip()).first()
                    if not child:
                        self.stdout.write(
                            self.style.WARNING(
                                f"Skipping inheritance link; no portal programme for code {row.get('program_code')}."
                            )
                        )
                        continue
                    link_program_to_curriculum_source(child, master_program)
                    linked += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported curriculum version id={version.id}: "
                f"catalog_created={created_catalog}, lines_created={created_lines}, "
                f"lines_skipped={skipped_lines}, inherited_links={linked if link_inherited else 0}."
            )
        )

    def _load_slots_for_import(self, detail: dict) -> list[dict]:
        # Import reuses the already-fetched slot rows attached during audit.
        return detail.get("_slot_rows") or []
