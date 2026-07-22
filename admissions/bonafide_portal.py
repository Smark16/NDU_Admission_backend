"""Admin snapshot of student-portal data for bonafide profile (finance, results, exam card)."""
from __future__ import annotations

import logging

from django.db import DatabaseError

from admissions.models import AdmittedStudent
from payments.registration_lookup import _course_rows_for_student
from payments.student_portal_finance import (
    registration_card_payment_history,
    student_billing_lines,
    student_finance_totals,
)

logger = logging.getLogger(__name__)


def _safe(label: str, errors: dict, fn, fallback):
    try:
        return fn()
    except Exception as exc:
        logger.exception("Bonafide portal snapshot failed for %s: %s", label, exc)
        errors[label] = str(exc)[:300]
        return fallback


def _published_results(student: AdmittedStudent) -> dict:
    from examinations.models import CourseUnitResult
    from examinations.serializers import CourseUnitResultSerializer

    results = (
        CourseUnitResult.objects.filter(
            enrollment__student=student,
            status=CourseUnitResult.STATUS_PUBLISHED,
        )
        .select_related(
            "enrollment",
            "enrollment__course_unit",
            "enrollment__course_unit__semester",
        )
        .order_by(
            "enrollment__course_unit__semester__order",
            "enrollment__course_unit__code",
        )
    )
    by_semester: dict[str, list] = {}
    for result in results:
        sem = result.enrollment.course_unit.semester
        key = sem.name if sem else "Other"
        by_semester.setdefault(key, []).append(CourseUnitResultSerializer(result).data)
    return {
        "semesters": [{"name": k, "courses": v} for k, v in by_semester.items()],
        "course_count": sum(len(v) for v in by_semester.values()),
    }


def _exam_permit_summary(student: AdmittedStudent, request=None) -> dict:
    from examinations.services.exam_card import build_exam_card_payload

    # Do not issue/print tokens just because an admin opened the profile.
    payload = build_exam_card_payload(student, request=request, issue_token=False)
    finance = payload.get("finance") or {}
    courses = payload.get("courses") or []
    eligible = bool(finance.get("tuition_cleared")) and len(courses) > 0
    return {
        "exam_period_label": payload.get("exam_period_label"),
        "eligible": eligible,
        "tuition_cleared": bool(finance.get("tuition_cleared")),
        "total_balance": finance.get("total_balance"),
        "display_currency": finance.get("display_currency") or "UGX",
        "message": finance.get("message") or "",
        "blockers": payload.get("blockers") or [],
        "eligible_course_count": len(courses),
        "courses": [
            {
                "course_code": c.get("course_code"),
                "course_name": c.get("course_name"),
                "semester_name": c.get("semester_name"),
                "is_retake": bool(c.get("is_retake")),
            }
            for c in courses[:40]
        ],
    }


def _portal_account_status(student: AdmittedStudent) -> dict:
    from admissions.models import StudentPortalAccountAction

    user = getattr(student, "student_user", None)
    history = []
    try:
        rows = student.portal_account_actions.select_related("performed_by").order_by(
            "-created_at"
        )[:20]
        for row in rows:
            history.append(
                {
                    "id": row.id,
                    "action": row.action,
                    "reason": row.reason,
                    "performed_by": (
                        row.performed_by.get_full_name() or row.performed_by.username
                        if row.performed_by_id
                        else None
                    ),
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
            )
    except (DatabaseError, StudentPortalAccountAction.DoesNotExist):
        # Migration 0049 may not be applied yet on some environments.
        history = []

    return {
        "has_portal_user": bool(user),
        "is_active": bool(user.is_active) if user else False,
        "username": (user.username if user else None),
        "history": history,
    }


def build_bonafide_portal_snapshot(student: AdmittedStudent, request=None) -> dict:
    """
    Build portal tabs for admin bonafide profile.

    Each section is isolated so one failure (e.g. missing audit table, exam edge
    case) still returns finance / courses / etc.
    """
    errors: dict[str, str] = {}

    finance = _safe("finance", errors, lambda: student_finance_totals(student), {})
    history = _safe(
        "payment_history",
        errors,
        lambda: registration_card_payment_history(student, limit=25),
        [],
    )
    results = _safe(
        "results",
        errors,
        lambda: _published_results(student),
        {"semesters": [], "course_count": 0},
    )
    exam = _safe(
        "exam_permit",
        errors,
        lambda: _exam_permit_summary(student, request=request),
        {
            "eligible": False,
            "tuition_cleared": False,
            "blockers": ["Exam permit summary unavailable."],
            "courses": [],
            "eligible_course_count": 0,
        },
    )
    courses = _safe("registered_courses", errors, lambda: _course_rows_for_student(student), [])
    billing = _safe("billing", errors, lambda: student_billing_lines(student), [])
    portal_account = _safe(
        "portal_account",
        errors,
        lambda: _portal_account_status(student),
        {"has_portal_user": False, "is_active": False, "username": None, "history": []},
    )

    outstanding = [
        {
            "kind": ln.get("kind"),
            "fee_head": ln.get("fee_head"),
            "description": ln.get("description"),
            "amount": ln.get("amount"),
            "paid_amount": ln.get("paid_amount"),
            "balance": ln.get("balance"),
            "currency": ln.get("currency"),
            "status": ln.get("status"),
        }
        for ln in billing
        if float(ln.get("balance") or 0) > 0.01
    ][:30]

    return {
        "student_id": student.student_id,
        "reg_no": student.reg_no,
        "finance": {
            "percentage_paid": finance.get("percentage_paid"),
            "total_paid": finance.get("total_paid"),
            "total_required": finance.get("total_required"),
            "balance": finance.get("balance"),
            "display_currency": finance.get("display_currency") or "UGX",
            "commitment_met": finance.get("commitment_met"),
            "commitment_paid_ugx": finance.get("commitment_paid_ugx"),
            "commitment_threshold": finance.get("commitment_threshold"),
            "payment_history": history,
            "outstanding_lines": outstanding,
        },
        "results": results,
        "exam_permit": exam,
        "registered_courses": courses,
        "registered_courses_count": len(courses),
        "portal_account": portal_account,
        "partial_errors": errors or None,
    }
