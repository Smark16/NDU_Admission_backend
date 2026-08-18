"""Staff ID card issuance API (same ID desk as students)."""

from __future__ import annotations

import logging
import mimetypes
import secrets
from datetime import timedelta
from io import BytesIO

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.http import FileResponse, HttpResponse
from django.utils import timezone
from PIL import Image
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Campus, SystemSettings
from admissions.permissions import ManageIdCardsPermission
from audit.utils import log_audit_event

from .models import Department, StaffIdCard, StaffProfile, StaffType

logger = logging.getLogger(__name__)

ID_CARD_PASSPORT_MAX_BYTES = 6 * 1024 * 1024


def _default_expiry(issue):
    return issue + timedelta(days=365 * 4)


def _ordinal_day(day: int) -> str:
    if 11 <= (day % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def _issue_date_display(d) -> str:
    return f"{_ordinal_day(d.day)} {d.strftime('%B %Y')}"


def _allocate_card_number() -> str:
    year = timezone.now().year
    for _ in range(32):
        tail = secrets.token_hex(3).upper()
        candidate = f"NDU-STF-{year}-{tail}"
        if not StaffIdCard.objects.filter(card_number=candidate).exists():
            return candidate
    raise RuntimeError("Could not allocate a unique staff card number")


def _active_card_subquery():
    return StaffIdCard.objects.filter(
        staff_profile_id=OuterRef("pk"),
        is_active=True,
    ).exclude(status=StaffIdCard.STATUS_REVOKED)


def _eligible_base_qs():
    return (
        StaffProfile.objects.exclude(Q(staff_no__isnull=True) | Q(staff_no__exact=""))
        .annotate(_has_active_card=Exists(_active_card_subquery()))
        .filter(_has_active_card=False)
        .select_related("org_unit", "staff_type")
        .prefetch_related("campus")
    )


def _parse_int_param(request, key: str) -> int | None:
    raw = request.query_params.get(key)
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return int(str(raw).strip())
    except ValueError:
        return None


def _apply_scope(qs, request):
    department_id = _parse_int_param(request, "department_id")
    campus_id = _parse_int_param(request, "campus_id")
    staff_type_id = _parse_int_param(request, "staff_type_id")
    if department_id is not None:
        qs = qs.filter(org_unit_id=department_id)
    if campus_id is not None:
        qs = qs.filter(campus__id=campus_id)
    if staff_type_id is not None:
        qs = qs.filter(staff_type_id=staff_type_id)
    return qs.distinct()


def _search(qs, q: str):
    q = (q or "").strip()
    if not q:
        return qs
    return qs.filter(
        Q(first_name__icontains=q)
        | Q(last_name__icontains=q)
        | Q(staff_no__icontains=q)
        | Q(university_email__icontains=q)
        | Q(job_title__icontains=q)
    )


def _has_photo(profile: StaffProfile) -> bool:
    photo = getattr(profile, "passport_photo", None)
    return bool(photo and getattr(photo, "name", ""))


def _photo_url(request, profile: StaffProfile) -> str | None:
    if not _has_photo(profile):
        return None
    try:
        return request.build_absolute_uri(
            f"/api/hr/staff/id_cards/profile/{profile.pk}/passport_photo"
        )
    except Exception:
        return None


def _eligible_payload(request, profile: StaffProfile) -> dict:
    campus_names = list(profile.campus.order_by("name").values_list("name", flat=True)[:3])
    return {
        "id": profile.id,
        "staff_no": profile.staff_no or "",
        "name": profile.get_full_name,
        "job_title": profile.job_title or "",
        "department": profile.org_unit.name if profile.org_unit_id else "",
        "campus": ", ".join(campus_names),
        "staff_type": profile.staff_type.name if profile.staff_type_id else "",
        "has_passport_photo": _has_photo(profile),
    }


def _card_payload(card: StaffIdCard) -> dict:
    st = card.staff_profile
    return {
        "id": card.id,
        "staff_profile": st.id,
        "admitted_student": st.id,
        "admitted_student_name": st.get_full_name,
        "student_id": st.staff_no or "",
        "reg_no": st.job_title or "",
        "staff_no": st.staff_no or "",
        "job_title": st.job_title or "",
        "department": st.org_unit.name if st.org_unit_id else "",
        "card_number": card.card_number,
        "status": card.status,
        "issue_date": card.issue_date.isoformat() if card.issue_date else None,
        "expiry_date": card.expiry_date.isoformat() if card.expiry_date else None,
        "is_active": card.is_active,
        "print_count": card.print_count,
    }


def _resolve_template_dict() -> dict | None:
    settings_obj = SystemSettings.get_settings()
    active_key = (getattr(settings_obj, "active_staff_id_card_template", None) or "").strip()
    if not active_key:
        return None
    from admissions.models import IdCardPdfTemplate

    pdf_row = IdCardPdfTemplate.objects.filter(key=active_key, audience="staff").first()
    if not pdf_row:
        return None
    return {
        "key": pdf_row.key,
        "name": pdf_row.name,
        "front_title": pdf_row.front_title or "NDEJJE UNIVERSITY",
        "back_text": "",
        "institution": pdf_row.institution or "Ndejje University",
        "issuer_title": pdf_row.issuer_title or "Human Resource",
        "issuer_signatory": pdf_row.issuer_signatory or "",
        "return_to": pdf_row.return_to or "",
        "tel": pdf_row.tel or "",
        "email": pdf_row.email or "",
        "field_positions": pdf_row.field_positions or {},
    }


def _preview_payload(request, card: StaffIdCard) -> dict:
    from admissions.id_card_pdf_render import (
        build_staff_id_card_qr_payload,
        explain_pdf_render_blocker,
        pdf_pages_png_base64,
        render_staff_id_card_pdf,
    )

    st = card.staff_profile
    tmpl = _resolve_template_dict() or {}
    issue = card.issue_date or timezone.now().date()
    expiry = card.expiry_date or _default_expiry(issue)
    staff_no = st.staff_no or ""
    payload = {
        "card_number": card.card_number,
        "audience": "staff",
        "template": {
            "key": tmpl.get("key"),
            "name": tmpl.get("name"),
            "front_title": tmpl.get("front_title"),
            "back_text": tmpl.get("back_text"),
        },
        "front": {
            "name": st.get_full_name,
            "student_no": staff_no,
            "staff_no": staff_no,
            "reg_no": st.job_title or "",
            "course": st.org_unit.name if st.org_unit_id else "",
            "job_title": st.job_title or "",
            "department": st.org_unit.name if st.org_unit_id else "",
            "gender": "",
            "expiry_date": expiry.isoformat(),
            "barcode_value": staff_no or card.card_number,
            "qr_payload": build_staff_id_card_qr_payload(card),
            "passport_photo": _photo_url(request, st),
        },
        "back": {
            "institution": (tmpl.get("institution") or "Ndejje University").strip(),
            "issuer_title": tmpl.get("issuer_title") or "Human Resource",
            "issuer_signatory": (tmpl.get("issuer_signatory") or "").strip(),
            "issued_on": issue.isoformat(),
            "issued_on_display": _issue_date_display(issue),
            "return_to": (tmpl.get("return_to") or "").strip(),
            "tel": tmpl.get("tel") or "",
            "email": tmpl.get("email") or "",
        },
        "render_mode": "default",
    }
    try:
        pdf_bytes = render_staff_id_card_pdf(card)
        if pdf_bytes:
            pages = pdf_pages_png_base64(pdf_bytes)
            payload["render_mode"] = "pdf_template"
            payload["rendered_image"] = pages[0] if pages else ""
            payload["rendered_pages"] = pages
            payload["print_pdf_url"] = request.build_absolute_uri(
                f"/api/hr/staff/id_cards/{card.pk}/print.pdf"
            )
    except Exception:
        logger.exception("Staff ID card PDF render failed for card %s", card.pk)

    if payload["render_mode"] == "default":
        hint = explain_pdf_render_blocker("staff")
        if hint:
            payload["render_hint"] = hint
    return payload


class StaffIdCardFilterOptionsView(APIView):
    permission_classes = [IsAuthenticated, ManageIdCardsPermission]

    def get(self, request):
        dept_ids = StaffProfile.objects.exclude(org_unit_id=None).values_list("org_unit_id", flat=True).distinct()
        type_ids = StaffProfile.objects.exclude(staff_type_id=None).values_list("staff_type_id", flat=True).distinct()
        campus_ids = StaffProfile.objects.values_list("campus", flat=True).distinct()
        return Response(
            {
                "departments": list(
                    Department.objects.filter(pk__in=dept_ids).order_by("name").values("id", "name", "code")
                ),
                "campuses": list(
                    Campus.objects.filter(pk__in=campus_ids).order_by("name").values("id", "name", "code")
                ),
                "staff_types": list(
                    StaffType.objects.filter(pk__in=type_ids).order_by("name").values("id", "name")
                ),
            }
        )


class StaffIdCardEligibleListView(APIView):
    permission_classes = [IsAuthenticated, ManageIdCardsPermission]

    def get(self, request):
        requested_limit = _parse_int_param(request, "limit")
        if requested_limit is None:
            requested_limit = 1000
        requested_limit = max(1, min(requested_limit, 5000))
        qs = _eligible_base_qs()
        qs = _apply_scope(qs, request)
        qs = _search(qs, request.query_params.get("q", ""))
        qs = qs.order_by("last_name", "first_name")[:requested_limit]
        return Response([_eligible_payload(request, row) for row in qs])


class StaffIdCardListView(APIView):
    permission_classes = [IsAuthenticated, ManageIdCardsPermission]

    def get(self, request):
        qs = StaffIdCard.objects.select_related(
            "staff_profile",
            "staff_profile__org_unit",
            "staff_profile__staff_type",
        ).order_by("-created_at")
        department_id = _parse_int_param(request, "department_id")
        campus_id = _parse_int_param(request, "campus_id")
        staff_type_id = _parse_int_param(request, "staff_type_id")
        if department_id is not None:
            qs = qs.filter(staff_profile__org_unit_id=department_id)
        if campus_id is not None:
            qs = qs.filter(staff_profile__campus__id=campus_id)
        if staff_type_id is not None:
            qs = qs.filter(staff_profile__staff_type_id=staff_type_id)
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(card_number__icontains=q)
                | Q(staff_profile__staff_no__icontains=q)
                | Q(staff_profile__first_name__icontains=q)
                | Q(staff_profile__last_name__icontains=q)
            )
        st = (request.query_params.get("status") or "").strip()
        if st:
            qs = qs.filter(status=st)
        return Response([_card_payload(c) for c in qs.distinct()[:1000]])


