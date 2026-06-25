"""Core offer-letter generation for API views and Celery bulk tasks."""
from __future__ import annotations

import base64
import logging
import random as _random
import secrets
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db.models import Q
from django.utils import timezone

from admissions.models import AdmittedStudent, Application
from admissions.admission_specialization import (
    offer_letter_combination_context,
    validate_offer_letter_admission,
)
from OfferLetter.AdmissionLetter.models import OfferLetterTemplate
from OfferLetter.AdmissionLetter.utils.letters import fill_pdf_template, render_docx_from_template
from OfferLetter.AdmissionLetter.utils.offer_security import stamp_offer_letter_pdf

logger = logging.getLogger(__name__)

HALLS = ["AKIIBUA", "NJUKI", "MUTEESA", "KAKUNGULU", "YOKANA"]


def _queue_offer_letter_email(application_id: int) -> None:
    from OfferLetter.AdmissionLetter.tasks import send_offerletter_email

    send_offerletter_email.delay(application_id)


def _queue_docx_to_pdf(encoded_docx: str, application_id: int) -> None:
    from OfferLetter.AdmissionLetter.tasks import convert_and_save_pdf_task

    convert_and_save_pdf_task.delay(encoded_docx, application_id)


def resolve_verify_base(request=None, origin: str | None = None) -> str:
    base = (getattr(settings, "OFFER_LETTER_PUBLIC_VERIFY_BASE", "") or "").strip().rstrip("/")
    if base:
        return base
    if request is not None:
        origin = (request.META.get("HTTP_ORIGIN") or "").strip().rstrip("/")
    origin = (origin or "").strip().rstrip("/")
    if origin:
        return origin
    return "http://localhost:3001"


def _printed_by_label(user_id) -> str:
    if not user_id:
        return "system"
    User = get_user_model()
    user = User.objects.filter(pk=user_id).first()
    if not user:
        return "system"
    return (user.get_full_name() or user.username or str(user.pk)).strip()


def _issue_offer_letter_audit(applicant: Application, user) -> str:
    token = secrets.token_urlsafe(32)
    applicant.offer_letter_verification_token = token
    applicant.offer_letter_generated_at = timezone.now()
    if user is not None and getattr(user, "is_authenticated", False):
        applicant.offer_letter_generated_by = user
    else:
        applicant.offer_letter_generated_by = None
    applicant.save(
        update_fields=[
            "offer_letter_verification_token",
            "offer_letter_generated_at",
            "offer_letter_generated_by",
        ]
    )
    return token


def _active_template_for_program(program_id: int) -> OfferLetterTemplate | None:
    return (
        OfferLetterTemplate.objects.filter(programs__id=program_id, status="active")
        .order_by("-uploaded_at")
        .first()
    )


def build_offer_letter_context(applicant: Application, admission: AdmittedStudent, template: OfferLetterTemplate) -> dict:
    if template.start_date:
        start_date_formatted = template.start_date.strftime("%B %d, %Y")
    else:
        start_date_formatted = "To Be Announced"

    if template.hall_of_residence == "RANDOM":
        hall = _random.choice(HALLS)
    elif template.hall_of_residence:
        hall = template.hall_of_residence
    else:
        hall = "To Be Assigned"

    title = (applicant.title or "").strip()
    if not title:
        if applicant.gender and applicant.gender.lower() == "male":
            title = "MR."
        elif applicant.gender and applicant.gender.lower() == "female":
            title = "MS."

    return {
        "full_name": (
            f"{title} {(applicant.first_name or '').strip()} "
            f"{(applicant.last_name or '').strip()} {(applicant.middle_name or '').strip()}"
        ).upper(),
        "phone_number": applicant.phone or "",
        "phone": applicant.phone or "",
        "student_no": admission.student_id or "TBD",
        "reg_no": admission.reg_no or "TBD",
        "program_name": admission.admitted_program.name,
        "min_years": admission.admitted_program.max_years,
        "max_years": admission.admitted_program.min_years,
        "campus": admission.admitted_campus,
        "study_mode": admission.study_mode,
        "start_date": start_date_formatted,
        "hall_of_residence": hall,
        **offer_letter_combination_context(admission),
    }


