"""Admin + student APIs for Temporary Access Passes."""
from __future__ import annotations

from datetime import datetime

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.models import AdmittedStudent, TemporaryAccessPass
from admissions.temporary_access import (
    active_passes_qs,
    expire_stale_passes,
    pass_to_dict,
    public_verify_pass,
    sponsorship_summary,
    student_active_scholarship_awards,
    student_is_sponsored,
    student_temporary_access,
)
from admissions.faculty_scope import assert_admitted_student_access
from accounts.erp_drf_permissions import AccountsClearedReportPermission
from accounts.finance_access import (
    user_can_approve_temporary_access_pass,
    user_can_clear_temporary_access_pass,
    user_can_issue_temporary_access_pass,
    user_can_view_student_finance,
)


def _can_issue_passes(user) -> bool:
    return user_can_issue_temporary_access_pass(user)


def _can_approve_passes(user) -> bool:
    return user_can_approve_temporary_access_pass(user)


def _can_clear_passes(user) -> bool:
    return user_can_clear_temporary_access_pass(user)


def _can_view_passes(user) -> bool:
    return (
        user_can_issue_temporary_access_pass(user)
        or user_can_approve_temporary_access_pass(user)
        or user_can_clear_temporary_access_pass(user)
        or user_can_view_student_finance(user)
    )


def _activate_pass(pass_obj, user):
    """Mark pass active and supersede any other live active passes for the student."""
    now = timezone.now()
    active_passes_qs(pass_obj.student).exclude(pk=pass_obj.pk).update(
        status=TemporaryAccessPass.STATUS_REVOKED,
        revoked_at=now,
        revoked_by=user,
        revoke_reason="Superseded by Bursar-approved temporary access pass",
    )
    pass_obj.status = TemporaryAccessPass.STATUS_ACTIVE
    pass_obj.approved_by = user
    pass_obj.approved_at = now
    pass_obj.save(
        update_fields=["status", "approved_by", "approved_at", "updated_at"]
    )
    return pass_obj


def _parse_date(raw):
    if raw in (None, ""):
        return None
    if hasattr(raw, "isoformat") and not isinstance(raw, str):
        return raw
    text = str(raw).strip()[:10]
    return datetime.strptime(text, "%Y-%m-%d").date()


