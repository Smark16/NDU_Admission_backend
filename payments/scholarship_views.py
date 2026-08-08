"""Staff API for scholarship programmes, awards, waivers, and ledger credits."""
from __future__ import annotations

import csv
import io
import re
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.erp_drf_permissions import user_has_any_erp_perm
from accounts.super_admin import user_is_super_admin
from admissions.models import AdmittedStudent
from payments.models import (
    FeeHead,
    ScholarshipAward,
    ScholarshipAwardWaiver,
    ScholarshipCredit,
    ScholarshipProgramme,
    ScholarshipProgrammeRate,
    ScholarshipProgrammeWaiver,
)
from payments.scholarship_services import (
    apply_award_waivers,
    delete_programme,
    programme_applied_amount,
    programme_committed_amount,
    reverse_credit,
    revoke_award,
    suggested_award_amount,
    validate_waiver_payload,
)


def _user_can_view_scholarships(user) -> bool:
    return user_has_any_erp_perm(
        user,
        "manage_scholarships",
        "view_scholarships",
        "manage_scholarship_programmes",
        "manage_scholarship_students",
    )


def _user_can_manage_scholarship_programmes(user) -> bool:
    return user_has_any_erp_perm(
        user,
        "manage_scholarships",
        "manage_scholarship_programmes",
    )


def _user_can_manage_scholarship_students(user) -> bool:
    return user_has_any_erp_perm(
        user,
        "manage_scholarships",
        "manage_scholarship_students",
    )


class ScholarshipViewPermission(BasePermission):
    message = "You do not have permission to view scholarships."

    def has_permission(self, request, view):
        u = request.user
        if not u.is_authenticated:
            return False
        if user_is_super_admin(u):
            return True
        return _user_can_view_scholarships(u)


class ScholarshipProgrammePermission(BasePermission):
    message = "You do not have permission to manage scholarship programmes."

    def has_permission(self, request, view):
        u = request.user
        if not u.is_authenticated:
            return False
        if user_is_super_admin(u):
            return True
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return _user_can_view_scholarships(u)
        return _user_can_manage_scholarship_programmes(u)


class ScholarshipStudentPermission(BasePermission):
    message = "You do not have permission to attach students to scholarships."

    def has_permission(self, request, view):
        u = request.user
        if not u.is_authenticated:
            return False
        if user_is_super_admin(u):
            return True
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return _user_can_view_scholarships(u)
        return _user_can_manage_scholarship_students(u)


# Backward-compatible alias used by award apply / credit reverse (full access).
class ScholarshipAdminPermission(BasePermission):
    message = "You do not have permission to manage scholarships."

    def has_permission(self, request, view):
        u = request.user
        if not u.is_authenticated:
            return False
        if user_is_super_admin(u):
            return True
        return user_has_any_erp_perm(u, "manage_scholarships")


def _dec(value, field="amount") -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {field}.") from exc


def _find_admitted_student(*, student_id=None, reg_no=None, schoolpay_code=None):
    """Resolve an admitted student from common spreadsheet identifiers."""
    sid = (str(student_id).strip() if student_id not in (None, "") else "")
    reg = (str(reg_no).strip() if reg_no not in (None, "") else "")
    code = (str(schoolpay_code).strip() if schoolpay_code not in (None, "") else "")
    if not sid and not reg and not code:
        raise ValueError("Provide student_id or reg_no (or schoolpay_code).")

    qs = AdmittedStudent.objects.select_related("admitted_program", "application")
    if sid:
        # Prefer string student_id; also accept numeric admitted-student PK.
        by_sid = qs.filter(student_id__iexact=sid).first()
        if by_sid:
            return by_sid
        if sid.isdigit():
            by_pk = qs.filter(pk=int(sid)).first()
            if by_pk:
                return by_pk
    if reg:
        by_reg = qs.filter(reg_no__iexact=reg).first()
        if by_reg:
            return by_reg
    if code:
        by_code = qs.filter(schoolpay_code__iexact=code).first()
        if by_code:
            return by_code
    # Last resort: any of the identifiers in any of those fields.
    parts = [p for p in (sid, reg, code) if p]
    if parts:
        q = Q()
        for p in parts:
            q |= Q(student_id__iexact=p) | Q(reg_no__iexact=p) | Q(schoolpay_code__iexact=p)
        hit = qs.filter(q).first()
        if hit:
            return hit
    raise ValueError(
        f"Student not found"
        + (f" (student_id={sid})" if sid else "")
        + (f" (reg_no={reg})" if reg else "")
        + (f" (schoolpay_code={code})" if code else "")
        + "."
    )


