"""Portal login branding from SystemSettings singleton."""

import base64
from pathlib import Path

from django.conf import settings

DEFAULT_UNIVERSITY_NAME = "NDEJJE UNIVERSITY STEWARD"
DEFAULT_ERP_FRONTEND_URL = "https://erp.ndejje.ndu.ac.ug"


def get_erp_frontend_url() -> str:
    """Public student/staff ERP URL for emails and links (no trailing slash)."""
    url = (getattr(settings, "ERP_FRONTEND_URL", "") or "").strip().rstrip("/")
    if url:
        return url
    return DEFAULT_ERP_FRONTEND_URL


def get_university_display_name() -> str:
    """Configured portal name from System Settings (singleton)."""
    try:
        from accounts.models import SystemSettings

        name = (SystemSettings.get_settings().university_name or "").strip()
        if name:
            return name
    except Exception:
        pass
    return DEFAULT_UNIVERSITY_NAME


def get_offer_letter_footer_name() -> str:
    """Lowercase system name for offer-letter PDF footers."""
    return get_university_display_name().lower()


def email_branding_context() -> dict:
    """Inject into all transactional / report email templates."""
    name = get_university_display_name()
    return {
        "university_name": name,
        "portal_name": name,
        "system_name": name,
        "portal_url": get_erp_frontend_url(),
    }


def _media_absolute_url(request, file_field) -> str | None:
    if not file_field or not getattr(file_field, "name", None):
        return None
    try:
        url = file_field.url
        if request is not None:
            return request.build_absolute_uri(url)
        return url
    except Exception:
        return None


def _image_mime_for_path(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in (".jpg", ".jpeg"):
        return "jpeg"
    if ext == ".webp":
        return "webp"
    return "png"


def _encode_image_file(path: Path) -> str:
    mime = _image_mime_for_path(path)
    with path.open("rb") as fh:
        encoded = base64.b64encode(fh.read()).decode("ascii")
    return f"data:image/{mime};base64,{encoded}"


def _read_portal_logo_bytes() -> bytes | None:
    try:
        from accounts.models import SystemSettings

        settings_obj = SystemSettings.get_settings()
        logo = getattr(settings_obj, "portal_logo", None)
        if logo and getattr(logo, "name", None):
            with logo.open("rb") as fh:
                return fh.read()
    except Exception:
        pass

    backend_root = Path(settings.BASE_DIR)
    workspace_root = backend_root.parent
    candidates = [
        workspace_root / "NDU-HORIZON" / "public" / "Ndejje_University_Logo.png",
        workspace_root / "NDU-HORIZON" / "public" / "Ndejje_University_Logo.jpg",
        workspace_root / "NDU_Admission_Frontend" / "public" / "Ndejje_University_Logo.png",
        workspace_root / "NDU_Admission_Frontend" / "public" / "Ndejje_University_Logo.jpg",
        backend_root / "static" / "Ndejje_University_Logo.png",
        backend_root / "static" / "Ndejje_University_Logo.jpg",
        backend_root / "static" / "ndejje_logo.png",
        backend_root / "static" / "ndejje_logo.jpg",
    ]
    for path in candidates:
        if path.is_file():
            return path.read_bytes()
    return None


def load_portal_logo_b64_for_pdf() -> str:
    """Raw base64 PNG for xhtml2pdf `<img src=\"data:image/png;base64,...\">`."""
    raw = _read_portal_logo_bytes()
    if not raw:
        return ""
    try:
        from io import BytesIO

        from PIL import Image

        img = Image.open(BytesIO(raw))
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")
        # Keep crest readable in PDFs without exploding PDF size.
        img.thumbnail((420, 420))
        out = BytesIO()
        img.save(out, format="PNG")
        return base64.b64encode(out.getvalue()).decode("ascii")
    except Exception:
        return base64.b64encode(raw).decode("ascii")


def load_portal_logo_data_uri() -> str:
    """Full data URI for HTML `<img src=\"...\">` in browsers."""
    raw = load_portal_logo_b64_for_pdf()
    if not raw:
        return ""
    return f"data:image/png;base64,{raw}"


def xhtml2pdf_link_callback(uri, rel=None):
    """
    Resolve relative URIs for xhtml2pdf WITHOUT wiping data:image logos.

    A callback that always returns BASE_DIR breaks embedded base64 images
    (timetable / exam PDFs would print with blank logo).
    """
    if not uri:
        return uri
    if str(uri).startswith(("data:", "http://", "https://", "file:")):
        return uri
    backend_root = Path(settings.BASE_DIR)
    candidate = Path(uri)
    if not candidate.is_absolute():
        candidate = backend_root / uri.lstrip("/\\")
    if candidate.is_file():
        return candidate.as_uri()
    return str(backend_root.as_uri()) + "/"


def portal_branding_payload(settings_obj, request=None) -> dict:
    name = (getattr(settings_obj, "university_name", None) or "").strip()
    try:
        portal_logo = getattr(settings_obj, "portal_logo", None)
        login_cover = getattr(settings_obj, "login_cover_image", None)
    except Exception:
        portal_logo = None
        login_cover = None
    return {
        "university_name": name or DEFAULT_UNIVERSITY_NAME,
        "portal_logo_url": _media_absolute_url(request, portal_logo),
        "login_cover_url": _media_absolute_url(request, login_cover),
    }