class StaffIdCardPassportPhotoView(APIView):
    permission_classes = [IsAuthenticated, ManageIdCardsPermission]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request, staff_id: int):
        profile = StaffProfile.objects.filter(pk=staff_id).first()
        if not profile or not _has_photo(profile):
            return Response(status=status.HTTP_404_NOT_FOUND)
        photo = profile.passport_photo
        try:
            fh = photo.open("rb")
        except Exception:
            return Response(status=status.HTTP_404_NOT_FOUND)
        content_type = mimetypes.guess_type(photo.name)[0] or "image/jpeg"
        return FileResponse(fh, content_type=content_type)

    def post(self, request, staff_id: int):
        uploaded = request.FILES.get("passport_photo")
        if not uploaded:
            return Response({"detail": "passport_photo file is required."}, status=400)
        profile = StaffProfile.objects.filter(pk=staff_id).first()
        if not profile:
            return Response({"detail": "Staff profile not found."}, status=404)

        raw = uploaded.read()
        if len(raw) > ID_CARD_PASSPORT_MAX_BYTES:
            return Response({"detail": "Image is too large (max 6 MB)."}, status=400)
        if len(raw) < 256:
            return Response({"detail": "Image file is too small or empty."}, status=400)
        try:
            Image.open(BytesIO(raw)).verify()
        except Exception:
            return Response({"detail": "Invalid image file. Use JPEG or PNG."}, status=400)
        try:
            im = Image.open(BytesIO(raw))
            im = im.convert("RGB")
            if im.size[0] < 64 or im.size[1] < 64:
                return Response({"detail": "Image is too small. Minimum size 64×64 pixels."}, status=400)
            out = BytesIO()
            im.save(out, format="JPEG", quality=90)
            out.seek(0)
            jpeg_bytes = out.read()
        except Exception:
            return Response({"detail": "Could not process this image. Try another file."}, status=400)

        fname = f"passport_staff_{profile.pk}.jpg"
        profile.passport_photo.save(fname, ContentFile(jpeg_bytes), save=True)
        log_audit_event(
            request.user,
            "passport_photo_update",
            profile,
            f"Staff ID photo updated for staff_no={profile.staff_no}",
            request,
        )
        return Response({"detail": "Photo saved.", "has_passport_photo": True}, status=200)

    def delete(self, request, staff_id: int):
        profile = StaffProfile.objects.filter(pk=staff_id).first()
        if not profile:
            return Response({"detail": "Staff profile not found."}, status=404)
        if _has_photo(profile):
            profile.passport_photo.delete(save=True)
        log_audit_event(
            request.user,
            "passport_photo_delete",
            profile,
            f"Staff ID photo removed for staff_no={profile.staff_no}",
            request,
        )
        return Response({"detail": "Photo removed.", "has_passport_photo": False}, status=200)


