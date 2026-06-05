from django.shortcuts import render
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import generics, status
from rest_framework.permissions import *
from rest_framework.parsers import MultiPartParser, FormParser
from .models import *
from .serializers import *
from django.utils import timezone

import os
from typing import Optional

from django.core.files.base import ContentFile
# from tempfile import NamedTemporaryFile
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Q
from admissions.models import Application, AdmittedStudent
from .utils.letters import render_docx_from_template, save_docx_to_field, convert_docx_to_pdf_bytes, save_docx_to_field, fill_pdf_template

from .utils.offer_security import stamp_offer_letter_pdf
from admissions.utils.notification import create_notification
from django.core.mail import send_mail
import threading
from django.db import close_old_connections

import logging
import platform
from .tasks import send_offerletter_email, convert_and_save_pdf_task
import base64

logger = logging.getLogger(__name__)


def _offer_verify_public_base(request) -> str:
    """Base URL of the SPA for /verify-offer/{token} (no trailing slash)."""
    base = (getattr(settings, "OFFER_LETTER_PUBLIC_VERIFY_BASE", "") or "").strip().rstrip("/")
    if base:
        return base
    origin = (request.META.get("HTTP_ORIGIN") or "").strip().rstrip("/")
    if origin:
        return origin
    return "http://localhost:3001"


def _issue_offer_letter_audit(applicant: Application, user) -> str:
    """Create a fresh verification token and record who generated the letter."""
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


def _printed_by_label(user_id) -> str:
    if not user_id:
        return "system"
    User = get_user_model()
    u = User.objects.filter(pk=user_id).first()
    if not u:
        return "system"
    return (u.get_full_name() or u.username or str(u.pk)).strip()


if platform.system() == "Windows":
    try:
        import pythoncom
    except ImportError:
        # This will only happen if pywin32 is not installed on Windows
        print("Warning: pythoncom not found. DOCX to PDF conversion may fail on Windows.")

# import win32com.client

# Create your views here.

# upload template
class UploadTemplate(generics.CreateAPIView):
    queryset = OfferLetterTemplate.objects.all()
    serializer_class = TemplateSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    parser_classes = [MultiPartParser, FormParser]

# list templates
class ListTemplates(generics.ListAPIView):
    queryset = OfferLetterTemplate.objects.all()
    serializer_class = TemplateSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

# edit template
class EditTemplate(generics.UpdateAPIView):
    queryset = OfferLetterTemplate.objects.all()
    serializer_class = TemplateSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def put(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)  
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=200)
    
# delete template
class DeleteTemplate(generics.RetrieveDestroyAPIView):
    queryset = OfferLetterTemplate.objects.all()
    serializer_class = TemplateSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def delete(self, request, *args, **kwargs):
        insatnce = self.get_object()
        insatnce.delete()

        return Response({"detail":"template deleted successfully"})
    
