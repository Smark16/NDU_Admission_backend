"""Portal-scoped login rules (admissions vs ERP)."""
from __future__ import annotations

from urllib.parse import urlparse

from rest_framework import exceptions

from accounts.portal_branding import DEFAULT_ERP_FRONTEND_URL, get_erp_frontend_url

ADMISSIONS_PORTAL_KINDS = frozenset({"admissions", "applicant", "application"})
ERP_PORTAL_KINDS = frozenset({"erp", "horizon", "staff", "admin", "student", "lecturer"})

# Hostnames that must only serve applicants (even if login body omits portal=).
ADMISSIONS_HOST_MARKERS = (
    "admissions.ndu.ac.ug",
    "applications.ndu.ac.ug",  # legacy applicant site hostname
)

ERP_HOST_MARKERS = (
    "erp.ndejje.ndu.ac.ug",
    "applications-admin.ndu.ac.ug",
)


def normalize_portal_kind(raw: str | None) -> str | None:
    kind = (raw or "").strip().lower()
    if not kind:
        return None
    if kind in ADMISSIONS_PORTAL_KINDS:
        return "admissions"
    if kind in ERP_PORTAL_KINDS:
        return "erp"
    return kind


def _host_from_url(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    try:
        return (urlparse(raw).hostname or "").lower()
    except Exception:
        return ""


def infer_portal_kind_from_request(request) -> str | None:
    """Infer admissions vs ERP from Origin / Referer when body omits portal."""
    if request is None:
        return None
    origin = request.headers.get("Origin") or ""
    referer = request.headers.get("Referer") or ""
    host = _host_from_url(origin) or _host_from_url(referer)
    if not host:
        return None
    if any(host == m or host.endswith("." + m) for m in ADMISSIONS_HOST_MARKERS):
        return "admissions"
    if any(host == m or host.endswith("." + m) for m in ERP_HOST_MARKERS):
        return "erp"
    return None


def resolve_portal_kind(request=None, portal_kind: str | None = None) -> str | None:
    explicit = normalize_portal_kind(portal_kind)
    if explicit:
        return explicit
    return infer_portal_kind_from_request(request)


def user_is_erp_account(user) -> bool:
    return bool(
        getattr(user, "is_staff", False)
        or getattr(user, "is_student", False)
        or getattr(user, "is_lecturer", False)
        or getattr(user, "is_superuser", False)
    )


def staff_erp_login_url() -> str:
    erp_url = DEFAULT_ERP_FRONTEND_URL.rstrip("/")
    configured = (get_erp_frontend_url() or "").rstrip("/")
    if configured and "erp.ndejje.ndu.ac.ug" in configured:
        erp_url = configured
    return erp_url


def assert_user_allowed_on_portal(
    user, portal_kind: str | None = None, *, request=None
) -> None:
    """
    Enforce portal split:
    - admissions → applicants only
    - erp → staff / students / lecturers only

    Portal kind comes from body/header, or is inferred from Origin/Referer
    so older admissions frontends still cannot log staff in.
    """
    kind = resolve_portal_kind(request, portal_kind)
    if kind is None:
        return

    erp_url = staff_erp_login_url()

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


def assert_session_allowed_on_portal(user, request) -> None:
    """Block ERP accounts from using sessions issued against the admissions site."""
    kind = resolve_portal_kind(request, None)
    if kind != "admissions":
        return
    if user_is_erp_account(user):
        raise exceptions.PermissionDenied(
            f"Staff and student accounts use the main university ERP. "
            f"Sign in at {staff_erp_login_url()}/"
        )