class StaffIdCardGenerateView(APIView):
    permission_classes = [IsAuthenticated, ManageIdCardsPermission]

    def post(self, request):
        try:
            staff_id = int(request.data.get("staff_profile_id") or request.data.get("admitted_student_id"))
        except (TypeError, ValueError):
            return Response({"detail": "staff_profile_id is required."}, status=400)

        profile = StaffProfile.objects.filter(pk=staff_id).first()
        if not profile:
            return Response({"detail": "Staff profile not found."}, status=404)
        if not (profile.staff_no or "").strip():
            return Response({"detail": "Staff number is required before generating an ID card."}, status=400)
        if not _has_photo(profile):
            return Response({"detail": "A passport photo is required."}, status=400)
        if StaffIdCard.objects.filter(staff_profile=profile, is_active=True).exists():
            return Response({"detail": "An active ID card already exists for this staff member."}, status=400)

        issue = timezone.now().date()
        expiry = _default_expiry(issue)
        with transaction.atomic():
            card = StaffIdCard.objects.create(
                staff_profile=profile,
                card_number=_allocate_card_number(),
                status=StaffIdCard.STATUS_GENERATED,
                is_active=True,
                issue_date=issue,
                expiry_date=expiry,
                issued_by=request.user,
            )
        log_audit_event(
            request.user,
            "id_card_generate",
            profile,
            f"Issued staff ID card {card.card_number}",
            request,
        )
        return Response(_card_payload(card), status=status.HTTP_201_CREATED)


