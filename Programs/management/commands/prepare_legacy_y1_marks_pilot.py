"""
Prepare a legacy programme batch for Year 1 marks pilot (Sem 1 + Sem 2).

Enrolls all SPE students on Y1 papers, withdraws Y2+ enrollments, stamps
registration, and opens semester marks windows so staff can enter results
through Year 1 Sem 2 and test the full workflow.

Examples:
  python manage.py prepare_legacy_y1_marks_pilot --batch-id 259 --dry-run
  python manage.py prepare_legacy_y1_marks_pilot --batch-id 259
  python manage.py prepare_legacy_y1_marks_pilot --batch-id 259 --terms 1
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from Programs.models import CourseUnit, ProgramBatch, Semester, StudentCourseUnitEnrollment
from Programs.teaching_sections import ensure_enrollment_teaching_section
from examinations.models import CourseUnitResult, MarksEntryWindow
from examinations.services.batch_marks_audit import spe_for_batch


def _parse_terms(raw: str) -> list[int]:
    out = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            n = int(part)
        except ValueError as exc:
            raise CommandError(f"Invalid term in --terms: {part!r}") from exc
        if n not in (1, 2, 3):
            raise CommandError(f"term must be 1, 2, or 3 (got {n})")
        out.append(n)
    return sorted(set(out))


class Command(BaseCommand):
    help = (
        "Enroll all students on a legacy batch onto Year 1 course units (Sem 1 & 2), "
        "stamp registration, and open marks windows for a marks-entry pilot."
    )

    def add_arguments(self, parser):
        parser.add_argument("--batch-id", type=int, required=True)
        parser.add_argument(
            "--year",
            type=int,
            default=1,
            help="Academic year of study to target (default: 1).",
        )
        parser.add_argument(
            "--terms",
            default="1,2",
            help="Comma-separated term numbers within the year (default: 1,2).",
        )
        parser.add_argument(
            "--current-term",
            type=int,
            default=2,
            help="Set SPE current_term_number after prep (default: 2 = through Sem 2).",
        )
        parser.add_argument(
            "--deactivate-batch-windows",
            action="store_true",
            default=True,
            help="Deactivate old batch-wide marks windows so semester windows apply (default).",
        )
        parser.add_argument(
            "--no-deactivate-batch-windows",
            action="store_false",
            dest="deactivate_batch_windows",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        batch_id = options["batch_id"]
        year = int(options["year"])
        terms = _parse_terms(options["terms"])
        current_term = int(options["current_term"])
        dry = bool(options.get("dry_run"))

        if not terms:
            raise CommandError("Provide at least one term in --terms.")

        try:
            batch = ProgramBatch.objects.select_related("program").get(pk=batch_id)
        except ProgramBatch.DoesNotExist as exc:
            raise CommandError(f"ProgramBatch #{batch_id} not found.") from exc

        semesters = list(
            Semester.objects.filter(
                program_batch=batch,
                is_active=True,
                year_of_study=year,
                term_number__in=terms,
            ).order_by("term_number", "order")
        )
        if not semesters:
            raise CommandError(
                f"No active semesters on batch #{batch_id} for Y{year} terms {terms}."
            )

        course_units = list(
            CourseUnit.objects.filter(
                program_batch=batch,
                is_active=True,
                semester_id__in=[s.id for s in semesters],
            ).select_related("semester")
            .order_by("semester__term_number", "code")
        )
        if not course_units:
            raise CommandError(f"No active course units for Y{year} terms {terms} on batch #{batch_id}.")

        spes = [
            spe
            for spe in spe_for_batch(batch)
            if spe.status == "enrolled"
            and not (
                getattr(spe.student, "application", None)
                and getattr(spe.student.application, "is_revoked", False)
            )
        ]
        if not spes:
            raise CommandError(f"No enrolled SPE students on batch #{batch_id}.")

        self.stdout.write(
            f"Legacy Y{year} marks pilot — batch #{batch.id} {batch.name}\n"
            f"  Students: {len(spes)} | Semesters: {len(semesters)} | Course units: {len(course_units)}"
            + (" [dry-run]" if dry else "")
        )
        for sem in semesters:
            n_cu = sum(1 for cu in course_units if cu.semester_id == sem.id)
            self.stdout.write(f"  · {sem.name} (id={sem.id}, Y{sem.year_of_study}T{sem.term_number}) — {n_cu} papers")

        if dry:
            self._dry_run_summary(spes, course_units, batch, semesters, year, current_term, options)
            return

        with transaction.atomic():
            spe_updates = 0
            for spe in spes:
                fields = []
                if spe.entry_year_of_study is None:
                    spe.entry_year_of_study = year
                    fields.append("entry_year_of_study")
                if spe.entry_term_number is None:
                    spe.entry_term_number = 1
                    fields.append("entry_term_number")
                if spe.current_year_of_study != year:
                    spe.current_year_of_study = year
                    fields.append("current_year_of_study")
                if spe.current_term_number != current_term:
                    spe.current_term_number = current_term
                    fields.append("current_term_number")
                if fields:
                    fields.append("updated_at")
                    spe.save(update_fields=fields)
                    spe_updates += 1
                ensure_enrollment_teaching_section(spe, assign_only=False)

            created = 0
            reactivated = 0
            for spe in spes:
                student = spe.student
                for cu in course_units:
                    enr, was_created = StudentCourseUnitEnrollment.objects.get_or_create(
                        student=student,
                        course_unit=cu,
                        defaults={
                            "status": "enrolled",
                            "source": "admin_assigned",
                            "registration_date": timezone.now(),
                        },
                    )
                    if was_created:
                        created += 1
                        continue
                    update_fields = []
                    if enr.status == "withdrawn":
                        enr.status = "enrolled"
                        update_fields.append("status")
                    if enr.registration_date is None:
                        enr.registration_date = timezone.now()
                        update_fields.append("registration_date")
                    if update_fields:
                        update_fields.append("updated_at")
                        enr.save(update_fields=update_fields)
                        reactivated += 1

            withdrawn = (
                StudentCourseUnitEnrollment.objects.filter(
                    student_id__in=[spe.student_id for spe in spes],
                    course_unit__program_batch=batch,
                    status="enrolled",
                )
                .exclude(course_unit__semester__year_of_study=year, course_unit__semester__term_number__in=terms)
                .update(status="withdrawn")
            )

            # Remove draft/verified test results on withdrawn rows (keep published for manual review)
            stale_results = CourseUnitResult.objects.filter(
                enrollment__student_id__in=[spe.student_id for spe in spes],
                enrollment__course_unit__program_batch=batch,
                enrollment__status="withdrawn",
                status__in=(CourseUnitResult.STATUS_DRAFT, CourseUnitResult.STATUS_VERIFIED),
            ).delete()[0]

            stamped = (
                StudentCourseUnitEnrollment.objects.filter(
                    student_id__in=[spe.student_id for spe in spes],
                    course_unit__program_batch=batch,
                    course_unit__semester_id__in=[s.id for s in semesters],
                    status="enrolled",
                    registration_date__isnull=True,
                ).update(registration_date=timezone.now())
            )

            windows_opened = 0
            base_name = f"{batch.name} Y{year} marks pilot"
            for sem in semesters:
                existing = (
                    MarksEntryWindow.objects.filter(
                        program_batch=batch,
                        semester=sem,
                        course_unit__isnull=True,
                    )
                    .order_by("-is_active", "-updated_at")
                    .first()
                )
                if existing and existing.is_active and existing.closes_at is None:
                    self.stdout.write(f"  Window open: #{existing.id} {sem.name}")
                    continue
                if existing:
                    existing.is_active = True
                    existing.opens_at = timezone.now()
                    existing.closes_at = None
                    existing.closed_at = None
                    existing.closed_by = None
                    existing.notes = (existing.notes or "") + "\nReopened by prepare_legacy_y1_marks_pilot."
                    existing.save()
                    windows_opened += 1
                else:
                    MarksEntryWindow.objects.create(
                        name=f"{base_name} — {sem.name}",
                        program_batch=batch,
                        semester=sem,
                        opens_at=timezone.now(),
                        is_active=True,
                        notes="Opened by prepare_legacy_y1_marks_pilot",
                    )
                    windows_opened += 1

            deactivated = 0
            if options.get("deactivate_batch_windows"):
                deactivated = MarksEntryWindow.objects.filter(
                    program_batch=batch,
                    semester__isnull=True,
                    course_unit__isnull=True,
                    is_active=True,
                ).update(is_active=False, closed_at=timezone.now())

        self.stdout.write(self.style.SUCCESS(
            f"Done: spe_updated={spe_updates} enrollments_created={created} "
            f"reactivated={reactivated} withdrawn_other_terms={withdrawn} "
            f"stale_draft_results_removed={stale_results} registration_stamped={stamped} "
            f"windows_opened={windows_opened} batch_windows_deactivated={deactivated}"
        ))
        self.stdout.write(
            "Re-run: python manage.py audit_batch_marks_readiness --batch-id "
            f"{batch_id}\nThen enter marks on LLB1101–1107 (Sem 1) and LLB1201–1207 (Sem 2)."
        )

    def _dry_run_summary(self, spes, course_units, batch, semesters, year, current_term, options):
        student_ids = [spe.student_id for spe in spes]
        existing = StudentCourseUnitEnrollment.objects.filter(
            student_id__in=student_ids,
            course_unit_id__in=[cu.id for cu in course_units],
            status="enrolled",
        ).count()
        would_create = len(spes) * len(course_units) - existing
        withdraw_qs = StudentCourseUnitEnrollment.objects.filter(
            student_id__in=student_ids,
            course_unit__program_batch=batch,
            status="enrolled",
        ).exclude(
            course_unit__semester__year_of_study=year,
            course_unit__semester__term_number__in=[s.term_number for s in semesters],
        )
        self.stdout.write(
            f"  Would set {len(spes)} SPE to Y{year} T{current_term}\n"
            f"  Would create ~{max(0, would_create)} enrollments "
            f"({existing} already enrolled on target papers)\n"
            f"  Would withdraw {withdraw_qs.count()} enrollments outside Y{year} terms\n"
            f"  Would open {len(semesters)} semester marks window(s)"
        )
        if options.get("deactivate_batch_windows"):
            n = MarksEntryWindow.objects.filter(
                program_batch=batch,
                semester__isnull=True,
                course_unit__isnull=True,
                is_active=True,
            ).count()
            self.stdout.write(f"  Would deactivate {n} batch-wide window(s)")