def _create_tracking_award(
    programme: ScholarshipProgramme,
    student: AdmittedStudent,
    *,
    award_amount: Decimal,
    notes: str,
    user,
) -> ScholarshipAward:
    """Attach student for sponsorship tracking / temp-pass eligibility (no fee waivers)."""
    if award_amount <= 0:
        raise ValueError("amount_covered must be greater than zero.")
    if ScholarshipAward.objects.filter(
        programme=programme,
        student=student,
        status=ScholarshipAward.STATUS_ACTIVE,
    ).exists():
        raise ValueError("Student already has an active award on this scholarship.")
    try:
        return ScholarshipAward.objects.create(
            programme=programme,
            student=student,
            award_amount=award_amount,
            currency=(programme.currency or "UGX").strip().upper()[:3],
            notes=(notes or "").strip(),
            awarded_by=user if getattr(user, "is_authenticated", False) else None,
        )
    except IntegrityError as exc:
        raise ValueError("Student already has an active award on this scholarship.") from exc


def _student_name(student: AdmittedStudent) -> str:
    name = (getattr(student, "full_name", None) or "").strip()
    if name:
        return name
    try:
        if student.application_id:
            return (student.application.full_name or "").strip()
    except Exception:
        pass
    user = getattr(student, "student_user", None)
    if user:
        return (user.get_full_name() or user.username or "").strip()
    return student.student_id or str(student.pk)


def _waiver_dict(row) -> dict:
    return {
        "id": row.id,
        "fee_head_id": row.fee_head_id,
        "fee_head_code": row.fee_head.code if row.fee_head_id else None,
        "fee_head_name": row.fee_head.name if row.fee_head_id else None,
        "waiver_mode": row.waiver_mode,
        "percent": str(row.percent) if row.percent is not None else None,
    }


def _credit_dict(c: ScholarshipCredit) -> dict:
    return {
        "id": c.id,
        "fee_head_id": c.fee_head_id,
        "fee_head_code": c.fee_head.code if c.fee_head_id else None,
        "fee_head_name": c.fee_head.name if c.fee_head_id else None,
        "amount": str(c.amount),
        "currency": c.currency,
        "payment_id": c.payment_id,
        "applied_at": c.applied_at.isoformat() if c.applied_at else None,
        "is_reversed": c.is_reversed,
        "reversed_at": c.reversed_at.isoformat() if c.reversed_at else None,
        "notes": c.notes,
    }


def _award_dict(a: ScholarshipAward, *, include_nested: bool = False) -> dict:
    data = {
        "id": a.id,
        "programme_id": a.programme_id,
        "programme_code": a.programme.code if a.programme_id else None,
        "programme_name": a.programme.name if a.programme_id else None,
        "student_id": a.student_id,
        "student_number": a.student.student_id if a.student_id else None,
        "reg_no": a.student.reg_no if a.student_id else None,
        "student_name": _student_name(a.student) if a.student_id else None,
        "award_amount": str(a.award_amount),
        "applied_amount": str(a.applied_amount),
        "remaining_amount": str(a.remaining_amount),
        "currency": a.currency,
        "status": a.status,
        "notes": a.notes,
        "awarded_at": a.awarded_at.isoformat() if a.awarded_at else None,
        "revoked_at": a.revoked_at.isoformat() if a.revoked_at else None,
    }
    if include_nested:
        data["waivers"] = [
            _waiver_dict(w) for w in a.waivers.select_related("fee_head")
        ]
        data["credits"] = [
            _credit_dict(c)
            for c in a.credits.select_related("fee_head").order_by("-applied_at")
        ]
    return data


def _rate_dict(row: ScholarshipProgrammeRate) -> dict:
    prog = row.academic_program
    return {
        "id": row.id,
        "academic_program_id": row.academic_program_id,
        "academic_program_name": getattr(prog, "name", None) if prog else None,
        "academic_program_code": getattr(prog, "code", None) if prog else None,
        "amount": str(row.amount),
        "notes": row.notes or "",
    }


