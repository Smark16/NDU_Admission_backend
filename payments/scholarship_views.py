"""Staff API for scholarship programmes, awards, waivers, and ledger credits."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
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
    copy_programme_waivers_to_award,
    programme_applied_amount,
    programme_committed_amount,
    reverse_credit,
    revoke_award,
    suggested_award_amount,
    validate_waiver_payload,
)


class ScholarshipAdminPermission(BasePermission):
    message = "You do not have permission to manage scholarships."

    def has_permission(self, request, view):
        u = request.user
        if not u.is_authenticated:
            return False
        if user_is_super_admin(u):
            return True
        if user_has_any_erp_perm(
            u,
            "manage_scholarships",
            "configure_fee_plans",
            "access_finance",
        ):
            return True
        if u.has_perm("payments.change_studenttuitionpayment"):
            return True
        return False


def _dec(value, field="amount") -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {field}.") from exc


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
    permission_classes = [IsAuthenticated, ScholarshipAdminPermission]

    def get(self, request):
        qs = ScholarshipProgramme.objects.all().order_by("name")
        active = request.query_params.get("active")
        if active in ("1", "true", "True"):
            qs = qs.filter(is_active=True)
        return Response([_programme_dict(p) for p in qs])

    def post(self, request):
        data = request.data or {}
        name = (data.get("name") or "").strip()
        code = (data.get("code") or "").strip().upper()
        if not name or not code:
            return Response(
                {"detail": "name and code are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if ScholarshipProgramme.objects.filter(code=code).exists():
            return Response(
                {"detail": f"Code '{code}' already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        fund = data.get("fund_amount")
        try:
            with transaction.atomic():
                programme = ScholarshipProgramme.objects.create(
                    name=name,
                    code=code,
                    sponsor=(data.get("sponsor") or "").strip(),
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
    permission_classes = [IsAuthenticated, ScholarshipAdminPermission]

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


class ScholarshipProgrammeAwardsView(APIView):
    """List / attach students on a programme."""

    permission_classes = [IsAuthenticated, ScholarshipAdminPermission]

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
        student_id = data.get("student_id")
        if not student_id:
            return Response(
                {"detail": "student_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        student = get_object_or_404(
            AdmittedStudent.objects.select_related("admitted_program", "application"),
            pk=student_id,
        )

        raw_amount = data.get("award_amount")
        suggested, rate_match = suggested_award_amount(programme, student)

        if raw_amount in (None, ""):
            if suggested is None:
                return Response(
                    {
                        "detail": (
                            "award_amount is required. No rate is configured for this "
                            "student's academic programme on this scholarship."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            award_amount = suggested
        else:
            try:
                award_amount = _dec(raw_amount, "award_amount")
            except ValueError as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if award_amount <= 0:
            return Response(
                {"detail": "award_amount must be greater than zero."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if (
            programme.awarding_mode == ScholarshipProgramme.AWARDING_BY_PROGRAMME
            and rate_match is None
            and not bool(data.get("force_custom_amount"))
        ):
            return Response(
                {
                    "detail": (
                        "This scholarship uses programme rates, but no rate exists for "
                        f"{getattr(student.admitted_program, 'name', 'this programme')}. "
                        "Add a rate, or send force_custom_amount=true with a manual amount."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if programme.fund_amount is not None:
            committed = programme_committed_amount(programme)
            if committed + award_amount > programme.fund_amount:
                return Response(
                    {
                        "detail": (
                            f"Award would exceed programme fund "
                            f"({programme.fund_amount} {programme.currency}). "
                            f"Already committed: {committed}."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if ScholarshipAward.objects.filter(
            programme=programme,
            student=student,
            status=ScholarshipAward.STATUS_ACTIVE,
        ).exists():
            return Response(
                {"detail": "Student already has an active award on this scholarship."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        rate_note = ""
        if rate_match is not None and raw_amount in (None, ""):
            rate_note = (
                f"Auto from rate: {rate_match.academic_program} = {rate_match.amount}."
            )

        try:
            with transaction.atomic():
                notes = (data.get("notes") or "").strip()
                if rate_note:
                    notes = f"{notes} {rate_note}".strip()
                award = ScholarshipAward.objects.create(
                    programme=programme,
                    student=student,
                    award_amount=award_amount,
                    currency=(data.get("currency") or programme.currency or "UGX")
                    .strip()
                    .upper()[:3],
                    notes=notes,
                    awarded_by=request.user,
                )
                if "waivers" in data:
                    _sync_award_waivers(award, data.get("waivers") or [])
                else:
                    copy_programme_waivers_to_award(award)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except IntegrityError:
            return Response(
                {"detail": "Student already has an active award on this scholarship."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        apply_now = bool(data.get("apply_now"))
        if apply_now:
            try:
                apply_award_waivers(award, request.user)
            except ValueError as exc:
                return Response(
                    {
                        **_award_dict(award, include_nested=True),
                        "apply_warning": str(exc),
                    },
                    status=status.HTTP_201_CREATED,
                )

        award.refresh_from_db()
        return Response(
            _award_dict(award, include_nested=True),
            status=status.HTTP_201_CREATED,
        )


class ScholarshipAwardDetailView(APIView):
    permission_classes = [IsAuthenticated, ScholarshipAdminPermission]

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
    permission_classes = [IsAuthenticated, ScholarshipAdminPermission]

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
