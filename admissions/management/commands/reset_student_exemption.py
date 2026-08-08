"""
Undo a student's course exemption so they can submit a fresh request.

Default target: Alyao Jacqueline (26/2/508/W/2543), change request #192.

What it does:
  - Removes StudentCurriculumOverride rows created for the request's approved papers
  - Deletes pending EXEMPTION_COURSE ad-hoc charges tied to the request
  - Deletes the AdmissionChangeRequest (lines + supporting docs cascade)
  - Optionally resets SPE current/entry year-term to Year 1 Term 1
  - Keeps EXEMPTION_FORM fee (so the form stays unlocked if already paid)

Usage:
  python manage.py reset_student_exemption --dry-run
  python manage.py reset_student_exemption
  python manage.py reset_student_exemption --reg-no "26/2/508/W/2543" --change-request-id 192
  python manage.py reset_student_exemption --no-reset-position
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from admissions.exemption_services import EXEMPTION_COURSE_FEE_CODE, ensure_exemption_fee_heads
from admissions.models import AdmissionChangeRequest, AdmittedStudent
from payments.models import StudentTuitionPayment
from Programs.models import StudentCurriculumOverride

REG_NO_DEFAULT = "26/2/508/W/2543"
CHANGE_REQUEST_ID_DEFAULT = 192


class Command(BaseCommand):
    help = "Undo a course exemption so the student can submit again."

    def add_arguments(self, parser):
        parser.add_argument("--reg-no", default=REG_NO_DEFAULT)
        parser.add_argument(
            "--change-request-id",
            type=int,
            default=CHANGE_REQUEST_ID_DEFAULT,
            help="Exemption change request to undo (default: 192).",
        )
        parser.add_argument(
            "--all-exemption-requests",
            action="store_true",
            help="Undo every exemption change request for this student (ignores --change-request-id).",
        )
        parser.add_argument(
            "--no-reset-position",
            action="store_true",
            help="Do not reset StudentProgrammeEnrollment year/term to Y1T1.",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        w = self.stdout.write
        dry = options["dry_run"]
        reg_no = (options["reg_no"] or "").strip()

        student = (
            AdmittedStudent.objects.filter(student_id=reg_no)
            .select_related("programme_enrollment", "application")
            .first()
        )
        if student is None:
            student = (
                AdmittedStudent.objects.filter(reg_no=reg_no)
                .select_related("programme_enrollment", "application")
                .first()
            )
        if student is None:
            raise CommandError(f"Student not found: {reg_no}")

        name = ""
        try:
            name = student.application.full_name or ""
        except Exception:
            pass

        qs = AdmissionChangeRequest.objects.filter(
            admitted_student=student,
            change_type="exemption",
        ).prefetch_related("exemption_lines")
        if not options["all_exemption_requests"]:
            qs = qs.filter(pk=options["change_request_id"])

        requests = list(qs.order_by("id"))
        if not requests:
            raise CommandError(
                "No matching exemption change request(s) found for this student."
            )

        _, course_head = ensure_exemption_fee_heads()
        reset_position = not options["no_reset_position"]

        w(self.style.NOTICE(
            f"{'[DRY-RUN] ' if dry else ''}"
            f"Resetting exemption for {name or 'student'} ({reg_no}) "
            f"pk={student.pk}"
        ))

        for req in requests:
            line_ids = [
                el.curriculum_line_id
                for el in req.exemption_lines.all()
                if el.curriculum_line_id
            ]
            note_marker = f"Exemption change request #{req.id}"
            course_charges = StudentTuitionPayment.objects.filter(
                student=student,
                source="ad_hoc",
                fee_head=course_head,
                notes__icontains=note_marker,
            )
            # Also catch older rows that used the fee-head code in notes only.
            course_charges = course_charges | StudentTuitionPayment.objects.filter(
                student=student,
                source="ad_hoc",
                fee_head__code=EXEMPTION_COURSE_FEE_CODE,
                notes__icontains=f"change request #{req.id}",
            )
            course_charges = course_charges.distinct()

            overrides = StudentCurriculumOverride.objects.none()
            try:
                enrollment = student.programme_enrollment
            except Exception:
                enrollment = None
            if enrollment is not None and line_ids:
                overrides = StudentCurriculumOverride.objects.filter(
                    enrollment=enrollment,
                    override_type="exempted",
                    curriculum_line_id__in=line_ids,
                )

            w(
                f"  CR #{req.id} status={req.status} "
                f"papers={req.exemption_lines.count()} "
                f"curriculum_links={len(line_ids)} "
                f"overrides={overrides.count()} "
                f"course_charges={course_charges.count()} "
                f"(pending={course_charges.filter(status='pending').count()})"
            )

            if dry:
                continue

            with transaction.atomic():
                deleted_overrides, _ = overrides.delete()
                deleted_charges, _ = course_charges.delete()
                req_id = req.id
                req.delete()
                w(self.style.SUCCESS(
                    f"  Deleted CR #{req_id}; removed {deleted_overrides} override(s), "
                    f"{deleted_charges} EXEMPTION_COURSE charge(s)."
                ))

        if reset_position:
            try:
                enrollment = student.programme_enrollment
            except Exception:
                enrollment = None
            if enrollment is not None:
                from_y, from_t = (
                    enrollment.current_year_of_study,
                    enrollment.current_term_number,
                )
                w(
                    f"  SPE position: Y{from_y}T{from_t} -> Y1T1"
                    + (" (dry-run)" if dry else "")
                )
                if not dry:
                    enrollment.current_year_of_study = 1
                    enrollment.current_term_number = 1
                    enrollment.entry_year_of_study = 1
                    enrollment.entry_term_number = 1
                    enrollment.save(
                        update_fields=[
                            "current_year_of_study",
                            "current_term_number",
                            "entry_year_of_study",
                            "entry_term_number",
                            "updated_at",
                        ]
                    )

        w(self.style.WARNING(
            "EXEMPTION_FORM fee was kept (form stays unlocked if already paid). "
            "Student can submit a new course exemption request."
        ))
        if dry:
            w(self.style.NOTICE("Dry-run only — nothing was changed."))
        else:
            w(self.style.SUCCESS("Done. Student can submit a new exemption request."))
