"""Render student ID cards from active PDF template + mapped field positions."""

from __future__ import annotations

import base64
import logging
import os
import platform
from datetime import date, timedelta
from pathlib import Path

import fitz

from accounts.models import SystemSettings

from .models import IdCardPdfTemplate, StudentIdCard

logger = logging.getLogger(__name__)

IMAGE_FIELD_KEYS = frozenset({"passport_photo"})
DEFAULT_PHOTO_WIDTH = 85.0
DEFAULT_PHOTO_HEIGHT = 105.0


def _default_expiry(issue: date) -> date:
    return issue + timedelta(days=365 * 4)


def _resolve_font(pos: dict) -> dict:
    bold = bool(pos.get("bold", False))
    font_family = str(pos.get("font_family", "helvetica")).strip().lower()

    if font_family in ("helvetica", "arial", ""):
        return {"fontname": "hebo" if bold else "helv"}
    if font_family in ("times", "times new roman"):
        return {"fontname": "tibo" if bold else "tiro"}
    if font_family in ("courier", "courier new"):
        return {"fontname": "cobo" if bold else "cour"}

    if font_family == "century":
        candidates = []
        if platform.system() == "Windows":
            win_fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
            candidates = [
                win_fonts / "CENTURY.TTF",
                win_fonts / "CENTURYB.TTF",
                win_fonts / "GOTHIC.TTF",
                win_fonts / "GOTHICB.TTF",
            ]
        else:
            candidates = [
                Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
            ]
        for font_path in candidates:
            if font_path.exists():
                return {"fontname": f"font_{font_family}", "fontfile": str(font_path)}
        return {"fontname": "tibo" if bold else "tiro"}

    return {"fontname": "hebo" if bold else "helv"}


def _pdf_template_row_for_key(key: str) -> IdCardPdfTemplate | None:
    row = IdCardPdfTemplate.objects.filter(key=key).first()
    if row is None or not row.template_pdf or not (row.template_pdf.name or "").strip():
        return None
    return row


def resolve_active_pdf_template() -> IdCardPdfTemplate | None:
    """Active IdCardPdfTemplate with PDF file and at least one mapped field."""
    settings_obj = SystemSettings.get_settings()
    active_key = (getattr(settings_obj, "active_id_card_template", None) or "").strip()
    if not active_key:
        return None

    row = _pdf_template_row_for_key(active_key)
    if row is None or not row.field_positions:
        return None
    return row


def maybe_auto_activate_id_card_template(key: str) -> bool:
    """Set active template when none is configured or the current key is invalid."""
    key = (key or "").strip()
    if not key or _pdf_template_row_for_key(key) is None:
        return False

    settings_obj = SystemSettings.get_settings()
    active_key = (getattr(settings_obj, "active_id_card_template", None) or "").strip()
    if active_key and _pdf_template_row_for_key(active_key) is not None:
        return False

    settings_obj.active_id_card_template = key
    settings_obj.save(update_fields=["active_id_card_template", "updated_at"])
    return True


def explain_pdf_render_blocker() -> str | None:
    """Human-readable reason preview/print still uses the built-in layout."""
    if not IdCardPdfTemplate.objects.filter(template_pdf__isnull=False).exclude(template_pdf="").exists():
        return None

    settings_obj = SystemSettings.get_settings()
    active_key = (getattr(settings_obj, "active_id_card_template", None) or "").strip()
    if not active_key:
        return (
            "A PDF template is uploaded but none is set as active. "
            "Open ID card templates and click the star on your template."
        )

    row = _pdf_template_row_for_key(active_key)
    if row is None:
        return (
            f"The active template key “{active_key}” does not match any uploaded PDF. "
            "Click the star on the template you want to use."
        )
    if not row.field_positions:
        return "The active PDF template has no mapped fields yet. Use Map fields and save positions."
    return None


def build_id_card_field_context(card: StudentIdCard) -> dict[str, str]:
    st = card.admitted_student
    app = st.application
    issue = card.issue_date or date.today()
    expiry = card.expiry_date or _default_expiry(issue)
    return {
        "name": st.full_name or "",
        "student_no": (st.student_id or "").strip(),
        "reg_no": (st.reg_no or "").strip(),
        "course": st.admitted_program.name if st.admitted_program_id else "",
        "gender": (app.gender or "").strip() if app else "",
        "expiry_date": expiry.isoformat(),
        "card_number": card.card_number or "",
    }


def _passport_photo_path(card: StudentIdCard) -> str | None:
    app = card.admitted_student.application
    photo = getattr(app, "passport_photo", None)
    if not photo or not getattr(photo, "name", None):
        return None
    try:
        path = photo.path
    except (ValueError, AttributeError):
        return None
    if path and os.path.isfile(path):
        return path
    return None


def fill_id_card_pdf_template(
    template_path: str,
    context: dict[str, str],
    field_positions: dict,
    *,
    image_paths: dict[str, str] | None = None,
) -> bytes:
    """Overlay mapped text and optional images onto the PDF template."""
    doc = fitz.open(template_path)
    image_paths = image_paths or {}

    for field_name, pos in (field_positions or {}).items():
        if not isinstance(pos, dict):
            continue
        page_num = int(pos.get("page", 0))
        if page_num >= len(doc):
            continue
        page = doc[page_num]

        if field_name in IMAGE_FIELD_KEYS:
            img_path = image_paths.get(field_name)
            if not img_path:
                continue
            x = float(pos.get("x", 0))
            y = float(pos.get("y", 0))
            width = float(pos.get("width") or DEFAULT_PHOTO_WIDTH)
            height = float(pos.get("height") or DEFAULT_PHOTO_HEIGHT)
            rect = fitz.Rect(x, y, x + width, y + height)
            try:
                page.insert_image(rect, filename=img_path, keep_proportion=True)
            except Exception:
                logger.exception("Failed to insert passport photo on ID card PDF")
            continue

        value = str(context.get(field_name, "") or "")
        if not value:
            continue
        x = float(pos.get("x", 0))
        y = float(pos.get("y", 0))
        font_size = float(pos.get("font_size", 11))
        font_kwargs = _resolve_font(pos)
        page.insert_text(
            fitz.Point(x, y),
            value,
            fontsize=font_size,
            color=(0, 0, 0),
            **font_kwargs,
        )

    pdf_bytes = doc.write()
    doc.close()
    return pdf_bytes


def render_id_card_pdf(card: StudentIdCard) -> bytes | None:
    """Return merged PDF bytes, or None when no usable active template is configured."""
    template = resolve_active_pdf_template()
    if template is None:
        return None

    ext = os.path.splitext(template.template_pdf.name or "")[1].lower()
    if ext != ".pdf":
        return None

    try:
        pdf_path = template.template_pdf.path
    except ValueError:
        return None
    if not os.path.isfile(pdf_path):
        return None

    context = build_id_card_field_context(card)
    image_paths: dict[str, str] = {}
    photo_path = _passport_photo_path(card)
    positions = template.field_positions or {}
    if photo_path and "passport_photo" in positions:
        image_paths["passport_photo"] = photo_path

    return fill_id_card_pdf_template(pdf_path, context, positions, image_paths=image_paths)


def pdf_first_page_png_base64(pdf_bytes: bytes, *, scale: float = 2.0) -> str:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        page = doc[0]
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
        return base64.b64encode(pix.tobytes("png")).decode()
    finally:
        doc.close()
