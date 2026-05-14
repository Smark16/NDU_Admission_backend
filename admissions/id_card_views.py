"""ID card issuance API (admin / Student ID Officer)."""

from __future__ import annotations

import secrets
import json
from datetime import date, timedelta

import mimetypes

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from io import BytesIO

from PIL import Image
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.http import FileResponse

from accounts.models import Campus, SystemSettings
from audit.utils import log_audit_event
from Programs.models import Program

from .models import AdmittedStudent, Batch, Faculty, StudentIdCard
from .permissions import ManageIdCardsPermission


def _default_expiry(issue: date) -> date:
    return issue + timedelta(days=365 * 4)


def _ordinal_day(day: int) -> str:
    if 11 <= (day % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def _issue_date_display(d: date) -> str:
    return f"{_ordinal_day(d.day)} {d.strftime('%B %Y')}"


def _default_id_card_return_address() -> str:
    return (
        "Office of the Academic Registrar\n"
        "Ndejje University\n"
        "P. O. Box 7088 Kampala, Uganda\n"
        "Tel: +256-392-730321\n"
        "Email: registrar@ndejjeuniversity.ac.ug"
    )


def _allocate_card_number() -> str:
    year = timezone.now().year
    for _ in range(32):
        tail = secrets.token_hex(3).upper()
        candidate = f"NDU-{year}-{tail}"
        if not StudentIdCard.objects.filter(card_number=candidate).exists():
            return candidate
    raise RuntimeError("Could not allocate a unique card number")


def _passport_absolute_url(request, application) -> str | None:
    photo = application.passport_photo
    if not photo or not getattr(photo, "name", None):
        return None
    try:
        return request.build_absolute_uri(photo.url)
    except ValueError:
        return None


def _active_card_subquery():
    return StudentIdCard.objects.filter(
        admitted_student_id=OuterRef("pk"),
        is_active=True,
    ).exclude(status=StudentIdCard.STATUS_REVOKED)


def _eligible_base_qs():
    return (
        AdmittedStudent.objects.filter(
            is_admitted=True,
            application__is_revoked=False,
            physical_documents_verified=True,
        )
        .exclude(Q(student_id__isnull=True) | Q(student_id__exact=""))
        .annotate(_has_active_card=Exists(_active_card_subquery()))
        .filter(_has_active_card=False)
        .select_related("application", "admitted_program", "admitted_program__faculty", "admitted_campus", "admitted_batch")
    )


def _search_admitted(qs, q: str):
    q = (q or "").strip()
    if not q:
        return qs
    return qs.filter(
        Q(application__first_name__icontains=q)
        | Q(application__last_name__icontains=q)
        | Q(application__middle_name__icontains=q)
        | Q(student_id__icontains=q)
        | Q(reg_no__icontains=q)
    )


def _parse_int_param(request, key: str) -> int | None:
    raw = request.query_params.get(key)
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return int(str(raw).strip())
    except ValueError:
        return None


def _parse_str_param(request, key: str) -> str | None:
    raw = request.query_params.get(key)
    if raw is None:
        return None
    s = str(raw).strip()
    return s or None


def _apply_scope_to_admitted_qs(qs, request):
    """Filter admitted students by intake (batch), academic year, campus, faculty, programme."""
    batch_id = _parse_int_param(request, "batch_id")
    campus_id = _parse_int_param(request, "campus_id")
    faculty_id = _parse_int_param(request, "faculty_id")
    program_id = _parse_int_param(request, "program_id")
    academic_year = _parse_str_param(request, "academic_year")

    if batch_id is not None:
        qs = qs.filter(admitted_batch_id=batch_id)
    if campus_id is not None:
        qs = qs.filter(admitted_campus_id=campus_id)
    if program_id is not None:
        qs = qs.filter(admitted_program_id=program_id)
    if faculty_id is not None:
        qs = qs.filter(admitted_program__faculty_id=faculty_id)
    if academic_year is not None:
        qs = qs.filter(admitted_batch__academic_year__iexact=academic_year)
    return qs


def _apply_scope_to_card_qs(qs, request):
    """Same scope filters, applied through StudentIdCard → admitted_student."""
    batch_id = _parse_int_param(request, "batch_id")
    campus_id = _parse_int_param(request, "campus_id")
    faculty_id = _parse_int_param(request, "faculty_id")
    program_id = _parse_int_param(request, "program_id")
    academic_year = _parse_str_param(request, "academic_year")

    if batch_id is not None:
        qs = qs.filter(admitted_student__admitted_batch_id=batch_id)
    if campus_id is not None:
        qs = qs.filter(admitted_student__admitted_campus_id=campus_id)
    if program_id is not None:
        qs = qs.filter(admitted_student__admitted_program_id=program_id)
    if faculty_id is not None:
        qs = qs.filter(admitted_student__admitted_program__faculty_id=faculty_id)
    if academic_year is not None:
        qs = qs.filter(admitted_student__admitted_batch__academic_year__iexact=academic_year)
    return qs


def _filter_options_admitted_scope():
    """Active admissions with physical documents verified — used for ID card filter dropdowns."""
    return AdmittedStudent.objects.filter(
        is_admitted=True,
        application__is_revoked=False,
        physical_documents_verified=True,
    )


def _eligible_payload(request, admitted: AdmittedStudent) -> dict:
    app = admitted.application
    photo = app.passport_photo
    has_photo = bool(photo and getattr(photo, "name", None))
    faculty_name = ""
    if admitted.admitted_program_id and admitted.admitted_program.faculty_id:
        faculty_name = admitted.admitted_program.faculty.name
    return {
        "id": admitted.id,
        "student_id": admitted.student_id or "",
        "reg_no": admitted.reg_no or "",
        "name": admitted.full_name,
        "gender": app.gender or "",
        "program": admitted.admitted_program.name if admitted.admitted_program_id else "",
        "campus": admitted.admitted_campus.name if admitted.admitted_campus_id else "",
        "batch": admitted.admitted_batch.name if admitted.admitted_batch_id else "",
        "academic_year": admitted.admitted_batch.academic_year if admitted.admitted_batch_id else "",
        "faculty": faculty_name,
        "is_registered": admitted.is_registered,
        "physical_documents_verified": admitted.physical_documents_verified,
        "has_passport_photo": has_photo,
    }


def _card_payload(card: StudentIdCard) -> dict:
    st = card.admitted_student
    return {
        "id": card.id,
        "admitted_student": st.id,
        "admitted_student_name": st.full_name,
        "student_id": st.student_id or "",
        "reg_no": st.reg_no or "",
        "card_number": card.card_number,
        "status": card.status,
        "issue_date": card.issue_date.isoformat() if card.issue_date else None,
        "expiry_date": card.expiry_date.isoformat() if card.expiry_date else None,
        "is_active": card.is_active,
        "print_count": card.print_count,
    }


def _resolve_template_dict() -> dict | None:
    settings_obj = SystemSettings.get_settings()
    active_key = (getattr(settings_obj, "active_id_card_template", None) or "").strip()
    if active_key:
        from .models import IdCardPdfTemplate

        pdf_row = IdCardPdfTemplate.objects.filter(key=active_key).first()
        if pdf_row:
            return {
                "key": pdf_row.key,
                "name": pdf_row.name,
                "front_title": pdf_row.front_title or "NDEJJE UNIVERSITY",
                "back_text": "",
                "institution": pdf_row.institution or "Ndejje University",
                "issuer_title": pdf_row.issuer_title or "",
                "issuer_signatory": pdf_row.issuer_signatory or "",
                "return_to": pdf_row.return_to or "",
                "tel": pdf_row.tel or "",
                "email": pdf_row.email or "",
                "field_positions": pdf_row.field_positions or {},
            }

    templates = getattr(settings_obj, "id_card_templates", None) or []
    if not isinstance(templates, list):
        templates = []
    chosen = None
    if active_key:
        for row in templates:
            if isinstance(row, dict) and row.get("key") == active_key:
                chosen = row
                break
    if chosen is None and templates:
        first = templates[0]
        chosen = first if isinstance(first, dict) else None
    return chosen


def _preview_payload(request, card: StudentIdCard) -> dict:
    st = card.admitted_student
    app = st.application
    tmpl = _resolve_template_dict() or {}
    issue = card.issue_date or timezone.now().date()
    expiry = card.expiry_date or _default_expiry(issue)
    student_no = st.student_id or ""
    return_to = (tmpl.get("return_to") or tmpl.get("back_text") or "").strip()
    if not return_to:
        return_to = _default_id_card_return_address()
    institution = (tmpl.get("institution") or "Ndejje University").strip()
    qr_obj = {
        "v": 1,
        "type": "ndu_student_id",
        "card_number": card.card_number,
        "name": st.full_name,
        "student_no": student_no,
        "reg_no": st.reg_no or "",
        "course": st.admitted_program.name if st.admitted_program_id else "",
        "gender": app.gender or "",
        "expiry_date": expiry.isoformat(),
    }
    return {
        "card_number": card.card_number,
        "template": {
            "key": tmpl.get("key"),
            "name": tmpl.get("name"),
            "front_title": tmpl.get("front_title"),
            "back_text": tmpl.get("back_text"),
        },
        "front": {
            "name": st.full_name,
            "student_no": student_no,
            "reg_no": st.reg_no or "",
            "course": st.admitted_program.name if st.admitted_program_id else "",
            "gender": app.gender or "",
            "expiry_date": expiry.isoformat(),
            "barcode_value": student_no or st.reg_no or card.card_number,
            "qr_payload": json.dumps(qr_obj, ensure_ascii=False),
            "passport_photo": _passport_absolute_url(request, app),
        },
        "back": {
            "institution": institution,
            "issuer_title": tmpl.get("issuer_title") or "Academic Registrar",
            "issuer_signatory": (tmpl.get("issuer_signatory") or "M. Nanda").strip(),
            "issued_on": issue.isoformat(),
            "issued_on_display": _issue_date_display(issue),
            "return_to": return_to,
            "tel": tmpl.get("tel") or "",
            "email": tmpl.get("email") or "",
        },
    }


class IdCardFilterOptionsView(APIView):
    """Dropdown values derived from admitted students (no extra model permissions required)."""

    permission_classes = [IsAuthenticated, ManageIdCardsPermission]

    def get(self, request):
        scope = _filter_options_admitted_scope()
        batch_ids = scope.values_list("admitted_batch_id", flat=True).distinct()
        campus_ids = scope.values_list("admitted_campus_id", flat=True).distinct()
        program_ids = scope.values_list("admitted_program_id", flat=True).distinct()

        batches = list(
            Batch.objects.filter(pk__in=batch_ids)
            .order_by("-created_at")
            .values("id", "name", "code", "academic_year")
        )
        years_set = {b.get("academic_year") or "" for b in batches}
        years_set.discard("")
        academic_years = sorted(years_set, reverse=True)

        campuses = list(
            Campus.objects.filter(pk__in=campus_ids).order_by("name").values("id", "name", "code")
        )
        programs = list(
            Program.objects.filter(pk__in=program_ids)
            .order_by("name")
            .values("id", "name", "code", "faculty_id")
        )
        faculty_ids = {p["faculty_id"] for p in programs if p.get("faculty_id")}
        faculties = list(
            Faculty.objects.filter(pk__in=faculty_ids).order_by("name").values("id", "name", "code")
        )

        return Response(
            {
                "academic_years": academic_years,
                "batches": batches,
                "faculties": faculties,
                "campuses": campuses,
                "programs": programs,
            }
        )


ID_CARD_PASSPORT_MAX_BYTES = 6 * 1024 * 1024


class IdCardAdmittedPassportPhotoView(APIView):
    """Read or replace the applicant passport photo used for ID cards (upload from desk or camera)."""

    permission_classes = [IsAuthenticated, ManageIdCardsPermission]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request, admitted_student_id: int):
        admitted = (
            AdmittedStudent.objects.select_related("application")
            .filter(pk=admitted_student_id)
            .first()
        )
        if not admitted:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if not admitted.physical_documents_verified:
            return Response(status=status.HTTP_404_NOT_FOUND)
        photo = admitted.application.passport_photo
        if not photo or not getattr(photo, "name", None):
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            fh = photo.open("rb")
        except Exception:
            return Response(status=status.HTTP_404_NOT_FOUND)
        content_type = mimetypes.guess_type(photo.name)[0] or "image/jpeg"
        return FileResponse(fh, content_type=content_type)

    def post(self, request, admitted_student_id: int):
        uploaded = request.FILES.get("passport_photo")
        if not uploaded:
            return Response({"detail": "passport_photo file is required."}, status=status.HTTP_400_BAD_REQUEST)

        admitted = (
            AdmittedStudent.objects.select_related("application")
            .filter(pk=admitted_student_id)
            .first()
        )
        if not admitted:
            return Response({"detail": "Admitted student not found."}, status=status.HTTP_404_NOT_FOUND)
        if not admitted.is_admitted or admitted.application.is_revoked:
            return Response({"detail": "Student is not eligible."}, status=status.HTTP_400_BAD_REQUEST)
        if not admitted.physical_documents_verified:
            return Response(
                {"detail": "Physical documents must be verified before updating the passport photo."},
                status=400,
            )

        raw = uploaded.read()
        if len(raw) > ID_CARD_PASSPORT_MAX_BYTES:
            return Response(
                {"detail": "Image is too large (max 6 MB)."},
                status=400,
            )
        if len(raw) < 256:
            return Response({"detail": "Image file is too small or empty."}, status=400)

        try:
            Image.open(BytesIO(raw)).verify()
        except Exception:
            return Response({"detail": "Invalid image file. Use JPEG or PNG."}, status=400)

        try:
            im = Image.open(BytesIO(raw))
            if im.mode in ("RGBA", "P"):
                im = im.convert("RGB")
            else:
                im = im.convert("RGB")
            w, h = im.size
            if w < 64 or h < 64:
                return Response(
                    {"detail": "Image is too small. Minimum size 64×64 pixels."},
                    status=400,
                )
            out = BytesIO()
            im.save(out, format="JPEG", quality=90)
            out.seek(0)
            jpeg_bytes = out.read()
        except Exception:
            return Response({"detail": "Could not process this image. Try another file."}, status=400)

        application = admitted.application
        fname = f"passport_app_{application.pk}.jpg"
        with transaction.atomic():
            application.passport_photo.save(fname, ContentFile(jpeg_bytes), save=True)

        log_audit_event(
            request.user,
            "passport_photo_update",
            admitted,
            f"Passport / ID photo updated for admitted student id={admitted.pk}",
            request,
        )
        return Response(
            {
                "detail": "Photo updated.",
                "has_passport_photo": True,
            },
            status=status.HTTP_200_OK,
        )

    def delete(self, request, admitted_student_id: int):
        admitted = (
            AdmittedStudent.objects.select_related("application")
            .filter(pk=admitted_student_id)
            .first()
        )
        if not admitted:
            return Response({"detail": "Admitted student not found."}, status=status.HTTP_404_NOT_FOUND)
        if not admitted.is_admitted or admitted.application.is_revoked:
            return Response({"detail": "Student is not eligible."}, status=status.HTTP_400_BAD_REQUEST)
        if not admitted.physical_documents_verified:
            return Response(
                {"detail": "Physical documents must be verified before changing the passport photo."},
                status=400,
            )

        application = admitted.application
        if not application.passport_photo:
            return Response({"detail": "No passport photo on file."}, status=status.HTTP_404_NOT_FOUND)

        with transaction.atomic():
            application.passport_photo.delete(save=True)

        log_audit_event(
            request.user,
            "passport_photo_delete",
            admitted,
            f"Passport / ID photo removed for admitted student id={admitted.pk}",
            request,
        )
        return Response(
            {"detail": "Photo removed.", "has_passport_photo": False},
            status=status.HTTP_200_OK,
        )


