"""Smoke-test SharedTeachingOffering helpers on local data.

Usage:
  python manage.py shell < Programs/management/commands/../  (or)
  python manage.py test_shared_teaching
  python manage.py test_shared_teaching --code "BCS 1101" --dry-run
  python manage.py test_shared_teaching --code "BCS 1101" --link
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Count

from Programs.models import CourseUnit, SharedTeachingOffering
from Programs.shared_teaching import (
    create_shared_offering_from_course_units,
    moodle_idnumber_for_course_unit,
    registered_enrollments_for_course_unit,
)


class Command(BaseCommand):
    help = "List / optionally link common course units for SharedTeachingOffering testing."

    def add_arguments(self, parser):
        parser.add_argument("--code", type=str, default="", help="Exact or partial course code")
        parser.add_argument(
            "--link",
            action="store_true",
            help="Create a SharedTeachingOffering for the first matching code group (min 2 units)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only print candidates; never create",
        )

    def handle(self, *args, **options):
        code = (options.get("code") or "").strip()
        qs = CourseUnit.objects.filter(is_active=True)
        if code:
            qs = qs.filter(code__icontains=code)

        groups = (
            qs.values("code")
            .annotate(n=Count("id"))
            .filter(n__gte=2)
            .order_by("code")[:30]
        )
        self.stdout.write(self.style.NOTICE(f"Codes with 2+ active offerings: {len(groups)}"))
        for g in groups:
            units = list(
                CourseUnit.objects.filter(code=g["code"], is_active=True)
                .select_related(
                    "program_batch",
                    "program_batch__program",
                    "semester",
                    "shared_teaching_offering",
                )
                .order_by("id")
            )
            self.stdout.write(f"\n{g['code']} ({g['n']})")
            for u in units:
                batch = u.program_batch
                prog = batch.program if batch else None
                sto = u.shared_teaching_offering_id
                self.stdout.write(
                    f"  cu={u.id} batch={batch.id if batch else None} "
                    f"{prog.name if prog else '?'} / {batch.name if batch else '?'} "
                    f"sem={u.semester_id} sto={sto} "
                    f"idnumber={moodle_idnumber_for_course_unit(u)}"
                )

        if options.get("dry_run") or not options.get("link"):
            existing = SharedTeachingOffering.objects.count()
            self.stdout.write(self.style.SUCCESS(f"\nExisting SharedTeachingOffering rows: {existing}"))
            if existing:
                for o in SharedTeachingOffering.objects.order_by("-id")[:10]:
                    self.stdout.write(
                        f"  #{o.id} {o.code} {o.moodle_idnumber} "
                        f"linked={o.course_units.count()}"
                    )
            self.stdout.write(
                self.style.NOTICE(
                    "Pass --link --code \"EXACT CODE\" to create a shared offering for testing."
                )
            )
            return

        if not code:
            self.stderr.write(" --link requires --code")
            return

        units = list(
            CourseUnit.objects.filter(code__iexact=code, is_active=True).order_by("id")
        )
        if len(units) < 2:
            # fallback contains
            units = list(
                CourseUnit.objects.filter(code__icontains=code, is_active=True).order_by("id")
            )
            # keep only one code group
            if units:
                primary = units[0].code
                units = [u for u in units if u.code == primary]

        if len(units) < 2:
            self.stderr.write("Need at least two active course units for that code.")
            return

        unlinked = [u for u in units if not u.shared_teaching_offering_id]
        if len(unlinked) < 2:
            self.stderr.write("Fewer than two unlinked units; nothing to create.")
            return

        offering = create_shared_offering_from_course_units(
            course_unit_ids=[u.id for u in unlinked],
            academic_year_label="TEST",
            term_number=1,
        )
        offering.refresh_from_db()
        sample = unlinked[0]
        sample.refresh_from_db()
        roster = registered_enrollments_for_course_unit(sample)
        self.stdout.write(
            self.style.SUCCESS(
                f"Created SharedTeachingOffering #{offering.id} "
                f"idnumber={offering.moodle_idnumber} "
                f"linked={offering.course_units.count()} "
                f"merged_roster={roster.count()}"
            )
        )