# ================================================Offer letters======================================================
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def send_offer_letter(request, applicant_id):
    applicant = get_object_or_404(Application, pk=applicant_id)
    admission = get_object_or_404(AdmittedStudent, application=applicant)

    # 1. Choose template
    template = (
        OfferLetterTemplate.objects
        .filter(programs__id=admission.admitted_program_id)
        .filter(status="active")
        .order_by('-uploaded_at')
        .first()
    )

    if not template:
        return Response({"detail": "No template for this program is uploaded yet"}, status=400)

    # 2. Build context
    import random as _random

    if template.start_date:
        start_date_formatted = template.start_date.strftime("%B %d, %Y")
    else:
        start_date_formatted = "To Be Announced"

    halls = ["AKIIBUA", "NJUKI", "MUTEESA", "KAKUNGULU", "YOKANA"]
    if template.hall_of_residence == "RANDOM":
        hall = _random.choice(halls)
    elif template.hall_of_residence:
        hall = template.hall_of_residence
    else:
        hall = "To Be Assigned"

    # check title
    title = (applicant.title or "").strip()
    if not applicant.title:
       if applicant.gender and applicant.gender.lower() == "male":
           title = "MR."
       elif applicant.gender and applicant.gender.lower() == "female":
           title = "MS."    
           
    context = {
        "full_name": f"{title} {(applicant.first_name or '').strip()} {(applicant.last_name or '').strip()} {(applicant.middle_name or '').strip()}".upper(),
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
    }

    # 3. PDF template path: overlay text directly → no DOCX/LibreOffice needed
    if template.file_type == 'pdf':
        if not template.field_positions:
            return Response({"detail": "PDF template has no field positions configured. Use 'Map Fields' first."}, status=400)
        try:
            _issue_offer_letter_audit(applicant, request.user)
            verify_base = _offer_verify_public_base(request)
            verify_url = f"{verify_base}/verify-offer/{applicant.offer_letter_verification_token}"

            pdf_bytes = fill_pdf_template(template.file.path, context, template.field_positions)
            sys_name = getattr(settings, "OFFER_LETTER_SYSTEM_FOOTER_NAME", "ndu university admissions")
            gen_at = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M %Z")
            printed_by = _printed_by_label(getattr(request.user, "id", None))
            pdf_bytes = stamp_offer_letter_pdf(
                pdf_bytes,
                verify_url=verify_url,
                printed_by=printed_by,
                system_name=sys_name,
                generated_at=gen_at,
            )
        except Exception as e:
            logger.error(f"PDF fill failed for applicant {applicant_id}: {e}")
            return Response({"detail": "PDF template filling failed."}, status=500)

        pdf_filename = f"OfferLetter_{applicant.id}.pdf"
        applicant.admission_letter_pdf.save(pdf_filename, ContentFile(pdf_bytes))
        applicant.status = "Admitted"
        applicant.offer_letter_status = "email_sent"
        applicant.offer_letter_progress = 100
        applicant.save()
        send_offerletter_email.delay(applicant.id)
        return Response({
            "detail": "Offer letter generated from PDF template.",
            "status": "complete",
            "pdf_url": applicant.admission_letter_pdf.url,
            "verify_url": verify_url,
        })

    # 4. DOCX template: render then convert in background
    try:
        docx_bytes = render_docx_from_template(template.file.path, context)
    except Exception as e:
        logger.error(f"DOCX rendering failed for applicant {applicant_id}: {e}")
        return Response({"detail": "DOCX template rendering failed"}, status=500)

    _issue_offer_letter_audit(applicant, request.user)
    verify_base = _offer_verify_public_base(request)
    verify_url = f"{verify_base}/verify-offer/{applicant.offer_letter_verification_token}"

    docx_filename = f"OfferLetter_{applicant.id}.docx"
    applicant.admission_letter_docx.save(docx_filename, ContentFile(docx_bytes))
    applicant.save()

    # 🔥 Encode and send to Celery
    encoded_docx = base64.b64encode(docx_bytes).decode("utf-8")
    convert_and_save_pdf_task.delay(encoded_docx, applicant.id)


    return Response({
        "detail": "Offer letter DOCX saved. PDF generation, status update, and email are starting in the background.",
        "status": "processing",
        "docx_url": applicant.admission_letter_docx.url,
        "verify_url": verify_url,
    })

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def resend_offer_letter(request, applicant_id):
    applicant = get_object_or_404(Application, pk=applicant_id)

    if not applicant.admission_letter_pdf:
        return Response(
            {"detail": "No generated offer letter PDF found for this applicant. Generate first."},
            status=400,
        )

    # send_offerletter_email.delay(applicant.id)
    return Response(
        {"detail": "Offer letter email queued successfully.", "status": "queued"},
        status=200,
    )

def _active_template_program_ids() -> set[int]:
    return set(
        OfferLetterTemplate.objects.filter(status="active")
        .values_list("programs__id", flat=True)
        .distinct()
    )


def _eligible_offer_letter_application_ids(
    *,
    only_missing_pdf: bool = False,
    include_existing_pdf: bool = True,
    admitted_batch_id: int | None = None,
    program_id: int | None = None,
) -> list[int]:
    """
    Admitted, non-revoked students whose programme has an active offer-letter template.
    """
    program_ids = _active_template_program_ids()
    if not program_ids:
        return []

    qs = AdmittedStudent.objects.filter(
        is_admitted=True,
        application__is_revoked=False,
        admitted_program_id__in=program_ids,
    )
    if admitted_batch_id:
        qs = qs.filter(admitted_batch_id=admitted_batch_id)
    if program_id:
        qs = qs.filter(admitted_program_id=program_id)

    if only_missing_pdf:
        qs = qs.filter(
            Q(application__admission_letter_pdf__isnull=True)
            | Q(application__admission_letter_pdf="")
        )
    elif not include_existing_pdf:
        qs = qs.filter(
            Q(application__admission_letter_pdf__isnull=True)
            | Q(application__admission_letter_pdf="")
        )

    return list(
        qs.order_by("application_id").values_list("application_id", flat=True).distinct()
    )