class StudentTemporaryAccessView(APIView):
    """GET /api/admissions/student/temporary_access — current student's pass status."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        student = (
            AdmittedStudent.objects.filter(student_user=request.user)
            .order_by("-id")
            .first()
        )
        if not student:
            return Response({"detail": "No admitted student record."}, status=404)
        return Response(student_temporary_access(student, request=request))


class StudentTemporaryAccessAdminView(APIView):
    """
    GET  /api/admissions/admitted_students/<pk>/temporary_access/
    POST /api/admissions/admitted_students/<pk>/temporary_access/
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, pk: int):
        if not _can_view_passes(request.user):
            return Response({"detail": "Permission denied."}, status=403)
        student = get_object_or_404(AdmittedStudent, pk=pk)
        assert_admitted_student_access(request.user, student)
        expire_stale_passes(student)
        related = (
            "scholarship_award",
            "scholarship_award__programme",
            "issued_by",
            "approved_by",
            "student",
            "student__application",
            "student__admitted_program",
            "student__admitted_campus",
        )
        active = [
            pass_to_dict(p, request=request)
            for p in active_passes_qs(student).select_related(*related)
        ]
        pending = [
            pass_to_dict(p, request=request)
            for p in TemporaryAccessPass.objects.filter(
                student=student,
                status=TemporaryAccessPass.STATUS_PENDING,
            )
            .select_related(*related)
            .order_by("-issued_at")[:20]
        ]
        history = [
            pass_to_dict(p, request=request)
            for p in TemporaryAccessPass.objects.filter(student=student)
            .select_related(*related)
            .order_by("-issued_at")[:40]
        ]
        sponsorship = sponsorship_summary(student)
        return Response(
            {
                "student_id": student.student_id,
                "reg_no": student.reg_no,
                "current": student_temporary_access(student, request=request),
                "active": active,
                "pending": pending,
                "history": history,
                "is_sponsored": sponsorship["is_sponsored"],
                "scholarship_awards": sponsorship["scholarship_awards"],
                "can_issue": _can_issue_passes(request.user) and sponsorship["is_sponsored"],
                "can_approve": _can_approve_passes(request.user),
                "can_clear": _can_clear_passes(request.user),
                "sponsor_type_choices": [
                    {"value": v, "label": lbl}
                    for v, lbl in TemporaryAccessPass.SPONSOR_CHOICES
                ],
            }
        )

    def post(self, request, pk: int):
        if not _can_issue_passes(request.user):
            return Response({"detail": "Permission denied."}, status=403)
        student = get_object_or_404(AdmittedStudent, pk=pk)
        assert_admitted_student_access(request.user, student)
        data = request.data or {}

        if not student_is_sponsored(student):
            return Response(
                {
                    "detail": (
                        "Temporary access cards are only for students on an active "
                        "scholarship list. Attach the student under Finance → Scholarships first."
                    )
                },
                status=400,
            )

        try:
            valid_from = _parse_date(data.get("valid_from")) or timezone.localdate()
            valid_until = _parse_date(data.get("valid_until"))
        except ValueError:
            return Response({"detail": "Invalid date. Use YYYY-MM-DD."}, status=400)

        if valid_until and valid_until < valid_from:
            return Response({"detail": "valid_until cannot be before valid_from."}, status=400)

        sponsor_type = (data.get("sponsor_type") or TemporaryAccessPass.SPONSOR_OTHER).strip()
        valid_types = {c[0] for c in TemporaryAccessPass.SPONSOR_CHOICES}
        if sponsor_type not in valid_types:
            return Response({"detail": "Invalid sponsor_type."}, status=400)

        award_id = data.get("scholarship_award_id")
        award = None
        active_awards = student_active_scholarship_awards(student)
        if award_id:
            from payments.models import ScholarshipAward

            award = active_awards.filter(pk=award_id).first()
            if not award:
                return Response(
                    {"detail": "Active scholarship award not found for this student."},
                    status=400,
                )
        else:
            # Default to the student's primary active sponsorship award.
            award = active_awards.first()

        allow_lectures = bool(data.get("allow_lectures", True))
        allow_hostel = bool(data.get("allow_hostel", False))
        allow_meals = bool(data.get("allow_meals", False))
        if not (allow_lectures or allow_hostel or allow_meals):
            return Response(
                {"detail": "Select at least one of: lectures, hostel, meals."},
                status=400,
            )

        sponsor_label = (data.get("sponsor_label") or "").strip()
        if award and award.programme_id:
            prog = award.programme
            prog_type = getattr(prog, "sponsor_type", None) or ""
            if prog_type in valid_types and (
                not data.get("sponsor_type") or sponsor_type == TemporaryAccessPass.SPONSOR_OTHER
            ):
                sponsor_type = prog_type
            if not sponsor_label:
                sponsor_label = (prog.sponsor or prog.name or "").strip()

        # Always create as pending; Bursar / Finance Manager auto-approves.
        auto_approve = _can_approve_passes(request.user)
        pass_obj = TemporaryAccessPass.objects.create(
            student=student,
            scholarship_award=award,
            sponsor_type=sponsor_type,
            sponsor_label=sponsor_label,
            reason=(data.get("reason") or "").strip(),
            notes=(data.get("notes") or "").strip(),
            allow_lectures=allow_lectures,
            allow_hostel=allow_hostel,
            allow_meals=allow_meals,
            allow_registration=False,
            allow_documents=False,
            valid_from=valid_from,
            valid_until=valid_until,
            status=TemporaryAccessPass.STATUS_PENDING,
            issued_by=request.user,
        )
        if auto_approve:
            _activate_pass(pass_obj, request.user)

        pass_obj = (
            TemporaryAccessPass.objects.select_related(
                "student",
                "student__application",
                "student__admitted_program",
                "student__admitted_campus",
                "issued_by",
                "approved_by",
                "scholarship_award",
                "scholarship_award__programme",
            ).get(pk=pass_obj.pk)
        )
        payload = pass_to_dict(pass_obj, request=request)
        payload["awaiting_bursar_approval"] = pass_obj.status == TemporaryAccessPass.STATUS_PENDING
        return Response(payload, status=status.HTTP_201_CREATED)


