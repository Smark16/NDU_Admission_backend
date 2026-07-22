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
import uuid

from .tasks import (
    bulk_generate_offer_letters_task,
    load_bulk_offer_letter_job,
    save_bulk_offer_letter_job,
    send_offerletter_email,
    convert_and_save_pdf_task,
)
from .utils.offer_generation import generate_offer_letter_for_application, resolve_verify_base
from .utils.bulk_report import append_bulk_report_row, build_bulk_offer_letter_csv
import base64

BULK_SYNC_THRESHOLD = 25

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
    verify_base = _offer_verify_public_base(request)
    result = generate_offer_letter_for_application(
        int(applicant_id),
        request.user,
        verify_base=verify_base,
        send_email=True,
        skip_if_pdf_exists=False,
    )
    if not result.get("ok"):
        status_code = status.HTTP_400_BAD_REQUEST
        if "failed" in (result.get("detail") or "").lower():
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return Response({"detail": result.get("detail", "Offer letter generation failed.")}, status=status_code)

    applicant = get_object_or_404(Application, pk=applicant_id)
    payload = {
        "detail": result.get("detail"),
        "status": result.get("status"),
        "application_id": applicant.id,
    }
    if applicant.offer_letter_verification_token:
        payload["verify_url"] = f"{verify_base}/verify-offer/{applicant.offer_letter_verification_token}"
    if applicant.admission_letter_pdf and getattr(applicant.admission_letter_pdf, "name", None):
        payload["pdf_url"] = applicant.admission_letter_pdf.url
    if applicant.admission_letter_docx and getattr(applicant.admission_letter_docx, "name", None):
        payload["docx_url"] = applicant.admission_letter_docx.url
    return Response(payload, status=status.HTTP_200_OK)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def resend_offer_letter(request, applicant_id):
    applicant = get_object_or_404(Application, pk=applicant_id)

    if not applicant.admission_letter_pdf:
        return Response(
            {"detail": "No generated offer letter PDF found for this applicant. Generate first."},
            status=400,
        )

    send_offerletter_email.delay(applicant.id)
    applicant.offer_letter_status = "email_sent"
    applicant.save(update_fields=["offer_letter_status"])
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


def _missing_offer_letter_pdf_q() -> Q:
    return Q(application__admission_letter_pdf__isnull=True) | Q(
        application__admission_letter_pdf=""
    )


def _has_offer_letter_pdf_q() -> Q:
    return (
        Q(application__admission_letter_pdf__isnull=False)
        & ~Q(application__admission_letter_pdf="")
    )


