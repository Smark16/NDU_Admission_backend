"""Unified student card scan desk: one QR identity, purpose-gated live payloads."""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from django.db.models import Q

from admissions.models import AdmittedStudent

PURPOSE_ID = "id"
PURPOSE_REGISTRATION = "registration"
PURPOSE_EXAM = "exam"
VALID_PURPOSES = (PURPOSE_ID, PURPOSE_REGISTRATION, PURPOSE_EXAM)

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)


def normalize_purpose(raw: str | None) -> str:
    p = (raw or PURPOSE_REGISTRATION).strip().lower()
    if p in ("identity", "id_card", "student_id"):
        return PURPOSE_ID
    if p in ("reg", "registration_card", "register"):
        return PURPOSE_REGISTRATION
    if p in ("examination", "exam_card", "exams"):
        return PURPOSE_EXAM
    if p in VALID_PURPOSES:
        return p
    return PURPOSE_REGISTRATION


def parse_scan_code(raw: str) -> dict[str, Any]:
    """
    Extract lookup key and optional hint from a camera / keyboard scan.

    Accepts:
      - bare paycode / student_id / reg_no
      - NDU|id|<code>, NDU|reg|<code>, NDU|exam|<uuid>
      - …/verify-registration/<code>
      - …/verify-exam-card/<uuid>
    """
    t = (raw or "").strip().replace("\x00", "")
    out: dict[str, Any] = {
        "raw": t,
        "lookup": None,
        "exam_token": None,
        "hint_purpose": None,
    }
    if not t:
        return out

    m = re.search(r"verify-exam-card/([0-9a-f-]{36})", t, re.I)
    if m:
        out["exam_token"] = m.group(1)
        out["hint_purpose"] = PURPOSE_EXAM
        return out

    m = re.search(r"verify-registration/([^/?#]+)", t, re.I)
    if m:
        out["lookup"] = unquote(m.group(1))
        out["hint_purpose"] = PURPOSE_REGISTRATION
        return out

    if re.match(r"^NDU[|:/]", t, re.I):
        parts = re.split(r"[|:/]+", t, maxsplit=2)
        parts = [p for p in parts if p]
        if len(parts) >= 3 and parts[0].upper() == "NDU":
            kind = parts[1].lower()
            value = parts[2].strip()
            if kind in ("exam", "examination") and _UUID_RE.match(value):
                out["exam_token"] = value
                out["hint_purpose"] = PURPOSE_EXAM
                return out
            if kind in ("id", "identity", "student"):
                out["lookup"] = value
                out["hint_purpose"] = PURPOSE_ID
                return out
            if kind in ("reg", "registration"):
                out["lookup"] = value
                out["hint_purpose"] = PURPOSE_REGISTRATION
                return out
            out["lookup"] = value
            return out

    try:
        if "://" in t:
            u = urlparse(t)
            qs = parse_qs(u.query)
            for key in ("student_id", "paycode", "code", "reg_no"):
                if qs.get(key):
                    out["lookup"] = qs[key][0].strip()
                    return out
            last = unquote(u.path.rstrip("/").split("/")[-1])
            if last and _UUID_RE.match(last):
                out["exam_token"] = last
                out["hint_purpose"] = PURPOSE_EXAM
                return out
            if last and re.match(r"^[\w./-]{2,64}$", last):
                out["lookup"] = last
                return out
    except Exception:
        pass

    if t.startswith("{"):
        try:
            j = json.loads(t)
            for key in ("student_no", "student_id", "reg_no", "paycode"):
                if j.get(key):
                    out["lookup"] = str(j[key]).strip()
                    return out
        except Exception:
            pass

    if _UUID_RE.match(t):
        out["exam_token"] = t
        out["hint_purpose"] = PURPOSE_EXAM
        return out

    if re.match(r"^[\w./-]{2,64}$", t):
        out["lookup"] = t
    return out


def resolve_student(lookup: str) -> AdmittedStudent | None:
    key = (lookup or "").strip()
    if not key:
        return None
    return (
        AdmittedStudent.objects.filter(
            Q(student_id=key) | Q(reg_no=key) | Q(schoolpay_code=key),
            is_admitted=True,
        )
        .select_related("admitted_program", "admitted_campus", "application")
        .first()
    )


