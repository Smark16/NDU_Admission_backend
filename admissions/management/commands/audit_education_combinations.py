"""
Read-only audit: teaching subject "combinations" (ProgramSpecialization) for
Faculty of Education (and any other has_specialization=True programme),
checked end-to-end across admission -> academic enrollment -> registration.

Flags the exact gap where a student picked a combination at admission
(AdmittedStudent.admitted_specialization) but it never made it onto their
StudentProgrammeEnrollment.specialization, which is what course
registration actually gates on.

Usage:
    python manage.py audit_education_combinations
    python manage.py audit_education_combinations --faculty "Education"
"""
from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand
from django.db.models import Q

# Date the "admitted_specialization" field + admission-time validation went live
# (commit 762b474, refined 2026-07-06 in a0829f3 to only require it at the
# programme's year-one entry point). Admissions before this date could not
# possibly have had a combination picker — that's expected backlog, not a bug.
COMBINATION_FEATURE_LIVE_DATE = date(2026, 6, 21)


class Command(BaseCommand):
    help = "Audit teaching subject combinations across admission / enrollment / registration."

    def add_arguments(self, parser):
        parser.add_argument(
            "--faculty",
            default="Education",
            help="Faculty name filter (icontains). Default: 'Education'.",
        )

    def handle(self, *args, **options):
        from Programs.models import Program

        faculty_filter = options["faculty"]

        programs = (
            Program.objects.filter(has_specialization=True)
            .exclude(code__istartswith="QA-")
            .select_related("faculty")
            .order_by("faculty__name", "name")
        )

        edu_programs = programs.filter(faculty__name__icontains=faculty_filter)
        other_programs = programs.exclude(faculty__name__icontains=faculty_filter)

        self.stdout.write(self.style.SUCCESS("=" * 78))
        self.stdout.write(self.style.SUCCESS(f"  COMBINATION AUDIT — faculty~='{faculty_filter}'"))
        self.stdout.write(self.style.SUCCESS("=" * 78))

        if not edu_programs.exists():
            self.stdout.write(
                self.style.WARNING(
                    f"  No non-QA programme with has_specialization=True found under a "
                    f"faculty matching '{faculty_filter}'."
                )
            )
        for program in edu_programs:
            self._audit_program(program)

        if other_programs.exists():
            self.stdout.write("")
            self.stdout.write(self.style.NOTICE("  Other has_specialization=True programmes (FYI, not this faculty):"))
            for p in other_programs:
                self.stdout.write(f"    - [{p.id}] {p.faculty.name if p.faculty_id else '—'} / {p.name}")

    def _audit_program(self, program):
        from admissions.models import AdmittedStudent
        from Programs.models import ProgramSpecialization, StudentProgrammeEnrollment
        from Programs.specialization_rules import (
            is_before_specialization_entry,
            normalize_specialization,
        )

        self.stdout.write("")
        self.stdout.write(self.style.NOTICE(f"  Programme [{program.id}] {program.name} ({program.faculty.name if program.faculty_id else '—'})"))
        self.stdout.write(
            f"    specialization_entry_year={program.specialization_entry_year}  "
            f"specialization_entry_term={program.specialization_entry_term}"
        )

        combos = list(ProgramSpecialization.objects.filter(program=program).order_by("name"))
        if combos:
            combo_dates = [c.created_at for c in combos if c.created_at]
            if combo_dates:
                self.stdout.write(
                    f"    Combinations ({len(combos)})  configured_at range: "
                    f"{min(combo_dates).date()} .. {max(combo_dates).date()}:"
                )
            else:
                self.stdout.write(f"    Combinations ({len(combos)}):")
            for c in combos:
                mark = "" if c.is_active else "  [INACTIVE]"
                created = c.created_at.date() if c.created_at else "?"
                self.stdout.write(f"      - [{c.id}] {c.name}{mark}  (added {created})")
        else:
            self.stdout.write(self.style.WARNING("    No ProgramSpecialization rows configured for this programme."))

        admitted = list(
            AdmittedStudent.objects.filter(admitted_program=program, is_admitted=True)
            .select_related("admitted_specialization", "programme_enrollment")
        )
        self.stdout.write(f"    Admitted students: {len(admitted)}")

        no_combo_at_admission = []
        combo_not_on_enrollment = []
        combo_mismatch = []
        blocked_now = []

        for a in admitted:
            combo_name = a.admitted_specialization.name if a.admitted_specialization_id else None
            if not combo_name:
                no_combo_at_admission.append(a)
                continue

            spe = getattr(a, "programme_enrollment", None)
            if spe is None:
                continue

            spe_spec = normalize_specialization(spe.specialization) or None

            if not spe_spec:
                combo_not_on_enrollment.append((a, combo_name))
                before_entry = is_before_specialization_entry(
                    program, spe.current_year_of_study, spe.current_term_number
                )
                if not before_entry:
                    blocked_now.append((a, combo_name, spe))
            elif spe_spec.lower() != combo_name.lower():
                combo_mismatch.append((a, combo_name, spe_spec))

        pre_deploy = [
            a for a in no_combo_at_admission
            if a.admission_date and a.admission_date.date() < COMBINATION_FEATURE_LIVE_DATE
        ]
        post_deploy = [
            a for a in no_combo_at_admission
            if not a.admission_date or a.admission_date.date() >= COMBINATION_FEATURE_LIVE_DATE
        ]

        self.stdout.write(
            f"    Admitted WITHOUT a combination selected: {len(no_combo_at_admission)}  "
            f"(pre-feature backlog: {len(pre_deploy)}, AFTER combo feature went live "
            f"{COMBINATION_FEATURE_LIVE_DATE}: {len(post_deploy)})"
        )
        self._print_date_range("      admission_date range (no combo)", no_combo_at_admission)

        if post_deploy:
            self.stdout.write(
                self.style.ERROR(
                    f"    ⚠ Admitted AFTER the combination feature went live but still "
                    f"missing a combination — real leak, not backlog ({len(post_deploy)}):"
                )
            )
            for a in post_deploy:
                self.stdout.write(
                    f"      - {a.reg_no or a.id}  admitted {a.admission_date.date() if a.admission_date else '?'}  "
                    f"{a.application.first_name if a.application_id else ''} {a.application.last_name if a.application_id else ''}"
                )

        for a in pre_deploy[:10]:
            self.stdout.write(
                f"      - {a.reg_no or a.id}  admitted {a.admission_date.date() if a.admission_date else '?'}  "
                f"{a.application.first_name if a.application_id else ''} {a.application.last_name if a.application_id else ''}"
            )

        with_combo = [a for a in admitted if a.admitted_specialization_id]
        self._print_date_range("      admission_date range (WITH combo)", with_combo)

        self.stdout.write(
            self.style.WARNING(
                f"    Combination chosen at admission but MISSING on enrollment record: "
                f"{len(combo_not_on_enrollment)}"
            )
        )
        for a, combo_name in combo_not_on_enrollment[:10]:
            self.stdout.write(f"      - {a.reg_no or a.id}  admitted_combo='{combo_name}'  enrollment.specialization=''")

        if combo_mismatch:
            self.stdout.write(self.style.ERROR(f"    Combination MISMATCH between admission and enrollment: {len(combo_mismatch)}"))
            for a, combo_name, spe_spec in combo_mismatch[:10]:
                self.stdout.write(f"      - {a.reg_no or a.id}  admitted='{combo_name}'  enrollment='{spe_spec}'")

        if blocked_now:
            self.stdout.write(
                self.style.ERROR(
                    f"    LIKELY BLOCKED at course registration RIGHT NOW (past specialization "
                    f"entry point, no specialization on enrollment): {len(blocked_now)}"
                )
            )
            for a, combo_name, spe in blocked_now[:10]:
                self.stdout.write(
                    f"      - {a.reg_no or a.id}  admitted_combo='{combo_name}'  "
                    f"position=Y{spe.current_year_of_study}T{spe.current_term_number}  "
                    f"status={spe.status}"
                )

        if not (no_combo_at_admission or combo_not_on_enrollment or combo_mismatch):
            self.stdout.write(self.style.SUCCESS("    Clean — admission and enrollment combinations agree for all students."))

    def _print_date_range(self, label, students):
        dates = [a.admission_date for a in students if a.admission_date]
        if not dates:
            self.stdout.write(f"{label}: n/a")
            return
        self.stdout.write(f"{label}: {min(dates).date()} .. {max(dates).date()}  (n={len(dates)})")
