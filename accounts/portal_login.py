"""Portal-scoped login rules (admissions vs ERP)."""
from __future__ import annotations

from rest_framework import exceptions

from accounts.portal_branding import DEFAULT_ERP_FRONTEND_URL, get_erp_frontend_url

ADMISSIONS_PORTAL_KINDS = frozenset({"admissions", "applicant", "application"})
ERP_PORTAL_KINDS = frozenset({"erp", "horizon", "staff", "admin", "student", "lecturer"})


def normalize_portal_kind(raw: str | None) -> str | None:
    kind = (raw or "").strip().lower()
    if not kind:
        return None
    if kind in ADMISSIONS_PORTAL_KINDS:
        return "admissions"
    if kind in ERP_PORTAL_KINDS:
        return "erp"
    return kind


def user_is_erp_account(user) -> bool:
    return bool(
        getattr(user, "is_staff", False)
        or getattr(user, "is_student", False)
        or getattr(user, "is_lecturer", False)
        or getattr(user, "is_superuser", False)
    )


def user_is_applicant_only(user) -> bool:
    return bool(getattr(user, "is_applicant", False)) and not user_is_erp_account(user)


def assert_user_allowed_on_portal(user, portal_kind: str | None) -> None:
    """
    Enforce portal split:
    - admissions → applicants only
    - erp → staff / students / lecturers only
    """
    kind = normalize_portal_kind(portal_kind)
    if kind is None:
        return

    erp_url = DEFAULT_ERP_FRONTEND_URL.rstrip("/")
    # Prefer configured URL when it is already the public Steward host.
    configured = (get_erp_frontend_url() or "").rstrip("/")
    if configured and "erp.ndejje.ndu.ac.ug" in configured:
        erp_url = configured

    if kind == "admissions":
        if user_is_erp_account(user):
            raise exceptions.AuthenticationFailed(
                f"Staff and student accounts use the main university ERP. "
                f"Sign in at {erp_url}/"
            )
        return

    if kind == "erp":
        if not user_is_erp_account(user):
            raise exceptions.AuthenticationFailed(
                "Applicant accounts use the admissions portal, not the ERP."
            )
        return