def _id_card_meta(student: AdmittedStudent) -> dict:
    try:
        from admissions.models import StudentIdCard

        card = (
            StudentIdCard.objects.filter(admitted_student=student, is_active=True)
            .order_by("-created_at", "-id")
            .first()
        )
        if not card:
            return {"id_card_number": None, "id_card_expiry": None, "id_card_status": None}
        return {
            "id_card_number": card.card_number,
            "id_card_expiry": card.expiry_date.isoformat() if card.expiry_date else None,
            "id_card_status": getattr(card, "status", None),
        }
    except Exception:
        return {"id_card_number": None, "id_card_expiry": None, "id_card_status": None}


def build_id_gate_payload(student: AdmittedStudent, request=None) -> dict:
    from payments.registration_lookup import _passport_photo_url, _programme_position

    position = _programme_position(student)
    meta = _id_card_meta(student)
    return {
        "valid": True,
        "purpose": PURPOSE_ID,
        "verdict": "pass",
        "message": "IDENTITY OK — student recognised",
        "student_id": student.student_id,
        "schoolpay_code": student.effective_schoolpay_code,
        "reg_no": student.reg_no,
        "student_name": student.full_name,
        "programme": student.admitted_program.name if student.admitted_program_id else None,
        "campus": student.admitted_campus.name if student.admitted_campus_id else None,
        "passport_photo": _passport_photo_url(student, request),
        **position,
        **meta,
    }


def build_registration_gate_payload(student: AdmittedStudent, request=None) -> dict:
    from admissions.registration_workflow import registration_clearance_block_reason
    from payments.registration_lookup import build_public_verify_payload

    block_reason = registration_clearance_block_reason(student)
    if block_reason:
        return {
            "valid": False,
            "purpose": PURPOSE_REGISTRATION,
            "verdict": "deny",
            "detail": f"DENY — {block_reason}",
            "accounts_registration_cleared": bool(
                getattr(student, "accounts_registration_cleared", False)
            ),
            "physical_documents_verified": bool(
                getattr(student, "physical_documents_verified", False)
            ),
            "student_id": student.student_id,
            "reg_no": student.reg_no,
            "student_name": student.full_name,
        }

    payload = build_public_verify_payload(student, request)
    payload["purpose"] = PURPOSE_REGISTRATION
    payload["verdict"] = "pass"
    payload["message"] = "ALLOW — Accounts + AR cleared · registration recognised"
    return payload


def build_exam_gate_from_student(student: AdmittedStudent, request=None) -> dict:
    from examinations.services.exam_card import (
        academically_eligible_courses,
        full_outstanding_balance_status,
    )
    from payments.registration_lookup import _passport_photo_url, _programme_position

    try:
        finance = full_outstanding_balance_status(student)
    except Exception:
        finance = {
            "tuition_cleared": False,
            "message": "Could not load fee status.",
            "total_balance": 0,
            "display_currency": "UGX",
        }
    try:
        courses = academically_eligible_courses(student)
    except Exception:
        courses = []
    payment_ok = bool(finance.get("tuition_cleared"))
    has_courses = len(courses) > 0
    ok = payment_ok and has_courses
    blockers = []
    if not payment_ok:
        blockers.append(finance.get("message") or "Outstanding balance remains.")
    if not has_courses:
        blockers.append("No academically eligible course units to sit.")

    return {
        "valid": ok,
        "purpose": PURPOSE_EXAM,
        "verdict": "pass" if ok else "deny",
        "message": (
            "ALLOW — Exam entry cleared"
            if ok
            else ("DENY — " + " ".join(blockers))
        ),
        "student_id": student.student_id,
        "reg_no": student.reg_no,
        "student_name": student.full_name,
        "programme": student.admitted_program.name if student.admitted_program_id else None,
        "campus": student.admitted_campus.name if student.admitted_campus_id else None,
        "passport_photo": _passport_photo_url(student, request),
        **_programme_position(student),
        "exam": {
            "payment_cleared": payment_ok,
            "eligible_courses_count": len(courses),
            "courses": courses[:40],
            "finance": finance,
            "blockers": blockers,
            "source": "student_id",
        },
    }