def _parse_optional_int(value) -> int | None:
    if value in (None, "", "all"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_offer_letter_scope(source) -> dict:
    """Normalize scope filters from query params or request body."""
    batch_name = (source.get("batch") or source.get("admitted_batch_name") or "").strip()
    program_name = (source.get("program") or source.get("program_name") or "").strip()
    return {
        "admitted_batch_id": _parse_optional_int(source.get("admitted_batch_id")),
        "admitted_batch_name": batch_name or None,
        "program_id": _parse_optional_int(source.get("program_id")),
        "program_name": program_name or None,
        "academic_batch_id": _parse_optional_int(source.get("academic_batch_id")),
    }


def _apply_offer_letter_scope_filters(qs, scope: dict):
    if scope.get("admitted_batch_id"):
        qs = qs.filter(admitted_batch_id=scope["admitted_batch_id"])
    if scope.get("admitted_batch_name"):
        qs = qs.filter(admitted_batch__name=scope["admitted_batch_name"])
    if scope.get("program_id"):
        qs = qs.filter(admitted_program_id=scope["program_id"])
    if scope.get("program_name"):
        qs = qs.filter(admitted_program__name__icontains=scope["program_name"])
    if scope.get("academic_batch_id"):
        qs = qs.filter(intended_program_batch_id=scope["academic_batch_id"])
    return qs


def _admitted_students_in_scope(scope: dict):
    from admissions.models import Application

    qs = AdmittedStudent.objects.filter(
        is_admitted=True,
        application__is_revoked=False,
    ).exclude(
        application__source=Application.SOURCE_LEGACY,
    )
    return _apply_offer_letter_scope_filters(qs, scope)


def _eligible_offer_letter_application_ids(
    *,
    only_missing_pdf: bool = False,
    include_existing_pdf: bool = True,
    admitted_batch_id: int | None = None,
    program_id: int | None = None,
    admitted_batch_name: str | None = None,
    program_name: str | None = None,
    academic_batch_id: int | None = None,
    scope: dict | None = None,
) -> list[int]:
    """
    Admitted, non-revoked students whose programme has an active offer-letter template.

    Legacy CSV imports are excluded — they already have historical offer letters.
    """
    from admissions.models import Application

    program_ids = _active_template_program_ids()
    if not program_ids:
        return []

    scope = scope or {
        "admitted_batch_id": admitted_batch_id,
        "admitted_batch_name": admitted_batch_name,
        "program_id": program_id,
        "program_name": program_name,
        "academic_batch_id": academic_batch_id,
    }

    qs = AdmittedStudent.objects.filter(
        is_admitted=True,
        application__is_revoked=False,
        admitted_program_id__in=program_ids,
    ).exclude(
        application__source=Application.SOURCE_LEGACY,
    )
    qs = _apply_offer_letter_scope_filters(qs, scope)

    if only_missing_pdf:
        qs = qs.filter(_missing_offer_letter_pdf_q())
    elif not include_existing_pdf:
        qs = qs.filter(_missing_offer_letter_pdf_q())

    return list(
        qs.order_by("application_id").values_list("application_id", flat=True).distinct()
    )


def _offer_letter_scope_summary(scope: dict, *, only_missing_pdf: bool = True) -> dict:
    """Counts for admin bulk-generation preview."""
    program_ids = _active_template_program_ids()
    admitted_in_scope = _admitted_students_in_scope(scope)
    admitted_total = admitted_in_scope.count()

    if not program_ids:
        return {
            "programs_with_templates": 0,
            "admitted_in_scope": admitted_total,
            "eligible_to_process": 0,
            "eligible_with_template_total": 0,
            "already_have_pdf": 0,
            "without_template": admitted_total,
            "only_missing_pdf": only_missing_pdf,
            "application_ids_sample": [],
            "scope": scope,
        }

    with_template = _apply_offer_letter_scope_filters(
        AdmittedStudent.objects.filter(
            is_admitted=True,
            application__is_revoked=False,
            admitted_program_id__in=program_ids,
        ).exclude(
            application__source=Application.SOURCE_LEGACY,
        ),
        scope,
    )
    eligible_with_template_total = with_template.count()
    already_have_pdf = with_template.filter(_has_offer_letter_pdf_q()).count()
    eligible_to_process = (
        with_template.filter(_missing_offer_letter_pdf_q()).count()
        if only_missing_pdf
        else eligible_with_template_total
    )
    without_template = admitted_total - eligible_with_template_total

    eligible_ids = _eligible_offer_letter_application_ids(
        only_missing_pdf=only_missing_pdf,
        scope=scope,
    )

    return {
        "programs_with_templates": len(program_ids),
        "admitted_in_scope": admitted_total,
        "eligible_to_process": len(eligible_ids),
        "eligible_with_template_total": eligible_with_template_total,
        "already_have_pdf": already_have_pdf,
        "without_template": max(without_template, 0),
        "only_missing_pdf": only_missing_pdf,
        "application_ids_sample": eligible_ids[:20],
        "scope": scope,
    }


def _bool_request_flag(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("1", "true", "yes")


def _process_bulk_offer_letters_sync(
    request,
    application_ids: list[int],
    *,
    send_email: bool = False,
    only_missing_pdf: bool = True,
) -> dict:
    generated = 0
    reused_pdf = 0
    failed = 0
    job_id = uuid.uuid4().hex
    job: dict = {
        "job_id": job_id,
        "status": "running",
        "total": len(application_ids),
        "processed": 0,
        "generated": 0,
        "reused": 0,
        "failed": 0,
        "report_rows": [],
        "send_email": send_email,
        "only_missing_pdf": only_missing_pdf,
        "started_by": getattr(request.user, "id", None),
        "created_at": timezone.now().isoformat(),
        "async": False,
    }
    verify_base = resolve_verify_base(request)

    for index, applicant_id in enumerate(application_ids, start=1):
        result = generate_offer_letter_for_application(
            applicant_id,
            request.user,
            verify_base=verify_base,
            send_email=send_email,
            skip_if_pdf_exists=only_missing_pdf,
        )
        if result.get("ok"):
            if result.get("status") == "skipped":
                reused_pdf += 1
                append_bulk_report_row(
                    job,
                    applicant_id,
                    "reused_existing_pdf",
                    result.get("detail") or "Existing PDF reused.",
                )
            elif result.get("status") == "processing":
                generated += 1
                append_bulk_report_row(
                    job,
                    applicant_id,
                    "processing",
                    "DOCX rendered; PDF conversion queued in background.",
                )
            else:
                generated += 1
                append_bulk_report_row(
                    job,
                    applicant_id,
                    "generated",
                    result.get("detail") or "Offer letter PDF generated.",
                )
        else:
            failed += 1
            append_bulk_report_row(
                job,
                applicant_id,
                "failed",
                result.get("detail", "Generation failed."),
            )
        job["processed"] = index

    total = len(application_ids)
    job["status"] = "complete"
    job["finished_at"] = timezone.now().isoformat()
    job["generated"] = generated
    job["reused"] = reused_pdf
    job["failed"] = failed
    job["errors"] = [
        {"id": r["application_id"], "detail": r.get("detail") or "Generation failed."}
        for r in job.get("report_rows", [])
        if r.get("outcome") == "failed"
    ]
    save_bulk_offer_letter_job(job_id, job)

    return {
        "detail": (
            f"Processed {total} applicants. Generated: {generated}, "
            f"Reused existing PDF: {reused_pdf}, Failed: {failed}."
        ),
        "async": False,
        "job_id": job_id,
        "report_url": f"/api/offer_letter/bulk_job_report/{job_id}",
        "summary": {
            "total": total,
            "generated_and_queued": generated,
            "reused_existing_pdf_and_queued": reused_pdf,
            "failed": failed,
        },
        "errors": job["errors"][:50],
        "status_code": 200 if failed == 0 else 207,
    }


def _queue_bulk_offer_letters_async(
    request,
    application_ids: list[int],
    *,
    send_email: bool = False,
    only_missing_pdf: bool = True,
) -> dict:
    job_id = uuid.uuid4().hex
    job_payload = {
        "job_id": job_id,
        "status": "queued",
        "total": len(application_ids),
        "processed": 0,
        "generated": 0,
        "reused": 0,
        "failed": 0,
        "errors": [],
        "report_rows": [],
        "send_email": send_email,
        "only_missing_pdf": only_missing_pdf,
        "started_by": getattr(request.user, "id", None),
        "created_at": timezone.now().isoformat(),
    }
    save_bulk_offer_letter_job(job_id, job_payload)
    bulk_generate_offer_letters_task.delay(
        job_id,
        application_ids,
        request.user.id,
        send_email=send_email,
        skip_if_pdf_exists=only_missing_pdf,
        verify_base=resolve_verify_base(request),
    )
    return {
        "detail": (
            f"Bulk offer letter job queued for {len(application_ids)} applicant(s). "
            "Poll bulk_job_status for progress."
        ),
        "async": True,
        "job_id": job_id,
        "total": len(application_ids),
        "status_url": f"/api/offer_letter/bulk_job_status/{job_id}",
        "report_url": f"/api/offer_letter/bulk_job_report/{job_id}",
        "status_code": 202,
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
    scope = _parse_offer_letter_scope(request.query_params)
    return Response(_offer_letter_scope_summary(scope, only_missing_pdf=only_missing))


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
        scope = _parse_offer_letter_scope(request.data)
        cleaned_ids = _eligible_offer_letter_application_ids(
            only_missing_pdf=only_missing_pdf,
            scope=scope,
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

    if "send_email" in request.data:
        send_email = _bool_request_flag(request.data.get("send_email"), default=False)
    elif all_eligible:
        send_email = False
    else:
        # Selected application_ids: generate if needed and email by default.
        send_email = True
    force_async = _bool_request_flag(request.data.get("async"), default=False)
    use_async = force_async or all_eligible or len(cleaned_ids) > BULK_SYNC_THRESHOLD

    if use_async:
        result = _queue_bulk_offer_letters_async(
            request,
            cleaned_ids,
            send_email=send_email,
            only_missing_pdf=only_missing_pdf,
        )
    else:
        result = _process_bulk_offer_letters_sync(
            request,
            cleaned_ids,
            send_email=send_email,
            only_missing_pdf=only_missing_pdf,
        )

    status_code = result.pop("status_code", 200)
    return Response(result, status=status_code)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def bulk_offer_letter_job_status(request, job_id):
    job = load_bulk_offer_letter_job(job_id)
    if not job:
        return Response({"detail": "Bulk job not found or expired."}, status=404)
    if not job.get("errors") and job.get("report_rows"):
        job = {
            **job,
            "errors": [
                {"id": r["application_id"], "detail": r.get("detail") or "Generation failed."}
                for r in job["report_rows"]
                if r.get("outcome") == "failed"
            ],
        }
    payload = {**job, "report_url": f"/api/offer_letter/bulk_job_report/{job_id}"}
    return Response(payload)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def bulk_offer_letter_job_report(request, job_id):
    """Download CSV report for a bulk offer-letter job (all rows or errors only)."""
    from django.http import HttpResponse

    job = load_bulk_offer_letter_job(job_id)
    if not job:
        return Response({"detail": "Bulk job not found or expired."}, status=404)

    errors_only = request.query_params.get("type", "all").lower() in (
        "errors",
        "failed",
        "error",
    )
    csv_text = build_bulk_offer_letter_csv(job, errors_only=errors_only)
    suffix = "errors" if errors_only else "full"
    filename = f"offer_letter_bulk_{job_id[:8]}_{suffix}.csv"
    response = HttpResponse(csv_text, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


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
    from accounts.portal_branding import get_offer_letter_footer_name

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
                settings, "OFFER_LETTER_SYSTEM_FOOTER_NAME", None
            ) or get_offer_letter_footer_name(),
        }
    )

# offer letter status
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def diagnose_offer_letter_readiness(request, application_id):
    """Pre-flight checks — same rules as bulk/single generation."""
    from admissions.admission_specialization import validate_offer_letter_admission
    from OfferLetter.AdmissionLetter.utils.offer_generation import (
        _active_template_for_program,
        _has_stored_offer_letter_pdf,
        _resolve_admission_for_offer_letter,
    )

    applicant = Application.objects.filter(pk=application_id).first()
    if not applicant:
        return Response(
            {"application_id": application_id, "ready": False, "checks": [{"ok": False, "detail": "Applicant not found."}]},
            status=404,
        )

    checks: list[dict] = []
    if applicant.is_revoked:
        checks.append({"ok": False, "code": "revoked", "detail": "Application admission is revoked."})

    admission = _resolve_admission_for_offer_letter(applicant)
    if admission is None:
        checks.append({"ok": False, "code": "admission", "detail": "No AdmittedStudent record linked to this application."})
    else:
        checks.append(
            {
                "ok": bool(admission.is_admitted),
                "code": "is_admitted",
                "detail": "Active admission flag is set." if admission.is_admitted else "is_admitted is false on AdmittedStudent.",
            }
        )
        combo_err = validate_offer_letter_admission(admission)
        if combo_err:
            checks.append({"ok": False, "code": "combination", "detail": combo_err})
        else:
            checks.append({"ok": True, "code": "combination", "detail": "Teaching combination / specialization OK."})

        template = _active_template_for_program(admission.admitted_program_id)
        if template is None:
            checks.append({"ok": False, "code": "template", "detail": "No active offer-letter template for this programme."})
        else:
            checks.append(
                {
                    "ok": True,
                    "code": "template",
                    "detail": f"Active template #{template.id} ({template.file_type}).",
                }
            )
            if template.file_type == "pdf" and not template.field_positions:
                checks.append(
                    {
                        "ok": False,
                        "code": "pdf_fields",
                        "detail": "PDF template has no field positions configured.",
                    }
                )
            try:
                with template.file.open("rb") as handle:
                    handle.read(1)
                checks.append({"ok": True, "code": "template_file", "detail": "Template file is readable from storage."})
            except Exception as exc:
                checks.append(
                    {
                        "ok": False,
                        "code": "template_file",
                        "detail": f"Template file not readable: {exc}",
                    }
                )

    if _has_stored_offer_letter_pdf(applicant):
        checks.append(
            {
                "ok": True,
                "code": "existing_pdf",
                "detail": "Offer letter PDF already on file (bulk only_missing_pdf skips regeneration).",
            }
        )

    blocking = [c for c in checks if not c.get("ok")]
    return Response(
        {
            "application_id": application_id,
            "ready": len(blocking) == 0,
            "blocking_count": len(blocking),
            "checks": checks,
        }
    )


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