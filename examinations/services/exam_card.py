"""Exam card: full outstanding balance cleared + academically eligible course units."""
from __future__ import annotations

import base64
import io
import uuid
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from admissions.models import AdmittedStudent
from Programs.models import StudentCourseUnitEnrollment

from ..models import ExamCardToken, ExamRetakeRegistration
from .eligibility import evaluate_exam_eligibility


def _exam_period_label(student: AdmittedStudent) -> str:
    try:
        enr = student.programme_enrollment
        if enr and enr.program_batch_id:
            batch = enr.program_batch
            y = enr.current_year_of_study
            t = enr.current_term_number
            if y and t:
                return f"{batch.name} — Year {y} Term {t} examinations"
            return f"{batch.name} examinations"
    except Exception:
        pass
    return "University examinations"


def full_outstanding_balance_status(student: AdmittedStudent) -> dict:
    """
    Cleared when every billing line (tuition, scheduled fees, ad-hoc) has zero balance.
    """
    from payments.student_portal_finance import student_billing_lines

    lines = student_billing_lines(student)
    if not lines:
        return {
            "tuition_cleared": True,
            "total_required": 0.0,
            "total_paid": 0.0,
            "total_balance": 0.0,
            "display_currency": "UGX",
            "balances_by_currency": {},
            "shortfalls_by_currency": {},
            "message": "No tuition or fee charges on record.",
        }

    by_ccy: dict[str, dict] = {}
    for line in lines:
        ccy = (line.get("currency") or "UGX").upper()
        bucket = by_ccy.setdefault(
            ccy,
            {"required": Decimal("0"), "paid": Decimal("0"), "balance": Decimal("0")},
        )
        bucket["required"] += Decimal(str(line.get("amount") or 0))
        bucket["paid"] += Decimal(str(line.get("paid_amount") or 0))
        bucket["balance"] += Decimal(str(line.get("balance") or 0))

    shortfalls = {
        ccy: float(b["balance"])
        for ccy, b in by_ccy.items()
        if b["balance"] > Decimal("0.01")
    }
    cleared = len(shortfalls) == 0
    primary = max(by_ccy.keys(), key=lambda k: float(by_ccy[k]["required"])) if by_ccy else "UGX"
    totals = by_ccy.get(primary, {"required": Decimal("0"), "paid": Decimal("0"), "balance": Decimal("0")})

    if cleared:
        msg = "Full outstanding balance cleared. You may print your examination card."
    else:
        parts = [f"{ccy} {amt:,.2f}" for ccy, amt in shortfalls.items()]
        msg = f"Outstanding balance remains: {', '.join(parts)}."

    return {
        "tuition_cleared": cleared,
        "total_required": float(totals["required"]),
        "total_paid": float(totals["paid"]),
        "total_balance": float(sum(b["balance"] for b in by_ccy.values())),
        "display_currency": primary,
        "balances_by_currency": {k: float(v["balance"]) for k, v in by_ccy.items()},
        "shortfalls_by_currency": shortfalls,
        "message": msg,
    }


def academically_eligible_courses(student: AdmittedStudent) -> list[dict]:
    """Course units the student may sit (CA threshold, enrolled, not revoked)."""
    enrollments = (
        StudentCourseUnitEnrollment.objects.filter(student=student, status="enrolled")
        .select_related(
            "course_unit",
            "course_unit__semester",
            "course_result",
            "student",
            "student__application",
            "course_unit__program_batch__program__academic_level",
        )
        .order_by("course_unit__code")
    )

    retake_enrollment_ids = set(
        ExamRetakeRegistration.objects.filter(
            enrollment__student=student,
            status__in=(
                ExamRetakeRegistration.STATUS_APPROVED,
                ExamRetakeRegistration.STATUS_SCHEDULED,
            ),
        ).values_list("enrollment_id", flat=True)
    )

    courses = []
    for enr in enrollments:
        elig = evaluate_exam_eligibility(enr)
        is_retake = enr.id in retake_enrollment_ids
        if not elig["eligible"] and not is_retake:
            continue
        cu = enr.course_unit
        courses.append(
            {
                "enrollment_id": enr.id,
                "course_code": cu.code,
                "course_name": cu.name,
                "semester_name": cu.semester.name if cu.semester_id else "",
                "ca_mark": elig.get("ca_mark"),
                "is_retake": is_retake,
            }
        )
    return courses