def build_exam_gate_from_token(token, request=None) -> dict:
    from examinations.services.exam_card import build_exam_card_verify_payload

    raw = build_exam_card_verify_payload(token, request=request)
    if not raw.get("valid"):
        return {
            "valid": False,
            "purpose": PURPOSE_EXAM,
            "verdict": "deny",
            "detail": raw.get("detail") or "Exam card not valid.",
            "message": raw.get("detail") or "DENY — Exam card not valid.",
        }

    payment = raw.get("payment") or {}
    courses = raw.get("courses") or []
    payment_ok = bool(payment.get("cleared"))
    ok = payment_ok and len(courses) > 0
    student = raw.get("student") or {}
    return {
        "valid": ok,
        "purpose": PURPOSE_EXAM,
        "verdict": "pass" if ok else "deny",
        "message": (
            "ALLOW — Exam card verified"
            if ok
            else (
                "DENY — "
                + (payment.get("message") or "Exam entry not cleared.")
            )
        ),
        "student_name": student.get("name"),
        "reg_no": student.get("reg_no"),
        "programme": student.get("program"),
        "passport_photo": student.get("photo_url"),
        "exam": {
            "payment_cleared": payment_ok,
            "eligible_courses_count": len(courses),
            "courses": courses[:40],
            "finance": payment,
            "verification_code": raw.get("verification_code"),
            "exam_period_label": raw.get("exam_period_label"),
            "issued_at": raw.get("issued_at"),
            "source": "exam_token",
        },
    }


def run_scan_desk(*, code: str, purpose: str, request=None) -> tuple[dict, int]:
    """
    Returns (payload, http_status).
    Desk purpose wins; code hint only used when purpose is ambiguous.
    """
    purpose = normalize_purpose(purpose)
    parsed = parse_scan_code(code)

    if purpose == PURPOSE_EXAM and parsed.get("exam_token"):
        from examinations.models import ExamCardToken

        try:
            token = ExamCardToken.objects.select_related(
                "student",
                "student__admitted_program",
                "student__admitted_campus",
            ).get(verification_code=parsed["exam_token"])
        except (ExamCardToken.DoesNotExist, ValueError, TypeError):
            return (
                {
                    "valid": False,
                    "purpose": PURPOSE_EXAM,
                    "verdict": "deny",
                    "detail": "Exam card token not recognised.",
                    "message": "DENY — Exam card token not recognised.",
                },
                404,
            )
        payload = build_exam_gate_from_token(token, request=request)
        return payload, 200 if payload.get("valid") else 403

    lookup = parsed.get("lookup")
    if not lookup and parsed.get("exam_token") and purpose != PURPOSE_EXAM:
        # Scanned an exam token at ID/registration desk — still resolve via token student
        from examinations.models import ExamCardToken

        try:
            token = ExamCardToken.objects.select_related("student").get(
                verification_code=parsed["exam_token"]
            )
            lookup = token.student.student_id or token.student.reg_no
        except ExamCardToken.DoesNotExist:
            pass

    if not lookup:
        return (
            {
                "valid": False,
                "purpose": purpose,
                "verdict": "deny",
                "detail": "Could not read a student identifier from this code.",
                "message": "DENY — Unrecognised code.",
            },
            400,
        )

    student = resolve_student(lookup)
    if not student:
        return (
            {
                "valid": False,
                "purpose": purpose,
                "verdict": "deny",
                "detail": "Student not recognised.",
                "message": "DENY — Card not recognised.",
            },
            404,
        )

    if purpose == PURPOSE_ID:
        return build_id_gate_payload(student, request), 200

    if purpose == PURPOSE_REGISTRATION:
        payload = build_registration_gate_payload(student, request)
        status = 200 if payload.get("valid") else 403
        return payload, status

    # exam via student id / paycode on plastic ID
    payload = build_exam_gate_from_student(student, request)
    status = 200 if payload.get("valid") else 403
    return payload, status