def _process_bulk_offer_letters(request, application_ids: list[int]) -> dict:
    generated = 0
    reused_pdf = 0
    failed = 0
    errors = []

    for applicant_id in application_ids:
        try:
            applicant = Application.objects.filter(pk=applicant_id).first()
            if not applicant:
                failed += 1
                errors.append({"id": applicant_id, "detail": "Applicant not found."})
                continue

            if applicant.admission_letter_pdf:
                send_offerletter_email.delay(applicant.id)
                reused_pdf += 1
                continue

            single_response = send_offer_letter(request, applicant.id)
            if 200 <= single_response.status_code < 300:
                generated += 1
            else:
                failed += 1
                error_detail = "Failed to generate/send offer letter."
                if isinstance(single_response.data, dict):
                    error_detail = single_response.data.get("detail", error_detail)
                errors.append({"id": applicant_id, "detail": error_detail})
        except Exception as e:
            logger.error(
                f"Bulk offer letter processing failed for applicant {applicant_id}: {e}",
                exc_info=True,
            )
            failed += 1
            errors.append({"id": applicant_id, "detail": "Unexpected server error."})

    total = len(application_ids)
    return {
        "detail": (
            f"Processed {total} applicants. Generated+queued: {generated}, "
            f"Reused existing PDF+queued: {reused_pdf}, Failed: {failed}."
        ),
        "summary": {
            "total": total,
            "generated_and_queued": generated,
            "reused_existing_pdf_and_queued": reused_pdf,
            "failed": failed,
        },
        "errors": errors[:50],
        "status_code": 200 if failed == 0 else 207,
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def bulk_eligible_offer_letters_preview(request):
    """Count admitted students eligible for bulk offer-letter generation."""
    only_missing = request.query_params.get("only_missing_pdf", "true").lower() in (
        "1",
        "true",
        "yes",
    )
    admitted_batch_id = request.query_params.get("admitted_batch_id")
    program_id = request.query_params.get("program_id")
    try:
        batch_id = int(admitted_batch_id) if admitted_batch_id else None
    except (TypeError, ValueError):
        batch_id = None
    try:
        prog_id = int(program_id) if program_id else None
    except (TypeError, ValueError):
        prog_id = None

    program_ids = _active_template_program_ids()
    eligible_ids = _eligible_offer_letter_application_ids(
        only_missing_pdf=only_missing,
        admitted_batch_id=batch_id,
        program_id=prog_id,
    )
    all_eligible_ids = _eligible_offer_letter_application_ids(
        only_missing_pdf=False,
        admitted_batch_id=batch_id,
        program_id=prog_id,
    )

    admitted_total = AdmittedStudent.objects.filter(
        is_admitted=True,
        application__is_revoked=False,
    )
    if batch_id:
        admitted_total = admitted_total.filter(admitted_batch_id=batch_id)
    if prog_id:
        admitted_total = admitted_total.filter(admitted_program_id=prog_id)

    no_template = admitted_total.exclude(admitted_program_id__in=program_ids).count()

    return Response(
        {
            "programs_with_templates": len(program_ids),
            "eligible_to_process": len(eligible_ids),
            "eligible_with_template_total": len(all_eligible_ids),
            "without_template": no_template,
            "only_missing_pdf": only_missing,
            "application_ids_sample": eligible_ids[:20],
        }
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def bulk_send_offer_letters(request):
    """
    Generate (if needed) and queue offer letter emails.

    Either pass application_ids, or all_eligible=true for every admitted student
    whose programme has an active template.
    """
    all_eligible = request.data.get("all_eligible") in (True, "true", "yes", "1", 1)
    only_missing_pdf = request.data.get("only_missing_pdf", True)
    if isinstance(only_missing_pdf, str):
        only_missing_pdf = only_missing_pdf.lower() in ("1", "true", "yes")

    if all_eligible:
        batch_id = request.data.get("admitted_batch_id")
        prog_id = request.data.get("program_id")
        try:
            batch_id = int(batch_id) if batch_id not in (None, "") else None
        except (TypeError, ValueError):
            batch_id = None
        try:
            prog_id = int(prog_id) if prog_id not in (None, "") else None
        except (TypeError, ValueError):
            prog_id = None

        cleaned_ids = _eligible_offer_letter_application_ids(
            only_missing_pdf=only_missing_pdf,
            admitted_batch_id=batch_id,
            program_id=prog_id,
        )
        if not cleaned_ids:
            return Response(
                {
                    "detail": "No eligible admitted students found (need active template per programme).",
                    "summary": {
                        "total": 0,
                        "generated_and_queued": 0,
                        "reused_existing_pdf_and_queued": 0,
                        "failed": 0,
                    },
                },
                status=400,
            )
    else:
        raw_ids = request.data.get("application_ids", [])
        if not isinstance(raw_ids, list) or not raw_ids:
            return Response(
                {"detail": "application_ids must be a non-empty list, or set all_eligible=true."},
                status=400,
            )

        cleaned_ids = []
        for raw_id in raw_ids:
            try:
                cleaned_ids.append(int(raw_id))
            except (TypeError, ValueError):
                continue

        if not cleaned_ids:
            return Response({"detail": "No valid applicant IDs provided."}, status=400)

    result = _process_bulk_offer_letters(request, cleaned_ids)
    status_code = result.pop("status_code", 200)
    return Response(result, status=status_code)

@api_view(["GET"])
@permission_classes([AllowAny])
def verify_offer_letter_public(request, token: str):
    """Public: confirm an offer letter was issued by this system (no auth)."""
    app = (
        Application.objects.filter(offer_letter_verification_token=token)
        .select_related("offer_letter_generated_by")
        .first()
    )
    if not app:
        return Response(
            {"valid": False, "detail": "This verification link is not recognised."},
            status=status.HTTP_404_NOT_FOUND,
        )
    admission = (
        AdmittedStudent.objects.filter(application=app)
        .select_related("admitted_program")
        .first()
    )
    printed = None
    if app.offer_letter_generated_by_id:
        u = app.offer_letter_generated_by
        printed = (u.get_full_name() or u.username or str(u.pk)).strip()
    return Response(
        {
            "valid": True,
            "student_name": f"{app.first_name or ''} {app.last_name or ''}".strip().upper(),
            "programme": admission.admitted_program.name
            if admission and admission.admitted_program
            else None,
            "generated_at": app.offer_letter_generated_at.isoformat()
            if app.offer_letter_generated_at
            else None,
            "printed_by": printed,
            "system": getattr(
                settings, "OFFER_LETTER_SYSTEM_FOOTER_NAME", "ndu university admissions"
            ),
        }
    )

# offer letter status
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def offer_letter_status(request, applicant_id):
    app = get_object_or_404(Application, id=applicant_id)
    return Response({
        "status": app.offer_letter_status,
        "progress": app.offer_letter_progress,
        "docx_url": app.admission_letter_docx.url if app.admission_letter_docx else None,
        "pdf_url": app.admission_letter_pdf.url if app.admission_letter_pdf else None,
    })

# ── PDF template: preview first page as base64 PNG ──────────────────────────
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def pdf_template_preview(request, pk):
    template = get_object_or_404(OfferLetterTemplate, pk=pk)
    file_ext = os.path.splitext(template.file.name or "")[1].lower()
    is_pdf = (template.file_type == 'pdf') or (file_ext == '.pdf')
    if not is_pdf:
        return Response({'detail': 'Selected template is not a PDF file.'}, status=400)

    import fitz
    import base64

    try:
        doc = fitz.open(template.file.path)
        page = doc[0]
        pdf_width = page.rect.width
        pdf_height = page.rect.height
        mat = fitz.Matrix(2, 2)  # 2× zoom for sharp preview
        pix = page.get_pixmap(matrix=mat)
        img_b64 = base64.b64encode(pix.tobytes('png')).decode()
        doc.close()
    except Exception as e:
        logger.error(f"Failed to generate PDF preview for template {template.id}: {e}", exc_info=True)
        return Response({'detail': 'Failed to render PDF preview. Ensure the uploaded template is a valid PDF.'}, status=500)

    return Response({
        'image': img_b64,
        'pdf_width': pdf_width,
        'pdf_height': pdf_height,
        'field_positions': template.field_positions,
    })

# ── PDF template: save field positions ──────────────────────────────────────
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def save_pdf_field_positions(request, pk):
    template = get_object_or_404(OfferLetterTemplate, pk=pk)
    file_ext = os.path.splitext(template.file.name or "")[1].lower()
    is_pdf = (template.file_type == 'pdf') or (file_ext == '.pdf')
    if not is_pdf:
        return Response({'detail': 'Selected template is not a PDF file.'}, status=400)

    positions = request.data.get('field_positions', {})
    template.field_positions = positions
    template.save(update_fields=['field_positions'])
    return Response({'detail': 'Field positions saved successfully.'})