class IdCardEligibleListView(APIView):
    permission_classes = [IsAuthenticated, ManageIdCardsPermission]

    def get(self, request):
        qs = _eligible_base_qs()
        qs = _apply_scope_to_admitted_qs(qs, request)
        qs = _search_admitted(qs, request.query_params.get("q", ""))
        qs = qs.select_related("admitted_program", "admitted_program__faculty").order_by("-admission_date")[:500]
        return Response([_eligible_payload(request, row) for row in qs])


class IdCardListView(APIView):
    permission_classes = [IsAuthenticated, ManageIdCardsPermission]

    def get(self, request):
        qs = StudentIdCard.objects.select_related(
            "admitted_student",
            "admitted_student__application",
            "admitted_student__admitted_program",
            "admitted_student__admitted_batch",
            "admitted_student__admitted_campus",
        ).order_by("-created_at")
        qs = _apply_scope_to_card_qs(qs, request)
        q = request.query_params.get("q", "")
        if q.strip():
            qt = q.strip()
            qs = qs.filter(
                Q(card_number__icontains=qt)
                | Q(admitted_student__student_id__icontains=qt)
                | Q(admitted_student__reg_no__icontains=qt)
                | Q(admitted_student__application__first_name__icontains=qt)
                | Q(admitted_student__application__last_name__icontains=qt)
            )
        st = request.query_params.get("status", "")
        if st.strip():
            qs = qs.filter(status=st.strip())
        return Response([_card_payload(c) for c in qs[:1000]])