def _programme_dict(p: ScholarshipProgramme, *, include_waivers: bool = True) -> dict:
    data = {
        "id": p.id,
        "name": p.name,
        "code": p.code,
        "sponsor": p.sponsor,
        "sponsor_type": getattr(p, "sponsor_type", None) or ScholarshipProgramme.SPONSOR_OTHER,
        "sponsor_type_display": (
            p.get_sponsor_type_display()
            if hasattr(p, "get_sponsor_type_display")
            else "Other / custom"
        ),
        "description": p.description,
        "fund_amount": str(p.fund_amount) if p.fund_amount is not None else None,
        "currency": p.currency,
        "academic_year": p.academic_year,
        "awarding_mode": p.awarding_mode,
        "is_active": p.is_active,
        "committed_amount": str(programme_committed_amount(p)),
        "applied_amount": str(programme_applied_amount(p)),
        "award_count": p.awards.filter(status=ScholarshipAward.STATUS_ACTIVE).count(),
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }
    if include_waivers:
        data["default_waivers"] = [
            _waiver_dict(w) for w in p.default_waivers.select_related("fee_head")
        ]
        data["programme_rates"] = [
            _rate_dict(r)
            for r in p.programme_rates.select_related("academic_program").order_by(
                "academic_program__name"
            )
        ]
    return data


def _sync_programme_rates(programme: ScholarshipProgramme, rows: list) -> None:
    if rows is None:
        return
    keep_ids: list[int] = []
    for raw in rows:
        prog_id = raw.get("academic_program_id")
        if not prog_id:
            raise ValueError("Each rate needs academic_program_id.")
        from Programs.models import Program

        academic = Program.objects.filter(pk=prog_id).first()
        if not academic:
            raise ValueError(f"Academic programme {prog_id} not found.")
        amount = _dec(raw.get("amount"), "amount")
        if amount <= 0:
            raise ValueError("Rate amount must be greater than zero.")
        obj, _ = ScholarshipProgrammeRate.objects.update_or_create(
            scholarship=programme,
            academic_program=academic,
            defaults={
                "amount": amount,
                "notes": (raw.get("notes") or "").strip(),
            },
        )
        keep_ids.append(obj.id)
    ScholarshipProgrammeRate.objects.filter(scholarship=programme).exclude(
        id__in=keep_ids
    ).delete()


def _sync_programme_waivers(programme: ScholarshipProgramme, rows: list) -> None:
    if rows is None:
        return
    keep_ids: list[int] = []
    for raw in rows:
        fh_id = raw.get("fee_head_id")
        if not fh_id:
            raise ValueError("Each waiver needs fee_head_id.")
        fee_head = FeeHead.objects.filter(pk=fh_id, is_active=True).first()
        if not fee_head:
            raise ValueError(f"Fee head {fh_id} not found or inactive.")
        mode, pct = validate_waiver_payload(raw.get("waiver_mode"), raw.get("percent"))
        obj, _ = ScholarshipProgrammeWaiver.objects.update_or_create(
            programme=programme,
            fee_head=fee_head,
            defaults={"waiver_mode": mode, "percent": pct},
        )
        keep_ids.append(obj.id)
    ScholarshipProgrammeWaiver.objects.filter(programme=programme).exclude(
        id__in=keep_ids
    ).delete()


def _sync_award_waivers(award: ScholarshipAward, rows: list) -> None:
    if rows is None:
        return
    keep_ids: list[int] = []
    for raw in rows:
        fh_id = raw.get("fee_head_id")
        if not fh_id:
            raise ValueError("Each waiver needs fee_head_id.")
        fee_head = FeeHead.objects.filter(pk=fh_id, is_active=True).first()
        if not fee_head:
            raise ValueError(f"Fee head {fh_id} not found or inactive.")
        mode, pct = validate_waiver_payload(raw.get("waiver_mode"), raw.get("percent"))
        obj, _ = ScholarshipAwardWaiver.objects.update_or_create(
            award=award,
            fee_head=fee_head,
            defaults={"waiver_mode": mode, "percent": pct},
        )
        keep_ids.append(obj.id)
    ScholarshipAwardWaiver.objects.filter(award=award).exclude(id__in=keep_ids).delete()