class TemporaryAccessPassApproveView(APIView):
    """POST /api/admissions/temporary_access/<pass_id>/approve/ — Bursar activates a pending pass."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pass_id: int):
        if not _can_approve_passes(request.user):
            return Response(
                {"detail": "Only the Bursar / Finance Manager can approve a temporary access pass."},
                status=403,
            )
        pass_obj = get_object_or_404(TemporaryAccessPass, pk=pass_id)
        assert_admitted_student_access(request.user, pass_obj.student)
        if pass_obj.status != TemporaryAccessPass.STATUS_PENDING:
            return Response({"detail": "Only pending passes can be approved."}, status=400)
        expire_stale_passes(pass_obj.student)
        _activate_pass(pass_obj, request.user)
        pass_obj.refresh_from_db()
        return Response(pass_to_dict(pass_obj, request=request))


class TemporaryAccessPassRejectView(APIView):
    """POST /api/admissions/temporary_access/<pass_id>/reject/ — Bursar rejects a pending request."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pass_id: int):
        if not _can_approve_passes(request.user):
            return Response(
                {"detail": "Only the Bursar / Finance Manager can reject a temporary access pass."},
                status=403,
            )
        pass_obj = get_object_or_404(TemporaryAccessPass, pk=pass_id)
        assert_admitted_student_access(request.user, pass_obj.student)
        if pass_obj.status != TemporaryAccessPass.STATUS_PENDING:
            return Response({"detail": "Only pending passes can be rejected."}, status=400)
        pass_obj.status = TemporaryAccessPass.STATUS_REJECTED
        pass_obj.revoked_at = timezone.now()
        pass_obj.revoked_by = request.user
        pass_obj.revoke_reason = (
            (request.data.get("reason") or "").strip() or "Rejected by Bursar"
        )
        pass_obj.save(
            update_fields=[
                "status",
                "revoked_at",
                "revoked_by",
                "revoke_reason",
                "updated_at",
            ]
        )
        return Response(pass_to_dict(pass_obj, request=request))


class TemporaryAccessPassRevokeView(APIView):
    """POST /api/admissions/temporary_access/<pass_id>/revoke/"""

    permission_classes = [IsAuthenticated]

    def post(self, request, pass_id: int):
        if not _can_clear_passes(request.user):
            return Response(
                {
                    "detail": "Only the Bursar / Finance office can clear (revoke) a temporary access pass.",
                },
                status=403,
            )
        pass_obj = get_object_or_404(TemporaryAccessPass, pk=pass_id)
        assert_admitted_student_access(request.user, pass_obj.student)
        if pass_obj.status != TemporaryAccessPass.STATUS_ACTIVE:
            return Response({"detail": "Only active passes can be revoked."}, status=400)
        pass_obj.status = TemporaryAccessPass.STATUS_REVOKED
        pass_obj.revoked_at = timezone.now()
        pass_obj.revoked_by = request.user
        pass_obj.revoke_reason = (request.data.get("reason") or "").strip() or "Revoked by Accounts"
        pass_obj.save(
            update_fields=[
                "status",
                "revoked_at",
                "revoked_by",
                "revoke_reason",
                "updated_at",
            ]
        )
        return Response(pass_to_dict(pass_obj, request=request))