class IdCardGenerateView(APIView):
    permission_classes = [IsAuthenticated, ManageIdCardsPermission]

    def post(self, request):
        try:
            admitted_id = int(request.data.get("admitted_student_id"))
        except (TypeError, ValueError):
            return Response({"detail": "admitted_student_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        admitted = AdmittedStudent.objects.select_related("application").filter(pk=admitted_id).first()
        if not admitted:
            return Response({"detail": "Admitted student not found."}, status=status.HTTP_404_NOT_FOUND)
        if not admitted.is_admitted or admitted.application.is_revoked:
            return Response({"detail": "Student is not eligible for an ID card."}, status=status.HTTP_400_BAD_REQUEST)
        if not admitted.physical_documents_verified:
            return Response(
                {"detail": "Physical documents must be verified before issuing an ID card."},
                status=400,
            )
        if not (admitted.student_id or "").strip():
            return Response({"detail": "Student number must be assigned before generating an ID card."}, status=400)
        photo = admitted.application.passport_photo
        if not photo or not getattr(photo, "name", None):
            return Response({"detail": "A passport photo is required on the application."}, status=400)
        if StudentIdCard.objects.filter(admitted_student=admitted, is_active=True).exists():
            return Response({"detail": "An active ID card already exists for this student."}, status=400)

        issue = timezone.now().date()
        expiry = _default_expiry(issue)
        with transaction.atomic():
            card = StudentIdCard.objects.create(
                admitted_student=admitted,
                card_number=_allocate_card_number(),
                status=StudentIdCard.STATUS_GENERATED,
                is_active=True,
                issue_date=issue,
                expiry_date=expiry,
                issued_by=request.user,
            )
        log_audit_event(
            request.user,
            "id_card_generate",
            admitted,
            f"Issued ID card {card.card_number}",
            request,
        )
        return Response(_card_payload(card), status=status.HTTP_201_CREATED)


class IdCardPreviewDataView(APIView):
    permission_classes = [IsAuthenticated, ManageIdCardsPermission]

    def get(self, request, card_id: int):
        card = StudentIdCard.objects.select_related(
            "admitted_student", "admitted_student__application", "admitted_student__admitted_program"
        ).filter(pk=card_id).first()
        if not card:
            return Response({"detail": "ID card not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(_preview_payload(request, card))


class IdCardRevokeView(APIView):
    permission_classes = [IsAuthenticated, ManageIdCardsPermission]

    def post(self, request, card_id: int):
        reason = (request.data.get("reason") or "").strip()
        if not reason:
            return Response({"detail": "reason is required."}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            card = StudentIdCard.objects.select_for_update().filter(pk=card_id).first()
            if not card:
                return Response({"detail": "ID card not found."}, status=status.HTTP_404_NOT_FOUND)
            if not card.is_active or card.status == StudentIdCard.STATUS_REVOKED:
                return Response({"detail": "This card is not active."}, status=400)
            card.status = StudentIdCard.STATUS_REVOKED
            card.is_active = False
            card.revoke_reason = reason
            card.save(update_fields=["status", "is_active", "revoke_reason", "updated_at"])
        log_audit_event(
            request.user,
            "id_card_revoke",
            card.admitted_student,
            f"Revoked ID card {card.card_number}: {reason[:200]}",
            request,
        )
        return Response(_card_payload(card))


class IdCardReissueView(APIView):
    permission_classes = [IsAuthenticated, ManageIdCardsPermission]

    def post(self, request, card_id: int):
        reason = (request.data.get("reason") or "").strip()
        if not reason:
            return Response({"detail": "reason is required."}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            old = StudentIdCard.objects.select_for_update().select_related("admitted_student").filter(pk=card_id).first()
            if not old:
                return Response({"detail": "ID card not found."}, status=status.HTTP_404_NOT_FOUND)
            if not old.is_active or old.status == StudentIdCard.STATUS_REVOKED:
                return Response({"detail": "This card is not active."}, status=400)
            admitted = old.admitted_student
            if not admitted.physical_documents_verified:
                return Response(
                    {"detail": "Physical documents must be verified before reissuing an ID card."},
                    status=400,
                )
            photo = admitted.application.passport_photo
            if not photo or not getattr(photo, "name", None):
                return Response({"detail": "A passport photo is required on the application."}, status=400)

            issue = timezone.now().date()
            expiry = _default_expiry(issue)
            new_card = StudentIdCard.objects.create(
                admitted_student=admitted,
                card_number=_allocate_card_number(),
                status=StudentIdCard.STATUS_GENERATED,
                is_active=True,
                issue_date=issue,
                expiry_date=expiry,
                issued_by=request.user,
                reissue_reason=reason,
            )
            old.status = StudentIdCard.STATUS_REISSUED
            old.is_active = False
            old.replaced_by = new_card
            old.save(update_fields=["status", "is_active", "replaced_by", "updated_at"])

        log_audit_event(
            request.user,
            "id_card_reissue",
            admitted,
            f"Reissued ID: {old.card_number} → {new_card.card_number}. {reason[:200]}",
            request,
        )
        return Response(_card_payload(new_card), status=status.HTTP_201_CREATED)