class ScholarshipProgrammeListCreateView(APIView):
    permission_classes = [IsAuthenticated, ScholarshipProgrammePermission]

    def get(self, request):
        qs = ScholarshipProgramme.objects.all().order_by("name")
        active = request.query_params.get("active")
        if active in ("1", "true", "True"):
            qs = qs.filter(is_active=True)
        return Response([_programme_dict(p) for p in qs])

    def post(self, request):
        data = request.data or {}
        name = (data.get("name") or "").strip()
        if not name:
            return Response(
                {"detail": "Scholarship name is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        code = (data.get("code") or "").strip().upper()
        if not code:
            # Simple create: code from name (FAWE → FAWE).
            code = re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")[:40] or "SCHOLARSHIP"
        base_code = code
        n = 2
        while ScholarshipProgramme.objects.filter(code=code).exists():
            suffix = f"_{n}"
            code = f"{base_code[: max(1, 40 - len(suffix))]}{suffix}"
            n += 1
        fund = data.get("fund_amount")
        try:
            with transaction.atomic():
                sponsor_type = (data.get("sponsor_type") or "").strip()
                if not sponsor_type:
                    low = name.lower()
                    if "hesfb" in low:
                        sponsor_type = ScholarshipProgramme.SPONSOR_HESFB
                    elif "fawe" in low:
                        sponsor_type = ScholarshipProgramme.SPONSOR_FAWE
                    elif "state house" in low or "statehouse" in low:
                        sponsor_type = ScholarshipProgramme.SPONSOR_STATE_HOUSE
                    elif "church" in low or "diocese" in low or "parish" in low:
                        sponsor_type = ScholarshipProgramme.SPONSOR_CHURCH
                    else:
                        sponsor_type = ScholarshipProgramme.SPONSOR_OTHER
                valid_sponsor_types = {c[0] for c in ScholarshipProgramme.SPONSOR_TYPE_CHOICES}
                if sponsor_type not in valid_sponsor_types:
                    raise ValueError("Invalid sponsor_type.")
                programme = ScholarshipProgramme.objects.create(
                    name=name,
                    code=code,
                    sponsor=(data.get("sponsor") or name).strip(),
                    sponsor_type=sponsor_type,
                    description=(data.get("description") or "").strip(),
                    fund_amount=_dec(fund, "fund_amount") if fund not in (None, "") else None,
                    currency=(data.get("currency") or "UGX").strip().upper()[:3],
                    academic_year=(data.get("academic_year") or "").strip(),
                    awarding_mode=(
                        data.get("awarding_mode")
                        or ScholarshipProgramme.AWARDING_PER_STUDENT
                    ),
                    is_active=bool(data.get("is_active", True)),
                    created_by=request.user,
                )
                if programme.awarding_mode not in (
                    ScholarshipProgramme.AWARDING_BY_PROGRAMME,
                    ScholarshipProgramme.AWARDING_PER_STUDENT,
                ):
                    raise ValueError("awarding_mode must be by_programme or per_student.")
                if "default_waivers" in data:
                    _sync_programme_waivers(programme, data.get("default_waivers") or [])
                if "programme_rates" in data:
                    _sync_programme_rates(programme, data.get("programme_rates") or [])
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_programme_dict(programme), status=status.HTTP_201_CREATED)


class ScholarshipProgrammeDetailView(APIView):
    permission_classes = [IsAuthenticated, ScholarshipProgrammePermission]

    def get(self, request, pk):
        programme = get_object_or_404(ScholarshipProgramme, pk=pk)
        return Response(_programme_dict(programme))

    def patch(self, request, pk):
        programme = get_object_or_404(ScholarshipProgramme, pk=pk)
        data = request.data or {}
        try:
            with transaction.atomic():
                if "name" in data:
                    programme.name = (data.get("name") or "").strip() or programme.name
                if "code" in data:
                    new_code = (data.get("code") or "").strip().upper()
                    if (
                        new_code
                        and new_code != programme.code
                        and ScholarshipProgramme.objects.filter(code=new_code).exists()
                    ):
                        return Response(
                            {"detail": f"Code '{new_code}' already exists."},
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                    if new_code:
                        programme.code = new_code
                if "sponsor" in data:
                    programme.sponsor = (data.get("sponsor") or "").strip()
                if "sponsor_type" in data:
                    sponsor_type = (data.get("sponsor_type") or "").strip()
                    valid_sponsor_types = {c[0] for c in ScholarshipProgramme.SPONSOR_TYPE_CHOICES}
                    if sponsor_type not in valid_sponsor_types:
                        raise ValueError("Invalid sponsor_type.")
                    programme.sponsor_type = sponsor_type
                if "description" in data:
                    programme.description = (data.get("description") or "").strip()
                if "academic_year" in data:
                    programme.academic_year = (data.get("academic_year") or "").strip()
                if "awarding_mode" in data:
                    mode = (data.get("awarding_mode") or "").strip()
                    if mode not in (
                        ScholarshipProgramme.AWARDING_BY_PROGRAMME,
                        ScholarshipProgramme.AWARDING_PER_STUDENT,
                    ):
                        raise ValueError(
                            "awarding_mode must be by_programme or per_student."
                        )
                    programme.awarding_mode = mode
                if "currency" in data:
                    programme.currency = (data.get("currency") or "UGX").strip().upper()[:3]
                if "is_active" in data:
                    programme.is_active = bool(data.get("is_active"))
                if "fund_amount" in data:
                    fund = data.get("fund_amount")
                    programme.fund_amount = (
                        _dec(fund, "fund_amount") if fund not in (None, "") else None
                    )
                programme.save()
                if "default_waivers" in data:
                    _sync_programme_waivers(programme, data.get("default_waivers") or [])
                if "programme_rates" in data:
                    _sync_programme_rates(programme, data.get("programme_rates") or [])
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_programme_dict(programme))

    def delete(self, request, pk):
        programme = get_object_or_404(ScholarshipProgramme, pk=pk)
        name = programme.name
        try:
            delete_programme(programme, request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {"detail": f"Scholarship '{name}' deleted. Attached awards were revoked and credits reversed."},
            status=status.HTTP_200_OK,
        )


class ScholarshipProgrammeAwardsView(APIView):
    """List / attach students on a programme."""

    permission_classes = [IsAuthenticated, ScholarshipStudentPermission]

    def get(self, request, pk):
        programme = get_object_or_404(ScholarshipProgramme, pk=pk)
        qs = programme.awards.select_related(
            "student", "student__application", "programme"
        ).order_by("-awarded_at")
        status_f = (request.query_params.get("status") or "").strip()
        if status_f:
            qs = qs.filter(status=status_f)
        return Response([_award_dict(a) for a in qs])

    def post(self, request, pk):
        programme = get_object_or_404(ScholarshipProgramme, pk=pk)
        if not programme.is_active:
            return Response(
                {"detail": "Cannot attach students to an inactive scholarship."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        data = request.data or {}
        student_pk = data.get("student_id")
        if not student_pk:
            return Response(
                {"detail": "student_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        student = get_object_or_404(
            AdmittedStudent.objects.select_related("admitted_program", "application"),
            pk=student_pk,
        )

        raw_amount = data.get("award_amount")
        suggested, _rate_match = suggested_award_amount(programme, student)
        try:
            if raw_amount in (None, ""):
                if suggested is not None:
                    award_amount = suggested
                elif programme.fund_amount is not None:
                    award_amount = programme.fund_amount
                else:
                    return Response(
                        {"detail": "award_amount is required."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            else:
                award_amount = _dec(raw_amount, "award_amount")
            award = _create_tracking_award(
                programme,
                student,
                award_amount=award_amount,
                notes=(data.get("notes") or "").strip(),
                user=request.user,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        award.refresh_from_db()
        return Response(
            _award_dict(award, include_nested=True),
            status=status.HTTP_201_CREATED,
        )


class ScholarshipProgrammeBulkAwardsView(APIView):
    """CSV / JSON bulk attach of sponsored students (tracking + temp-pass eligibility)."""

    permission_classes = [IsAuthenticated, ScholarshipStudentPermission]

    TEMPLATE_HEADERS = ["student_id", "reg_no", "amount_covered", "notes"]

    def get(self, request, pk):
        get_object_or_404(ScholarshipProgramme, pk=pk)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(self.TEMPLATE_HEADERS)
        writer.writerow(["1012118627", "", "2450000", "Example row — delete before upload"])
        writer.writerow(["", "NDU/2024/001", "", "Uses scholarship amount covered if amount blank"])
        content = buf.getvalue()
        resp = HttpResponse(content, content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = (
            f'attachment; filename="scholarship_{pk}_students_template.csv"'
        )
        return resp

    def post(self, request, pk):
        programme = get_object_or_404(ScholarshipProgramme, pk=pk)
        if not programme.is_active:
            return Response(
                {"detail": "Cannot attach students to an inactive scholarship."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        rows, parse_error = self._parse_rows(request)
        if parse_error:
            return Response({"detail": parse_error}, status=status.HTTP_400_BAD_REQUEST)
        if not rows:
            return Response(
                {"detail": "No student rows found in the upload."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(rows) > 500:
            return Response(
                {"detail": "Maximum 500 rows per upload."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        default_amount = programme.fund_amount
        attached = []
        errors = []

        for idx, row in enumerate(rows, start=1):
            line = row.get("_line") or idx
            try:
                student = _find_admitted_student(
                    student_id=row.get("student_id"),
                    reg_no=row.get("reg_no"),
                    schoolpay_code=row.get("schoolpay_code"),
                )
                raw_amount = row.get("amount_covered")
                if raw_amount in (None, ""):
                    raw_amount = row.get("award_amount")
                if raw_amount in (None, ""):
                    if default_amount is None:
                        raise ValueError(
                            "amount_covered is required (or set Amount covered on the scholarship)."
                        )
                    award_amount = default_amount
                else:
                    award_amount = _dec(raw_amount, "amount_covered")
                award = _create_tracking_award(
                    programme,
                    student,
                    award_amount=award_amount,
                    notes=(row.get("notes") or "").strip(),
                    user=request.user,
                )
                attached.append(
                    {
                        "line": line,
                        "student_id": student.student_id,
                        "reg_no": student.reg_no,
                        "award_id": award.id,
                        "amount_covered": str(award.award_amount),
                    }
                )
            except ValueError as exc:
                errors.append({"line": line, "detail": str(exc), "row": {
                    "student_id": row.get("student_id") or "",
                    "reg_no": row.get("reg_no") or "",
                }})

        return Response(
            {
                "attached_count": len(attached),
                "error_count": len(errors),
                "attached": attached,
                "errors": errors,
                "detail": (
                    f"Attached {len(attached)} student(s)"
                    + (f"; {len(errors)} row(s) failed." if errors else ".")
                ),
            },
            status=status.HTTP_200_OK,
        )

    def _parse_rows(self, request):
        upload = request.FILES.get("file")
        if upload is not None:
            name = (upload.name or "").lower()
            if not name.endswith(".csv"):
                return [], "Only .csv files are accepted for bulk upload."
            try:
                text = upload.read().decode("utf-8-sig")
            except UnicodeDecodeError:
                return [], "Could not read CSV as UTF-8. Save as CSV UTF-8 and try again."
            reader = csv.DictReader(io.StringIO(text))
            if not reader.fieldnames:
                return [], "CSV has no header row."
            headers = {((h or "").strip().lower()): (h or "").strip() for h in reader.fieldnames}
            alias = {
                "student_id": ("student_id", "student number", "student_number", "schoolpay", "id"),
                "reg_no": ("reg_no", "reg no", "registration_number", "registration no", "regno"),
                "schoolpay_code": ("schoolpay_code", "schoolpay code"),
                "amount_covered": (
                    "amount_covered",
                    "award_amount",
                    "amount",
                    "covered",
                ),
                "notes": ("notes", "note", "comment"),
            }
            colmap = {}
            for key, names in alias.items():
                for n in names:
                    if n in headers:
                        colmap[key] = headers[n]
                        break
            if "student_id" not in colmap and "reg_no" not in colmap and "schoolpay_code" not in colmap:
                return [], (
                    "CSV must include a student_id or reg_no column "
                    "(optional: amount_covered, notes)."
                )
            rows = []
            for i, raw in enumerate(reader, start=2):
                if not any((str(v or "").strip() for v in raw.values())):
                    continue
                rows.append(
                    {
                        "student_id": (raw.get(colmap.get("student_id", ""), "") or "").strip(),
                        "reg_no": (raw.get(colmap.get("reg_no", ""), "") or "").strip(),
                        "schoolpay_code": (
                            raw.get(colmap.get("schoolpay_code", ""), "") or ""
                        ).strip(),
                        "amount_covered": (
                            raw.get(colmap.get("amount_covered", ""), "") or ""
                        ).strip(),
                        "notes": (raw.get(colmap.get("notes", ""), "") or "").strip(),
                        "_line": i,
                    }
                )
            return rows, None

        data = request.data or {}
        payload = data.get("rows") or data.get("students") or []
        if not isinstance(payload, list):
            return [], "Send a CSV file, or JSON { rows: [...] }."
        rows = []
        for i, item in enumerate(payload, start=1):
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "student_id": str(item.get("student_id") or "").strip(),
                    "reg_no": str(item.get("reg_no") or "").strip(),
                    "schoolpay_code": str(item.get("schoolpay_code") or "").strip(),
                    "amount_covered": str(
                        item.get("amount_covered")
                        if item.get("amount_covered") not in (None,)
                        else item.get("award_amount") or ""
                    ).strip(),
                    "notes": str(item.get("notes") or "").strip(),
                    "_line": i,
                }
            )
        return rows, None


class ScholarshipAwardDetailView(APIView):
    permission_classes = [IsAuthenticated, ScholarshipStudentPermission]

    def get(self, request, pk):
        award = get_object_or_404(
            ScholarshipAward.objects.select_related(
                "student", "student__application", "programme"
            ),
            pk=pk,
        )
        return Response(_award_dict(award, include_nested=True))

    def patch(self, request, pk):
        award = get_object_or_404(ScholarshipAward, pk=pk)
        if award.status == ScholarshipAward.STATUS_REVOKED:
            return Response(
                {"detail": "Revoked awards cannot be edited."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        data = request.data or {}
        try:
            with transaction.atomic():
                if "award_amount" in data:
                    amount = _dec(data.get("award_amount"), "award_amount")
                    if amount <= 0:
                        return Response(
                            {"detail": "award_amount must be greater than zero."},
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                    if amount < (award.applied_amount or Decimal("0")):
                        return Response(
                            {
                                "detail": (
                                    f"award_amount cannot be less than already applied "
                                    f"({award.applied_amount})."
                                )
                            },
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                    award.award_amount = amount
                if "notes" in data:
                    award.notes = (data.get("notes") or "").strip()
                award.save()
                if "waivers" in data:
                    _sync_award_waivers(award, data.get("waivers") or [])
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_award_dict(award, include_nested=True))


class ScholarshipAwardApplyView(APIView):
    permission_classes = [IsAuthenticated, ScholarshipAdminPermission]

    def post(self, request, pk):
        award = get_object_or_404(ScholarshipAward, pk=pk)
        try:
            credits = apply_award_waivers(award, request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        award.refresh_from_db()
        return Response(
            {
                "award": _award_dict(award, include_nested=True),
                "credits_created": [_credit_dict(c) for c in credits],
                "detail": (
                    f"Posted {len(credits)} scholarship credit(s)."
                    if credits
                    else "No new credits posted (nothing due or already covered)."
                ),
            }
        )


class ScholarshipAwardRevokeView(APIView):
    permission_classes = [IsAuthenticated, ScholarshipStudentPermission]

    def post(self, request, pk):
        award = get_object_or_404(ScholarshipAward, pk=pk)
        reverse_credits = bool((request.data or {}).get("reverse_credits", True))
        revoke_award(award, request.user, reverse_credits=reverse_credits)
        award.refresh_from_db()
        return Response(_award_dict(award, include_nested=True))


class ScholarshipCreditReverseView(APIView):
    permission_classes = [IsAuthenticated, ScholarshipAdminPermission]

    def post(self, request, pk):
        credit = get_object_or_404(ScholarshipCredit, pk=pk)
        try:
            reverse_credit(credit, request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        credit.refresh_from_db()
        return Response(_credit_dict(credit))
