"""
Rebuild ``ApplicationProgramChoice`` rows from a legacy Django M2M through table.

Typical use after a bad data migration left ``program_choices`` empty while
``admissions_application_programs`` (Application↔Program M2M) still has rows.

Usage (server, with venv activated)::

    ./venv/bin/python manage.py backfill_application_program_choices --dry-run
    ./venv/bin/python manage.py backfill_application_program_choices --apply
    ./venv/bin/python manage.py backfill_application_program_choices --apply --sync-m2m

``--sync-m2m`` also calls ``application.programs.set(...)`` when the legacy
M2M field still exists (keeps old read paths in sync).
"""
from __future__ import annotations

from collections import defaultdict

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import ForeignKey

from Programs.models import Program


def _discover_choice_model():
    try:
        return apps.get_model("admissions", "ApplicationProgramChoice")
    except LookupError as exc:
        raise CommandError("ApplicationProgramChoice model not found.") from exc


def _fk_field_name(model, related_model):
    for f in model._meta.concrete_fields:
        if isinstance(f, ForeignKey) and f.related_model is related_model:
            return f.name
    return None


def _preference_field_name(choice_model):
    if any(f.name == "preference" for f in choice_model._meta.concrete_fields):
        return "preference"
    for name in ("rank", "choice_order", "order", "position", "sort_order"):
        if any(f.name == name for f in choice_model._meta.concrete_fields):
            return name
    return None


def _legacy_through_table_names():
    """Return candidate DB table names for Application.programs M2M."""
    names = ["admissions_application_programs"]
    with connection.cursor() as cursor:
        if connection.vendor == "sqlite":
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IS NOT NULL"
            )
            for (tbl,) in cursor.fetchall():
                low = tbl.lower()
                if "application" in low and "program" in low and "choice" not in low:
                    if tbl not in names:
                        names.append(tbl)
        elif connection.vendor == "postgresql":
            cursor.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name LIKE '%%application%%program%%'
                """
            )
            for (tbl,) in cursor.fetchall():
                if "choice" not in tbl.lower() and tbl not in names:
                    names.append(tbl)
    return names


def _table_exists(table: str) -> bool:
    return table in connection.introspection.table_names()


def _legacy_rows(table: str):
    """Yield (application_id, program_id, legacy_row_id_for_ordering)."""
    qn = connection.ops.quote_name
    with connection.cursor() as cursor:
        desc = connection.introspection.get_table_description(cursor, table)
    cols = {row.name for row in desc}
    app_col = "application_id" if "application_id" in cols else None
    prog_col = "program_id" if "program_id" in cols else None
    if not app_col or not prog_col:
        raise CommandError(
            f"Table {table!r} missing application_id/program_id columns; found {sorted(cols)}"
        )
    pk_col = "id" if "id" in cols else None
    order_col = pk_col if pk_col else app_col
    sql = (
        f"SELECT {qn(app_col)}, {qn(prog_col)}, {qn(order_col)} FROM "
        f"{qn(table)} ORDER BY {qn(app_col)}, {qn(order_col)}"
    )
    with connection.cursor() as cursor:
        cursor.execute(sql)
        yield from cursor.fetchall()


class Command(BaseCommand):
    help = (
        "Backfill ApplicationProgramChoice from legacy Application↔Program M2M table "
        "(default: admissions_application_programs)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report counts only (default if neither --dry-run nor --apply).",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Insert missing ApplicationProgramChoice rows.",
        )
        parser.add_argument(
            "--legacy-table",
            default=None,
            help="Explicit M2M table name (default: auto-detect).",
        )
        parser.add_argument(
            "--sync-m2m",
            action="store_true",
            help="After backfill, set Application.programs from choices (if M2M exists).",
        )

    def handle(self, *args, **options):
        dry = options["dry_run"] or not options["apply"]
        apply_changes = bool(options["apply"])
        legacy_override = options["legacy_table"]
        sync_m2m = options["sync_m2m"]

        Choice = _discover_choice_model()
        Application = apps.get_model("admissions", "Application")
        app_fk = _fk_field_name(Choice, Application)
        prog_fk = _fk_field_name(Choice, Program)
        pref_fk = _preference_field_name(Choice)
        if not app_fk or not prog_fk:
            raise CommandError(
                f"Could not resolve FK fields on {Choice._meta.label} "
                f"(application={app_fk!r}, program={prog_fk!r})."
            )
        if not pref_fk:
            raise CommandError(
                f"No ordering field (preference/rank/order/…) on {Choice._meta.label}."
            )

        candidates = [legacy_override] if legacy_override else _legacy_through_table_names()
        table = None
        for t in candidates:
            if t and _table_exists(t):
                table = t
                break
        if not table:
            raise CommandError(
                "No legacy M2M table found. Tried: "
                + ", ".join(repr(t) for t in candidates if t)
            )

        self.stdout.write(self.style.NOTICE(f"Using legacy table: {table}"))

        rows = list(_legacy_rows(table))
        self.stdout.write(f"Legacy link rows: {len(rows)}")

        by_app = defaultdict(list)
        for app_id, prog_id, order_key in rows:
            by_app[app_id].append((order_key, prog_id))

        valid_program_ids = set(Program.objects.values_list("pk", flat=True))
        valid_app_ids = set(Application.objects.values_list("pk", flat=True))

        to_create = []
        skipped_program = 0
        skipped_app = 0
        for app_id, pairs in by_app.items():
            if app_id not in valid_app_ids:
                skipped_app += len(pairs)
                continue
            pairs.sort(key=lambda x: x[0])
            pref = 0
            seen_prog = set()
            for _, prog_id in pairs:
                if prog_id not in valid_program_ids:
                    skipped_program += 1
                    continue
                if prog_id in seen_prog:
                    continue
                seen_prog.add(prog_id)
                pref += 1
                kwargs = {app_fk: app_id, prog_fk: prog_id, pref_fk: pref}
                to_create.append(Choice(**kwargs))

        self.stdout.write(f"Applications with legacy links: {len(by_app)}")
        self.stdout.write(f"Choice rows to insert: {len(to_create)}")
        if skipped_app:
            self.stdout.write(self.style.WARNING(f"Skipped (missing application): {skipped_app}"))
        if skipped_program:
            self.stdout.write(self.style.WARNING(f"Skipped (missing program): {skipped_program}"))

        existing = Choice.objects.count()
        self.stdout.write(f"ApplicationProgramChoice rows before: {existing}")

        if dry and not apply_changes:
            self.stdout.write(self.style.WARNING("Dry run only; pass --apply to write."))
            return

        with transaction.atomic():
            Choice.objects.bulk_create(to_create, ignore_conflicts=True)

        self.stdout.write(self.style.SUCCESS(f"Inserted (ignore_duplicates): {len(to_create)}"))
        self.stdout.write(f"ApplicationProgramChoice rows after: {Choice.objects.count()}")

        if sync_m2m:
            try:
                Application._meta.get_field("programs")
            except Exception:
                self.stdout.write("No Application.programs M2M; skipping --sync-m2m.")
                return
            pref_lookup = pref_fk
            updated = 0
            for app_id in by_app:
                if app_id not in valid_app_ids:
                    continue
                app = Application.objects.get(pk=app_id)
                qs = app.program_choices.select_related("program").order_by(pref_lookup, "pk")
                ids = [c.program_id for c in qs if c.program_id]
                if ids:
                    app.programs.set(ids)
                    updated += 1
            self.stdout.write(self.style.SUCCESS(f"sync-m2m: updated applications: {updated}"))