def frontend_verify_url(verification_code) -> str:
    base = (getattr(settings, "ERP_FRONTEND_URL", None) or "").rstrip("/")
    if not base:
        base = "http://localhost:5173"
    return f"{base}/verify-exam-card/{verification_code}"


def qr_png_base64(url: str) -> str:
    import qrcode

    qr = qrcode.QRCode(version=None, box_size=4, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def issue_or_refresh_exam_card_token(student: AdmittedStudent) -> ExamCardToken | None:
    finance = full_outstanding_balance_status(student)
    if not finance["tuition_cleared"]:
        return None

    token = (
        ExamCardToken.objects.filter(student=student, is_revoked=False)
        .order_by("-issued_at")
        .first()
    )
    label = _exam_period_label(student)
    if token and token.expires_at and token.expires_at < timezone.now():
        token.is_revoked = True
        token.save(update_fields=["is_revoked"])
        token = None

    if token:
        if token.exam_period_label != label:
            token.exam_period_label = label
            token.save(update_fields=["exam_period_label"])
        return token

    return ExamCardToken.objects.create(
        student=student,
        verification_code=uuid.uuid4(),
        exam_period_label=label,
    )


def build_exam_card_payload(
    student: AdmittedStudent,
    *,
    request=None,
    issue_token: bool = True,
) -> dict:
    finance = full_outstanding_balance_status(student)
    courses = academically_eligible_courses(student)
    can_print = finance["tuition_cleared"] and len(courses) > 0

    token = None
    verify_url = ""
    qr_b64 = ""
    if issue_token and can_print:
        token = issue_or_refresh_exam_card_token(student)
        if token:
            verify_url = frontend_verify_url(token.verification_code)
            qr_b64 = qr_png_base64(verify_url)

    photo_url = None
    app = getattr(student, "application", None)
    if app and app.passport_photo:
        try:
            url = app.passport_photo.url
            photo_url = request.build_absolute_uri(url) if request else url
        except Exception:
            photo_url = None

    blockers = []
    if not finance["tuition_cleared"]:
        blockers.append(finance["message"])
    if not courses:
        blockers.append(
            "No course units are academically eligible yet (CA mark and enrollment required)."
        )

    return {
        "student": {
            "name": student.full_name or "",
            "reg_no": student.reg_no or "",
            "program": student.admitted_program.name if student.admitted_program_id else "",
            "photo_url": photo_url,
        },
        "exam_period_label": _exam_period_label(student),
        "finance": finance,
        "courses": courses,
        "can_print": can_print and bool(token),
        "blockers": blockers,
        "verification_code": str(token.verification_code) if token else None,
        "verify_url": verify_url,
        "qr_png_base64": qr_b64,
        "issued_at": token.issued_at.isoformat() if token else None,
    }


def build_exam_card_verify_payload(token: ExamCardToken, *, request=None) -> dict:
    """Live verification for QR scan (re-checks payment; do not trust PDF alone)."""
    student = token.student
    if token.is_revoked:
        return {"valid": False, "detail": "This examination card has been revoked."}

    if token.expires_at and token.expires_at < timezone.now():
        return {"valid": False, "detail": "This examination card has expired."}

    finance = full_outstanding_balance_status(student)
    courses = academically_eligible_courses(student)

    photo_url = None
    app = getattr(student, "application", None)
    if app and app.passport_photo:
        try:
            url = app.passport_photo.url
            photo_url = request.build_absolute_uri(url) if request else url
        except Exception:
            photo_url = None

    payment_ok = finance["tuition_cleared"]
    return {
        "valid": True,
        "verification_code": str(token.verification_code),
        "issued_at": token.issued_at.isoformat(),
        "exam_period_label": token.exam_period_label,
        "student": {
            "name": student.full_name or "",
            "reg_no": student.reg_no or "",
            "program": student.admitted_program.name if student.admitted_program_id else "",
            "photo_url": photo_url,
        },
        "payment": {
            "cleared": payment_ok,
            "status_label": "CLEARED" if payment_ok else "NOT CLEARED",
            "total_balance": finance["total_balance"],
            "display_currency": finance["display_currency"],
            "shortfalls_by_currency": finance["shortfalls_by_currency"],
            "message": finance["message"],
            "checked_at": timezone.now().isoformat(),
        },
        "eligible_courses": courses,
        "may_enter_examination_block": payment_ok and len(courses) > 0,
    }