def generate_offer_letter_for_application(
    application_id: int,
    user,
    *,
    verify_base: str | None = None,
    send_email: bool = True,
    skip_if_pdf_exists: bool = False,
) -> dict[str, Any]:
    applicant = Application.objects.filter(pk=application_id).first()
    if not applicant:
        return {"ok": False, "detail": "Applicant not found.", "status": "error", "application_id": application_id}

    if applicant.is_revoked:
        return {"ok": False, "detail": "Admission revoked.", "status": "error", "application_id": application_id}

    if skip_if_pdf_exists and applicant.admission_letter_pdf:
        if send_email:
            _queue_offer_letter_email(application_id)
        return {
            "ok": True,
            "detail": "Existing PDF reused.",
            "status": "skipped",
            "application_id": application_id,
        }

    try:
        admission = AdmittedStudent.objects.select_related(
            "admitted_program",
            "admitted_campus",
            "admitted_specialization",
        ).get(application=applicant, is_admitted=True)
    except AdmittedStudent.DoesNotExist:
        return {
            "ok": False,
            "detail": "No active admission record for this applicant.",
            "status": "error",
            "application_id": application_id,
        }

    combo_err = validate_offer_letter_admission(admission)
    if combo_err:
        return {
            "ok": False,
            "detail": combo_err,
            "status": "error",
            "application_id": application_id,
        }

    template = _active_template_for_program(admission.admitted_program_id)
    if not template:
        return {
            "ok": False,
            "detail": "No active template for this program.",
            "status": "error",
            "application_id": application_id,
        }

    verify_base = verify_base or resolve_verify_base()
    context = build_offer_letter_context(applicant, admission, template)

    if template.file_type == "pdf":
        if not template.field_positions:
            return {
                "ok": False,
                "detail": "PDF template has no field positions configured.",
                "status": "error",
                "application_id": application_id,
            }
        try:
            _issue_offer_letter_audit(applicant, user)
            verify_url = f"{verify_base}/verify-offer/{applicant.offer_letter_verification_token}"
            pdf_bytes = fill_pdf_template(template.file.path, context, template.field_positions)
            from accounts.portal_branding import get_offer_letter_footer_name

            sys_name = getattr(
                settings,
                "OFFER_LETTER_SYSTEM_FOOTER_NAME",
                None,
            ) or get_offer_letter_footer_name()
            gen_at = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M %Z")
            printed_by = _printed_by_label(getattr(user, "id", None))
            pdf_bytes = stamp_offer_letter_pdf(
                pdf_bytes,
                verify_url=verify_url,
                printed_by=printed_by,
                system_name=sys_name,
                generated_at=gen_at,
            )
        except Exception as exc:
            logger.error("PDF fill failed for applicant %s: %s", application_id, exc, exc_info=True)
            return {
                "ok": False,
                "detail": "PDF template filling failed.",
                "status": "error",
                "application_id": application_id,
            }

        pdf_filename = f"OfferLetter_{applicant.id}.pdf"
        applicant.admission_letter_pdf.save(pdf_filename, ContentFile(pdf_bytes))
        applicant.status = "Admitted"
        applicant.offer_letter_status = "email_sent" if send_email else "pdf_ready"
        applicant.offer_letter_progress = 100
        applicant.save()
        if send_email:
            _queue_offer_letter_email(application_id)
        return {
            "ok": True,
            "detail": "Offer letter PDF generated.",
            "status": "complete",
            "application_id": application_id,
        }

    try:
        docx_bytes = render_docx_from_template(template.file.path, context)
    except Exception as exc:
        logger.error("DOCX rendering failed for applicant %s: %s", application_id, exc, exc_info=True)
        return {
            "ok": False,
            "detail": "DOCX template rendering failed.",
            "status": "error",
            "application_id": application_id,
        }

    _issue_offer_letter_audit(applicant, user)
    docx_filename = f"OfferLetter_{applicant.id}.docx"
    applicant.admission_letter_docx.save(docx_filename, ContentFile(docx_bytes))
    applicant.save()

    encoded_docx = base64.b64encode(docx_bytes).decode("utf-8")
    _queue_docx_to_pdf(encoded_docx, applicant.id)

    return {
        "ok": True,
        "detail": "DOCX saved; PDF conversion queued.",
        "status": "processing",
        "application_id": application_id,
    }
