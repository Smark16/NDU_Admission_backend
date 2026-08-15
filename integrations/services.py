"""Domain helpers for Moodle integration endpoints."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from django.contrib.auth import authenticate, get_user_model
from django.db.models import Q

from admissions.models import AdmittedStudent
from payments.student_portal_finance import student_finance_totals

from .models import MoodleApiAccessLog, MoodleIntegrationConfig

User = get_user_model()


def log_moodle_access(
    *,
    endpoint: str,
    http_status: int,
    key_prefix: str = "",
    detail: str = "",
) -> None:
    try:
        MoodleApiAccessLog.objects.create(
            endpoint=endpoint[:120],
            key_prefix=(key_prefix or "")[:16],
            http_status=http_status,
            detail=(detail or "")[:255],
        )
    except Exception:
        pass


def resolve_student_by_lookup(lookup: str) -> AdmittedStudent | None:
    key = (lookup or "").strip()
    if not key:
        return None
    return (
        AdmittedStudent.objects.filter(is_admitted=True)
        .filter(Q(reg_no__iexact=key) | Q(student_id__iexact=key))
        .select_related(
            "admitted_program",
            "admitted_campus",
            "student_user",
            "application",
            "intended_program_batch",
            "programme_enrollment",
            "programme_enrollment__program_batch",
        )
        .first()
    )


def verify_student_credentials(username: str, password: str) -> tuple[User | None, AdmittedStudent | None]:
    """
    Authenticate Steward credentials for Moodle.
    Accepts portal username or registration number.
    """
    uname = (username or "").strip()
    pwd = password or ""
    if not uname or not pwd:
        return None, None

    user = authenticate(username=uname, password=pwd)
    student = None
    if user is None:
        student = resolve_student_by_lookup(uname)
        if student and student.student_user_id:
            portal_username = student.student_user.username
            user = authenticate(username=portal_username, password=pwd)

    if user is None:
        return None, None

    if student is None:
        student = (
            AdmittedStudent.objects.filter(is_admitted=True, student_user=user)
            .select_related(
                "admitted_program",
                "admitted_campus",
                "application",
                "intended_program_batch",
                "programme_enrollment",
                "programme_enrollment__program_batch",
            )
            .first()
        )
        if student is None:
            student = resolve_student_by_lookup(user.username)

    return user, student


def academic_batch_payload(student: AdmittedStudent) -> dict:
    """Enrollment cohort first, then intended batch. Additive LMS fields only."""
    from Programs.program_batch_resolution import format_program_batch_display

    batch = None
    try:
        enrollment = student.programme_enrollment
    except Exception:
        enrollment = None
    if enrollment is not None and enrollment.program_batch_id:
        batch = enrollment.program_batch
    if batch is None:
        batch = getattr(student, "intended_program_batch", None)
    if batch is None or not getattr(batch, "pk", None):
        return {"academic_batch_id": None, "academic_batch": None}
    return {
        "academic_batch_id": batch.pk,
        "academic_batch": format_program_batch_display(batch),
    }


def student_profile_payload(student: AdmittedStudent, user: User | None = None) -> dict:
    app = getattr(student, "application", None)
    payload = {
        "reg_no": student.reg_no or "",
        "student_id": student.student_id or "",
        "username": (user.username if user else "") or (student.reg_no or ""),
        "full_name": student.full_name or "",
        "email": (getattr(app, "email", None) or getattr(user, "email", None) or "") if (app or user) else "",
        "programme": student.admitted_program.name if student.admitted_program_id else None,
        "campus": student.admitted_campus.name if student.admitted_campus_id else None,
        "accounts_registration_cleared": bool(
            getattr(student, "accounts_registration_cleared", False)
        ),
    }
    payload.update(academic_batch_payload(student))
    return payload


def finance_status_for_student(student: AdmittedStudent) -> dict:
    cfg = MoodleIntegrationConfig.get_solo()
    try:
        finance = student_finance_totals(student)
    except Exception:
        finance = {
            "percentage_paid": 0,
            "balance": 0,
            "total_paid": 0,
            "total_required": 0,
            "display_currency": "UGX",
            "commitment_met": False,
            "prepaid_credit": 0,
        }

    percent = Decimal(str(finance.get("percentage_paid") or 0))
    balance = Decimal(str(finance.get("balance") or 0))
    cleared_min = Decimal(str(cfg.cleared_min_percent or 100))
    partial_min = Decimal(str(cfg.partial_min_percent or 50))

    if balance <= 0 or percent >= cleared_min:
        status = "CLEARED"
    elif percent >= partial_min:
        status = "PARTIAL"
    else:
        status = "BLOCKED"

    payload = {
        "reg_no": student.reg_no or "",
        "student_id": student.student_id or "",
        "status": status,
        "percent_paid": float(percent),
        "balance": float(balance),
        "prepaid_credit": float(finance.get("prepaid_credit") or 0),
        "total_paid": float(finance.get("total_paid") or 0),
        "total_required": float(finance.get("total_required") or 0),
        "display_currency": finance.get("display_currency") or "UGX",
        "accounts_cleared": bool(getattr(student, "accounts_registration_cleared", False)),
        "commitment_met": bool(finance.get("commitment_met")),
        "cleared_min_percent": float(cleared_min),
        "partial_min_percent": float(partial_min),
        "as_of": datetime.now(timezone.utc).isoformat(),
    }
    payload.update(academic_batch_payload(student))
    return payload


def lecturer_payload(user) -> dict:
    return {
        "id": user.pk,
        "username": user.username,
        "email": user.email or "",
        "full_name": user.get_full_name() or user.username,
        "staff_id": getattr(user, "staff_id", None) or "",
    }