class StaffIdCardPreviewDataView(APIView):
    permission_classes = [IsAuthenticated, ManageIdCardsPermission]

    def get(self, request, card_id: int):
        card = (
            StaffIdCard.objects.select_related("staff_profile", "staff_profile__org_unit")
            .filter(pk=card_id)
            .first()
        )
        if not card:
            return Response({"detail": "ID card not found."}, status=404)
        return Response(_preview_payload(request, card))


class StaffIdCardPrintPdfView(APIView):
    permission_classes = [IsAuthenticated, ManageIdCardsPermission]

    def get(self, request, card_id: int):
        from admissions.id_card_pdf_render import render_staff_id_card_pdf

        card = StaffIdCard.objects.select_related("staff_profile").filter(pk=card_id).first()
        if not card:
            return Response({"detail": "ID card not found."}, status=404)
        try:
            pdf_bytes = render_staff_id_card_pdf(card)
        except Exception:
            logger.exception("Staff ID card PDF print failed for card %s", card_id)
            return Response({"detail": "Failed to render ID card PDF."}, status=500)
        if not pdf_bytes:
            return Response(
                {
                    "detail": (
                        "No active staff PDF template with mapped fields. Upload a staff template, "
                        "map fields, and set it as active."
                    )
                },
                status=400,
            )
        filename = f"staff-id-card-{card.card_number or card_id}.pdf"
        if card.print_count is not None:
            StaffIdCard.objects.filter(pk=card.pk).update(print_count=card.print_count + 1)
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{filename}"'
        return response


class StaffIdCardRevokeView(APIView):
    permission_classes = [IsAuthenticated, ManageIdCardsPermission]

    def post(self, request, card_id: int):
        reason = (request.data.get("reason") or "").strip()
        if not reason:
            return Response({"detail": "reason is required."}, status=400)
        with transaction.atomic():
            card = StaffIdCard.objects.select_for_update().filter(pk=card_id).first()
            if not card:
                return Response({"detail": "ID card not found."}, status=404)
            if not card.is_active or card.status == StaffIdCard.STATUS_REVOKED:
                return Response({"detail": "This card is not active."}, status=400)
            card.status = StaffIdCard.STATUS_REVOKED
            card.is_active = False
            card.revoke_reason = reason
            card.save(update_fields=["status", "is_active", "revoke_reason", "updated_at"])
        log_audit_event(
            request.user,
            "id_card_revoke",
            card.staff_profile,
            f"Revoked staff ID card {card.card_number}: {reason}",
            request,
        )
        return Response(_card_payload(card))


class StaffIdCardReissueView(APIView):
    permission_classes = [IsAuthenticated, ManageIdCardsPermission]

    def post(self, request, card_id: int):
        reason = (request.data.get("reason") or "").strip()
        if not reason:
            return Response({"detail": "reason is required."}, status=400)
        with transaction.atomic():
            old = StaffIdCard.objects.select_for_update().select_related("staff_profile").filter(pk=card_id).first()
            if not old:
                return Response({"detail": "ID card not found."}, status=404)
            if not old.is_active:
                return Response({"detail": "This card is not active."}, status=400)
            issue = timezone.now().date()
            new_card = StaffIdCard.objects.create(
                staff_profile=old.staff_profile,
                card_number=_allocate_card_number(),
                status=StaffIdCard.STATUS_GENERATED,
                is_active=True,
                issue_date=issue,
                expiry_date=_default_expiry(issue),
                issued_by=request.user,
                reissue_reason=reason,
            )
            old.status = StaffIdCard.STATUS_REISSUED
            old.is_active = False
            old.replaced_by = new_card
            old.reissue_reason = reason
            old.save(
                update_fields=["status", "is_active", "replaced_by", "reissue_reason", "updated_at"]
            )
        log_audit_event(
            request.user,
            "id_card_reissue",
            old.staff_profile,
            f"Reissued staff ID {old.card_number} → {new_card.card_number}: {reason}",
            request,
        )
        return Response(_card_payload(new_card), status=status.HTTP_201_CREATED)
