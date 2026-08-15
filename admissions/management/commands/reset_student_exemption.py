"""
Undo a student's course exemption so they can submit a fresh request.

Default target: Alyao Jacqueline (26/2/508/W/2543).

What it does:
  - Removes StudentCurriculumOverride rows (exempted) for the student
  - Deletes EXEMPTION_COURSE ad-hoc charges (optionally all, or only those
    tied to matching change requests)
  - Deletes matching AdmissionChangeRequest rows (lines + docs cascade)
  - Optionally resets SPE current/entry year-term to Year 1 Term 1
  - Keeps EXEMPTION_FORM fee (so the form stays unlocked if already paid)

If no change request remains (already deleted), still cleans overrides /
course charges / position so the student is ready to submit again.

Usage:
  python manage.py reset_student_exemption --dry-run
  python manage.py reset_student_exemption
  python manage.py reset_student_exemption --all-exemption-requests
  python manage.py reset_student_exemption --reg-no "26/2/508/W/2543"
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from admissions.exemption_services import (
    EXEMPTION_COURSE_FEE_CODE,
    EXEMPTION_FORM_FEE_CODE,
    ensure_exemption_fee_heads,
)
from admissions.models import AdmissionChangeRequest, AdmittedStudent
from payments.models import StudentTuitionPayment
from Programs.models import StudentCurriculumOverride

REG_NO_DEFAULT = "26/2/508/W/2543"
CHANGE_REQUEST_ID_DEFAULT = 192


def _find_student(reg_no: str):
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
    return student


class Command(BaseCommand):
    help = "Undo a course exemption so the student can submit again."

    def add_arguments(self, parser):
        parser.add_argument("--reg-no", default=REG_NO_DEFAULT)
        parser.add_argument(
            "--change-request-id",
            type=int,
            default=CHANGE_REQUEST_ID_DEFAULT,
            help="Exemption change request to undo (default: 192). Ignored with --all-exemption-requests.",
        )
        parser.add_argument(
            "--all-exemption-requests",
            action="store_true",
            help="Undo every exemption change request for this student (and all leftover exempted overrides / course charges).",
        )
        parser.add_argument(
            "--no-reset-position",
            action="store_true",
            help="Do not reset StudentProgrammeEnrollment year/term to Y1T1.",
        )
        parser.add_argument(
            "--wipe-form-fee",
            action="store_true",
            help="Also delete EXEMPTION_FORM (50k) bills so the student must pay via SchoolPay again.",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        w = self.stdout.write
        dry = options["dry_run"]
        reg_no = (options["reg_no"] or "").strip()
        all_reqs = options["all_exemption_requests"]

        student = _find_student(reg_no)
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
        if not all_reqs:
            qs = qs.filter(pk=options["change_request_id"])

        requests = list(qs.order_by("id"))
        _, course_head = ensure_exemption_fee_heads()
        form_head, _ = ensure_exemption_fee_heads()
        reset_position = not options["no_reset_position"]
        wipe_form = options["wipe_form_fee"]

        try:
            enrollment = student.programme_enrollment
        except Exception:
            enrollment = None

        # Leftover cleanup when CR already gone, or when wiping all.
        cleanup_all_leftovers = all_reqs or not requests

        w(self.style.NOTICE(
            f"{'[DRY-RUN] ' if dry else ''}"
            f"Resetting exemption for {name or 'student'} ({reg_no}) "
            f"pk={student.pk}"
        ))
        if not requests:
            w(self.style.WARNING(
                "  No matching AdmissionChangeRequest — cleaning leftover "
                "overrides / EXEMPTION_COURSE charges / position."
            ))

        line_ids_from_reqs: set[int] = set()
        for req in requests:
            for el in req.exemption_lines.all():
                if el.curriculum_line_id:
                    line_ids_from_reqs.add(el.curriculum_line_id)

            note_marker = f"Exemption change request #{req.id}"
            course_charges = StudentTuitionPayment.objects.filter(
                student=student,
                source="ad_hoc",
                fee_head=course_head,
                notes__icontains=note_marker,
            ) | StudentTuitionPayment.objects.filter(
                student=student,
                source="ad_hoc",
                fee_head__code=EXEMPTION_COURSE_FEE_CODE,
                notes__icontains=f"change request #{req.id}",
            )
            course_charges = course_charges.distinct()

            overrides = StudentCurriculumOverride.objects.none()
            if enrollment is not None and line_ids_from_reqs:
                # Per-request preview only; actual delete may use full leftover set below.
                overrides = StudentCurriculumOverride.objects.filter(
                    enrollment=enrollment,
                    override_type="exempted",
                    curriculum_line_id__in=[
                        el.curriculum_line_id
                        for el in req.exemption_lines.all()
                        if el.curriculum_line_id
                    ],
                )

            w(
                f"  CR #{req.id} status={req.status} "
                f"papers={req.exemption_lines.count()} "
                f"overrides(for CR lines)={overrides.count()} "
                f"course_charges={course_charges.count()} "
                f"(pending={course_charges.filter(status='pending').count()})"
            )

        if enrollment is not None:
            leftover_overrides = StudentCurriculumOverride.objects.filter(
                enrollment=enrollment,
                override_type="exempted",
            )
            if not cleanup_all_leftovers and line_ids_from_reqs:
                leftover_overrides = leftover_overrides.filter(
                    curriculum_line_id__in=line_ids_from_reqs
                )
        else:
            leftover_overrides = StudentCurriculumOverride.objects.none()

        if cleanup_all_leftovers:
            leftover_charges = StudentTuitionPayment.objects.filter(
                student=student,
                source="ad_hoc",
            ).filter(
                Q(fee_head=course_head) | Q(fee_head__code=EXEMPTION_COURSE_FEE_CODE)
            )
        else:
            markers = [f"Exemption change request #{r.id}" for r in requests] + [
                f"change request #{r.id}" for r in requests
            ]
            q = Q()
            for m in markers:
                q |= Q(notes__icontains=m)
            leftover_charges = StudentTuitionPayment.objects.filter(
                student=student,
                source="ad_hoc",
            ).filter(
                Q(fee_head=course_head) | Q(fee_head__code=EXEMPTION_COURSE_FEE_CODE)
            ).filter(q)

        leftover_form_fees = StudentTuitionPayment.objects.none()
        if wipe_form:
            leftover_form_fees = StudentTuitionPayment.objects.filter(
                student=student,
                source="ad_hoc",
            ).filter(Q(fee_head=form_head) | Q(fee_head__code=EXEMPTION_FORM_FEE_CODE))

        w(
            f"  Will remove: exempted_overrides={leftover_overrides.count()} "
            f"EXEMPTION_COURSE_charges={leftover_charges.count()} "
            f"EXEMPTION_FORM_charges={leftover_form_fees.count()} "
            f"change_requests={len(requests)}"
        )
        if enrollment is not None:
            w(
                f"  SPE now: Y{enrollment.current_year_of_study}"
                f"T{enrollment.current_term_number} "
                f"entry=Y{enrollment.entry_year_of_study}"
                f"T{enrollment.entry_term_number}"
                + (
                    " -> reset to Y1T1"
                    if reset_position
                    else " (position kept)"
                )
            )

        if dry:
            w(self.style.NOTICE("Dry-run only — nothing was changed."))
            return

        with transaction.atomic():
            deleted_overrides, _ = leftover_overrides.delete()
            deleted_charges, _ = leftover_charges.delete()
            deleted_form = 0
            if wipe_form:
                deleted_form, _ = leftover_form_fees.delete()
            for req in requests:
                req_id = req.id
                req.delete()
                w(self.style.SUCCESS(f"  Deleted CR #{req_id}"))

            if reset_position and enrollment is not None:
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
                w(self.style.SUCCESS("  SPE reset to Y1T1 (current + entry)."))

            w(self.style.SUCCESS(
                f"  Removed {deleted_overrides} override(s), "
                f"{deleted_charges} EXEMPTION_COURSE charge(s)"
                + (f", {deleted_form} EXEMPTION_FORM charge(s)." if wipe_form else ".")
            ))

        if wipe_form:
            w(self.style.WARNING(
                "EXEMPTION_FORM fee was deleted. Student must pay the 50k via SchoolPay "
                "before submitting a new application."
            ))
        else:
            w(self.style.WARNING(
                "EXEMPTION_FORM fee was kept (form stays unlocked if already paid). "
                "Student can submit a new course exemption request."
            ))
        w(self.style.SUCCESS("Done. Student can submit a new exemption request."))
