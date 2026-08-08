"""Temporary access passes for sponsored / pending-settlement students.

Separate from Accounts registration clearance:
- Pass can allow lectures, hostel, meals for a dated window
- Pass must NOT unlock course registration or official documents

Issue policy:
- Only students with an active scholarship / sponsorship award may receive a pass.
- Clearing / revoking a pass is restricted to Bursar / Finance clearance roles.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from django.db.models import Exists, OuterRef, Q, Subquery
from django.utils import timezone

from admissions.models import AdmittedStudent, TemporaryAccessPass


def _today() -> date:
    return timezone.localdate()


def student_active_scholarship_awards(student: AdmittedStudent):
    """Active awards on an active scholarship programme (the scholarship student list)."""
    from payments.models import ScholarshipAward

    return (
        ScholarshipAward.objects.filter(
            student=student,
            status=ScholarshipAward.STATUS_ACTIVE,
            programme__is_active=True,
        )
        .select_related("programme")
        .order_by("-awarded_at")
    )


def student_is_sponsored(student: AdmittedStudent) -> bool:
    """Temp cards only for students attached to an active scholarship list."""
    return student_active_scholarship_awards(student).exists()


def sponsorship_summary(student: AdmittedStudent) -> dict[str, Any]:
    awards = list(student_active_scholarship_awards(student)[:20])
    return {
        "is_sponsored": bool(awards),
        "scholarship_awards": [
            {
                "id": a.id,
                "programme_name": a.programme.name if a.programme_id else None,
                "programme_code": a.programme.code if a.programme_id else None,
                "sponsor": (a.programme.sponsor if a.programme_id else "") or "",
                "sponsor_type": getattr(a.programme, "sponsor_type", None) if a.programme_id else None,
                "award_amount": float(a.award_amount or 0),
                "currency": a.currency or "UGX",
                "status": a.status,
            }
            for a in awards
        ],
    }


def active_temporary_access_subquery():
    today = _today()
    return TemporaryAccessPass.objects.filter(
        student_id=OuterRef("pk"),
        status=TemporaryAccessPass.STATUS_ACTIVE,
        valid_from__lte=today,
    ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))


def annotate_temporary_access(queryset):
    """Annotate AdmittedStudent queryset with active temporary-pass indicators."""
    active = active_temporary_access_subquery().order_by("-issued_at")
    return queryset.annotate(
        has_temporary_access_pass=Exists(active),
        temporary_access_sponsor=Subquery(active.values("sponsor_label")[:1]),
        temporary_access_valid_until=Subquery(active.values("valid_until")[:1]),
    )


def annotate_scholarship_status(queryset):
    """Annotate active scholarship-list membership for student directory columns."""
    from payments.models import ScholarshipAward

    active_awards = ScholarshipAward.objects.filter(
        student_id=OuterRef("pk"),
        status=ScholarshipAward.STATUS_ACTIVE,
        programme__is_active=True,
    )
    return queryset.annotate(
        is_scholarship_sponsored=Exists(active_awards),
        scholarship_name=Subquery(
            active_awards.order_by("-awarded_at").values("programme__name")[:1]
        ),
    )


def count_active_temporary_passes(queryset=None) -> int:
    """Count students (or passes) with a currently active temporary access pass."""
    today = _today()
    qs = TemporaryAccessPass.objects.filter(
        status=TemporaryAccessPass.STATUS_ACTIVE,
        valid_from__lte=today,
    ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))
    if queryset is not None:
        qs = qs.filter(student_id__in=queryset.values("pk"))
    return qs.values("student_id").distinct().count()


def active_passes_qs(student: AdmittedStudent):
    today = _today()
    return (
        TemporaryAccessPass.objects.filter(
            student=student,
            status=TemporaryAccessPass.STATUS_ACTIVE,
            valid_from__lte=today,
        )
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))
        .select_related(
            "scholarship_award",
            "scholarship_award__programme",
            "issued_by",
            "student",
            "student__application",
            "student__admitted_program",
            "student__admitted_campus",
        )
        .order_by("-issued_at")
    )


def get_active_pass(student: AdmittedStudent) -> TemporaryAccessPass | None:
    return active_passes_qs(student).first()


def expire_stale_passes(student: AdmittedStudent | None = None) -> int:
    """Mark active passes past valid_until as expired. Returns count updated."""
    today = _today()
    qs = TemporaryAccessPass.objects.filter(
        status=TemporaryAccessPass.STATUS_ACTIVE,
        valid_until__isnull=False,
        valid_until__lt=today,
    )
    if student is not None:
        qs = qs.filter(student=student)
    return qs.update(status=TemporaryAccessPass.STATUS_EXPIRED)


def student_temporary_access(student: AdmittedStudent, *, request=None) -> dict[str, Any]:
    """Aggregated scopes from all currently active passes (OR across passes)."""
    expire_stale_passes(student)
    passes = list(active_passes_qs(student))
    if not passes:
        return {
            "has_active_pass": False,
            "allow_lectures": False,
            "allow_hostel": False,
            "allow_meals": False,
            "allow_registration": False,
            "allow_documents": False,
            "passes": [],
            "message": None,
        }

    allow_lectures = any(p.allow_lectures for p in passes)
    allow_hostel = any(p.allow_hostel for p in passes)
    allow_meals = any(p.allow_meals for p in passes)
    # Hard policy: temporary passes never grant registration or official docs.
    allow_registration = False
    allow_documents = False

    primary = passes[0]
    until = primary.valid_until
    for p in passes:
        if p.valid_until is None:
            until = None
            break
        if until is None or p.valid_until > until:
            until = p.valid_until

    scopes: list[str] = []
    if allow_lectures:
        scopes.append("lectures")
    if allow_hostel:
        scopes.append("hostel")
    if allow_meals:
        scopes.append("meals")
    scope_txt = ", ".join(scopes) if scopes else "limited access"
    until_txt = until.isoformat() if until else "further notice"
    message = (
        f"Temporary access ({scope_txt}) until {until_txt}. "
        "Course registration and official documents remain locked until Accounts "
        "gives full registration clearance."
    )

    return {
        "has_active_pass": True,
        "allow_lectures": allow_lectures,
        "allow_hostel": allow_hostel,
        "allow_meals": allow_meals,
        "allow_registration": allow_registration,
        "allow_documents": allow_documents,
        "valid_until": until.isoformat() if until else None,
        "message": message,
        "passes": [pass_to_dict(p, request=request) for p in passes],
    }


def pass_to_dict(p: TemporaryAccessPass, *, request=None) -> dict[str, Any]:
    award = p.scholarship_award
    programme = getattr(award, "programme", None) if award else None
    student = p.student
    app = getattr(student, "application", None)
    photo = None
    if app is not None:
        raw_photo = getattr(app, "passport_photo", None) or getattr(app, "photo", None)
        if raw_photo:
            try:
                url = raw_photo.url
                if request is not None:
                    photo = request.build_absolute_uri(url)
                else:
                    photo = url
            except Exception:
                photo = str(raw_photo) if raw_photo else None

    prog = getattr(student, "admitted_program", None)
    campus = getattr(student, "admitted_campus", None)
    issuer = None
    if p.issued_by_id:
        issuer = (p.issued_by.get_full_name() or "").strip() or p.issued_by.username
    approver = None
    if getattr(p, "approved_by_id", None):
        approver = (p.approved_by.get_full_name() or "").strip() or p.approved_by.username

    return {
        "id": p.id,
        "verification_token": str(p.verification_token) if p.verification_token else None,
        "status": p.status,
        "status_display": p.get_status_display(),
        "sponsor_type": p.sponsor_type,
        "sponsor_type_display": p.get_sponsor_type_display(),
        "sponsor_label": p.sponsor_label,
        "reason": p.reason,
        "notes": p.notes,
        "allow_lectures": p.allow_lectures,
        "allow_hostel": p.allow_hostel,
        "allow_meals": p.allow_meals,
        "allow_registration": False,
        "allow_documents": False,
        "valid_from": p.valid_from.isoformat() if p.valid_from else None,
        "valid_until": p.valid_until.isoformat() if p.valid_until else None,
        "issued_at": p.issued_at.isoformat() if p.issued_at else None,
        "issued_by_name": issuer,
        "approved_at": p.approved_at.isoformat() if getattr(p, "approved_at", None) else None,
        "approved_by_name": approver,
        "scholarship_award_id": award.id if award else None,
        "scholarship_programme": programme.name if programme else None,
        "revoked_at": p.revoked_at.isoformat() if p.revoked_at else None,
        "revoke_reason": p.revoke_reason,
        "student": {
            "id": student.id,
            "student_id": student.student_id,
            "reg_no": student.reg_no,
            "name": getattr(student, "full_name", None)
            or (getattr(app, "full_name", None) if app else None)
            or "",
            "programme": prog.name if prog else None,
            "campus": campus.name if campus else None,
            "passport_photo": photo,
        },
    }


def public_verify_pass(token: str, *, request=None) -> dict[str, Any]:
    """Live verification payload for QR scans on printed temporary pass cards."""
    expire_stale_passes()
    try:
        pass_obj = TemporaryAccessPass.objects.select_related(
            "student",
            "student__application",
            "student__admitted_program",
            "student__admitted_campus",
            "issued_by",
            "scholarship_award",
            "scholarship_award__programme",
        ).get(verification_token=token)
    except (TemporaryAccessPass.DoesNotExist, ValueError, TypeError):
        return {"valid": False, "detail": "Temporary access pass not found."}

    live = student_temporary_access(pass_obj.student)
    # This specific pass is currently active in the live aggregation?
    active_ids = {p["id"] for p in live.get("passes") or []}
    this_active = (
        pass_obj.status == TemporaryAccessPass.STATUS_ACTIVE
        and pass_obj.id in active_ids
    )

    scopes = []
    if pass_obj.allow_lectures:
        scopes.append("lectures")
    if pass_obj.allow_hostel:
        scopes.append("hostel")
    if pass_obj.allow_meals:
        scopes.append("meals")

    return {
        "valid": True,
        "pass_active": this_active,
        "status": pass_obj.status,
        "status_display": pass_obj.get_status_display(),
        "scopes": scopes,
        "message": (
            live.get("message")
            if this_active
            else (
                "This temporary pass is no longer active "
                f"({pass_obj.get_status_display().lower()})."
            )
        ),
        "pass": pass_to_dict(pass_obj, request=request),
        "may_access_lectures": bool(this_active and pass_obj.allow_lectures),
        "may_access_hostel": bool(this_active and pass_obj.allow_hostel),
        "may_access_meals": bool(this_active and pass_obj.allow_meals),
        "may_register": False,
        "may_print_documents": False,
        "checked_at": timezone.now().isoformat(),
    }
