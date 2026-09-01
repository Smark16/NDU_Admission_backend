"""
Move PHY curriculum lines out of the Shared (blank specialization) bucket so only
physics-related teaching combinations receive them.

Background: Faculty of Education programmes often load PHY 1101–1104 as Shared,
which assigns general physics to every Y1 combination (Math&Chem, Bio&Chem, etc.).
When PHY should be limited to physics-related tracks, deactivate the shared lines
and ensure each combination whose name contains "Physics" has its own PHY lines.

Usage:
    python manage.py retag_education_shared_phy
    python manage.py retag_education_shared_phy --faculty Education
    python manage.py retag_education_shared_phy --apply
    python manage.py retag_education_shared_phy --apply --fix-enrollments
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

PHY_CODE_PREFIX = "PHY"


def _is_physics_combination(name: str) -> bool:
    return "physics" in (name or "").strip().lower()


def _blank_spec_q():
    return Q(specialization__isnull=True) | Q(specialization="")


class Command(BaseCommand):
    help = (
        "Retag Education PHY courses: remove from Shared, keep/add on physics-related combinations."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--faculty",
            default="Education",
            help="Faculty name filter (icontains). Default: Education.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write changes. Default is dry-run (report only).",
        )
        parser.add_argument(
            "--fix-enrollments",
            action="store_true",
            help=(
                "With --apply: withdraw unregistered PHY enrollments for students on "
                "non-physics combinations; warn on registered PHY rows (manual review)."
            ),
        )

    def handle(self, *args, **options):
        from Programs.models import Program, ProgramCurriculumLine, ProgramSpecialization

        faculty_filter = options["faculty"]
        dry_run = not options["apply"]
        fix_enrollments = options["fix_enrollments"]

        programs = (
            Program.objects.filter(has_specialization=True)
            .exclude(code__istartswith="QA-")
            .filter(faculty__name__icontains=faculty_filter)
            .select_related("faculty")
            .order_by("name")
        )

        if not programs.exists():
            self.stdout.write(self.style.WARNING(f"No programmes found for faculty~='{faculty_filter}'."))
            return

        mode = "DRY RUN" if dry_run else "APPLY"
        self.stdout.write(self.style.SUCCESS("=" * 72))
        self.stdout.write(self.style.SUCCESS(f"  RETAG EDUCATION SHARED PHY — {mode}"))
        self.stdout.write(self.style.SUCCESS("=" * 72))

        totals = {
            "shared_deactivated": 0,
            "combo_created": 0,
            "combo_already": 0,
            "enrollments_withdrawn": 0,
            "registered_phy_warnings": 0,
        }

        for program in programs:
            self._process_program(program, dry_run, fix_enrollments, totals)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Totals:"))
        for key, val in totals.items():
            self.stdout.write(f"  {key}: {val}")
        if dry_run:
            self.stdout.write(self.style.NOTICE("\nRe-run with --apply to persist changes."))

    def _process_program(self, program, dry_run: bool, fix_enrollments: bool, totals: dict):
        from Programs.curriculum_inheritance import curriculum_owner_program
        from Programs.models import (
            ProgramCurriculumLine,
            ProgramCurriculumVersion,
            ProgramSpecialization,
        )

        owner = curriculum_owner_program(program)
        versions = ProgramCurriculumVersion.objects.filter(
            program=owner, is_active=True
        ).order_by("-is_default", "-id")

        if not versions.exists():
            return

        physics_combos = [
            s.name
            for s in ProgramSpecialization.objects.filter(program=program, is_active=True)
            if _is_physics_combination(s.name)
        ]
        non_physics_combos = [
            s.name
            for s in ProgramSpecialization.objects.filter(program=program, is_active=True)
            if not _is_physics_combination(s.name)
        ]

        shared_phy = list(
            ProgramCurriculumLine.objects.filter(
                program=owner,
                curriculum_version__in=versions,
                is_active=True,
                catalog_course__code__istartswith=PHY_CODE_PREFIX,
            )
            .filter(_blank_spec_q())
            .select_related("catalog_course", "curriculum_version")
            .order_by("curriculum_version_id", "year_of_study", "term_number", "catalog_course__code")
        )

        if not shared_phy:
            return

        self.stdout.write("")
        self.stdout.write(
            self.style.NOTICE(
                f"Programme [{program.id}] {program.name} — {len(shared_phy)} shared PHY line(s)"
            )
        )
        self.stdout.write(f"  Physics combinations: {', '.join(physics_combos) or '(none)'}")
        self.stdout.write(f"  Non-physics combinations: {len(non_physics_combos)}")

        for line in shared_phy:
            code = line.catalog_course.code
            pos = f"Y{line.year_of_study} T{line.term_number}"
            self.stdout.write(
                f"  Shared PHY to deactivate: {code} ({pos}) version={line.curriculum_version_id}"
            )

            for combo in physics_combos:
                exists = ProgramCurriculumLine.objects.filter(
                    program=owner,
                    curriculum_version=line.curriculum_version,
                    catalog_course=line.catalog_course,
                    year_of_study=line.year_of_study,
                    term_number=line.term_number,
                    specialization__iexact=combo,
                    is_active=True,
                ).exists()
                if exists:
                    totals["combo_already"] += 1
                    self.stdout.write(f"    already on '{combo}'")
                else:
                    totals["combo_created"] += 1
                    self.stdout.write(self.style.WARNING(f"    will add to '{combo}'"))
                    if not dry_run:
                        ProgramCurriculumLine.objects.create(
                            program=owner,
                            curriculum_version=line.curriculum_version,
                            catalog_course=line.catalog_course,
                            year_of_study=line.year_of_study,
                            term_number=line.term_number,
                            course_type=line.course_type,
                            elective_group=line.elective_group,
                            specialization=combo,
                            sort_order=line.sort_order,
                            is_active=True,
                        )

            if not dry_run:
                line.is_active = False
                line.save(update_fields=["is_active", "updated_at"])
            totals["shared_deactivated"] += 1

        self._report_affected_students(program, non_physics_combos)

        if fix_enrollments and not dry_run:
            totals["enrollments_withdrawn"] += self._fix_enrollments(program, non_physics_combos, totals)

    def _report_affected_students(self, program, non_physics_combos: list[str]):
        from Programs.models import StudentCourseUnitEnrollment, StudentProgrammeEnrollment

        if not non_physics_combos:
            return

        combo_lower = {c.lower() for c in non_physics_combos}
        spes = StudentProgrammeEnrollment.objects.filter(
            program=program,
            is_enrolled=True,
        ).select_related("student")

        affected = []
        for spe in spes:
            spec = (spe.specialization or "").strip()
            if not spec or spec.lower() in combo_lower:
                phy_rows = StudentCourseUnitEnrollment.objects.filter(
                    student=spe.student,
                    course_unit__code__istartswith=PHY_CODE_PREFIX,
                    status="enrolled",
                ).select_related("course_unit")
                if phy_rows.exists():
                    reg = sum(1 for e in phy_rows if e.registration_date)
                    affected.append((spe, spec, phy_rows.count(), reg))

        if not affected:
            self.stdout.write("  No non-physics students with PHY enrollments.")
            return

        self.stdout.write(self.style.WARNING(f"  {len(affected)} non-physics student(s) with PHY enrollments:"))
        for spe, spec, count, reg in affected[:20]:
            st = spe.student
            name = getattr(getattr(st, "application", None), "full_name", None) or st.student_id
            self.stdout.write(
                f"    {st.student_id} {name} | {spec or '(no combo)'} | "
                f"PHY rows={count} registered={reg}"
            )
        if len(affected) > 20:
            self.stdout.write(f"    ... and {len(affected) - 20} more")

    def _fix_enrollments(self, program, non_physics_combos: list[str], totals: dict) -> int:
        from Programs.models import StudentCourseUnitEnrollment, StudentProgrammeEnrollment

        combo_lower = {c.lower() for c in non_physics_combos}
        withdrawn = 0

        spes = StudentProgrammeEnrollment.objects.filter(program=program, is_enrolled=True)
        with transaction.atomic():
            for spe in spes:
                spec = (spe.specialization or "").strip()
                if not spec or spec.lower() not in combo_lower:
                    continue
                for en in StudentCourseUnitEnrollment.objects.filter(
                    student=spe.student,
                    course_unit__code__istartswith=PHY_CODE_PREFIX,
                    status="enrolled",
                ):
                    if en.registration_date:
                        totals["registered_phy_warnings"] += 1
                        self.stdout.write(
                            self.style.ERROR(
                                f"    MANUAL: {spe.student.student_id} registered for "
                                f"{en.course_unit.code} — review transcript/Moodle"
                            )
                        )
                        continue
                    en.status = "withdrawn"
                    en.save(update_fields=["status"])
                    withdrawn += 1
        return withdrawn
