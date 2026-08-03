"""Hostel eligibility: FY Main Campus requires Accounts + AR docs clearance."""
from __future__ import annotations

from admissions.models import AdmittedStudent
from admissions.registration_workflow import (
    requires_physical_document_verification,
    student_curriculum_year_term,
)


def _normalize_gender(raw: str | None) -> str | None:
    if not raw:
        return None
    g = str(raw).strip().lower()
    if g in ("m", "male", "man", "boy"):
        return "male"
    if g in ("f", "female", "woman", "girl"):
        return "female"
    return g or None


def student_gender(student: AdmittedStudent) -> str | None:
    app = getattr(student, "application", None)
    return _normalize_gender(getattr(app, "gender", None) if app else None)


def is_main_campus(student: AdmittedStudent) -> bool:
    campus = getattr(student, "admitted_campus", None)
    if not campus:
        return False
    code = (getattr(campus, "code", None) or "").strip().upper()
    name = (getattr(campus, "name", None) or "").strip().lower()
    if code in ("MAIN", "MAINCAMPUS", "NDU-MAIN"):
        return True
    if "main" in name or "ndejje" in name:
        return True
    return False


def is_first_year_first_term(student: AdmittedStudent) -> bool:
    year, term = student_curriculum_year_term(student)
    return year == 1 and term == 1


def student_hostel_eligibility(student: AdmittedStudent) -> dict:
    """
    Returns {ok: bool, reasons: list[str], meta: dict}.

    FY Main Campus (Y1T1): require Accounts clearance AND AR document verification.
    Continuing / other: require Accounts registration clearance.
    """
    reasons: list[str] = []
    accounts_ok = bool(getattr(student, "accounts_registration_cleared", False))
    docs_ok = bool(getattr(student, "physical_documents_verified", False))
    gender = student_gender(student)
    main = is_main_campus(student)
    fy = is_first_year_first_term(student)
    needs_docs = requires_physical_document_verification(student)

    if not gender:
        reasons.append("Student gender is missing on the application.")

    if not accounts_ok:
        reasons.append("Accounts registration clearance is required before hostel assignment.")

    if main and fy and needs_docs and not docs_ok:
        reasons.append(
            "AR document verification is required for first-year Main Campus hostel assignment."
        )

    return {
        "ok": len(reasons) == 0,
        "reasons": reasons,
        "meta": {
            "accounts_registration_cleared": accounts_ok,
            "physical_documents_verified": docs_ok,
            "is_main_campus": main,
            "is_first_year_first_term": fy,
            "requires_ar_docs": bool(main and fy and needs_docs),
            "gender": gender,
            "year_term": list(student_curriculum_year_term(student)),
        },
    }