class TemporaryAccessPassVerifyPublicView(APIView):
    """GET /api/admissions/temporary_access/verify/<token>/ — public QR check."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, token: str):
        payload = public_verify_pass(token, request=request)
        if not payload.get("valid"):
            return Response(payload, status=status.HTTP_404_NOT_FOUND)
        return Response(payload)


class TemporaryAccessPassReportView(APIView):
    """
    GET /api/admissions/temporary_access/report/
    Finance / Bursar report of temporary access passes (active, revoked, expired).
    """

    permission_classes = [IsAuthenticated, AccountsClearedReportPermission]

    def get(self, request):
        expire_stale_passes()

        try:
            page = max(1, int(request.query_params.get("page") or 1))
        except (TypeError, ValueError):
            page = 1
        try:
            page_size = min(100, max(1, int(request.query_params.get("page_size") or 25)))
        except (TypeError, ValueError):
            page_size = 25

        search = (request.query_params.get("search") or "").strip()
        status_filter = (request.query_params.get("status") or "active").strip().lower()
        sponsor_type = (request.query_params.get("sponsor_type") or "").strip()
        from_date = parse_date(request.query_params.get("from_date") or "")
        to_date = parse_date(request.query_params.get("to_date") or "")

        today = timezone.localdate()
        qs = TemporaryAccessPass.objects.select_related(
            "student",
            "student__application",
            "student__admitted_program",
            "student__admitted_campus",
            "student__admitted_batch",
            "issued_by",
            "revoked_by",
        ).order_by("-issued_at", "-id")

        if status_filter in ("active", "current"):
            qs = qs.filter(
                status=TemporaryAccessPass.STATUS_ACTIVE,
                valid_from__lte=today,
            ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))
        elif status_filter in ("pending", "revoked", "expired", "rejected", "active_all"):
            if status_filter == "active_all":
                qs = qs.filter(status=TemporaryAccessPass.STATUS_ACTIVE)
            else:
                qs = qs.filter(status=status_filter)
        elif status_filter not in ("all", ""):
            return Response(
                {
                    "detail": "status must be active, pending, revoked, expired, rejected, active_all, or all."
                },
                status=400,
            )

        if sponsor_type:
            qs = qs.filter(sponsor_type=sponsor_type)
        if from_date:
            qs = qs.filter(issued_at__date__gte=from_date)
        if to_date:
            qs = qs.filter(issued_at__date__lte=to_date)
        if search:
            qs = qs.filter(
                Q(student__student_id__icontains=search)
                | Q(student__reg_no__icontains=search)
                | Q(student__application__first_name__icontains=search)
                | Q(student__application__last_name__icontains=search)
                | Q(sponsor_label__icontains=search)
                | Q(reason__icontains=search)
                | Q(student__admitted_program__name__icontains=search)
            )

        active_count = TemporaryAccessPass.objects.filter(
            status=TemporaryAccessPass.STATUS_ACTIVE,
            valid_from__lte=today,
        ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today)).count()

        total = qs.count()
        offset = (page - 1) * page_size
        rows = []
        for p in qs[offset : offset + page_size]:
            student = p.student
            app = getattr(student, "application", None)
            name = ""
            if app:
                name = f"{app.first_name or ''} {app.last_name or ''}".strip()
            if not name:
                name = getattr(student, "full_name", None) or "—"
            issuer = ""
            if p.issued_by_id:
                issuer = (p.issued_by.get_full_name() or "").strip() or p.issued_by.username
            clearer = ""
            if p.revoked_by_id:
                clearer = (p.revoked_by.get_full_name() or "").strip() or p.revoked_by.username
            scopes = []
            if p.allow_lectures:
                scopes.append("lectures")
            if p.allow_hostel:
                scopes.append("hostel")
            if p.allow_meals:
                scopes.append("meals")
            rows.append(
                {
                    "id": p.id,
                    "student_pk": student.id,
                    "student_id": student.student_id or "",
                    "reg_no": student.reg_no or "",
                    "student_name": name,
                    "programme": student.admitted_program.name if student.admitted_program_id else "",
                    "campus": student.admitted_campus.name if student.admitted_campus_id else "",
                    "intake": student.admitted_batch.name if student.admitted_batch_id else "",
                    "status": p.status,
                    "status_display": p.get_status_display(),
                    "sponsor_type": p.sponsor_type,
                    "sponsor_type_display": p.get_sponsor_type_display(),
                    "sponsor_label": p.sponsor_label or "",
                    "scopes": scopes,
                    "reason": (p.reason or "")[:300],
                    "valid_from": p.valid_from.isoformat() if p.valid_from else None,
                    "valid_until": p.valid_until.isoformat() if p.valid_until else None,
                    "issued_at": p.issued_at.isoformat() if p.issued_at else None,
                    "issued_by": issuer,
                    "revoked_at": p.revoked_at.isoformat() if p.revoked_at else None,
                    "revoked_by": clearer,
                    "revoke_reason": (p.revoke_reason or "")[:300],
                }
            )

        return Response(
            {
                "count": total,
                "page": page,
                "page_size": page_size,
                "active_total": active_count,
                "results": rows,
                "sponsor_type_choices": [
                    {"value": v, "label": lbl}
                    for v, lbl in TemporaryAccessPass.SPONSOR_CHOICES
                ],
            }
        )
