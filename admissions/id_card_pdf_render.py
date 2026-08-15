"""Render student ID cards from active PDF template + mapped field positions."""

from __future__ import annotations

import base64
import io
import logging
import os
import platform
from datetime import date, timedelta
from pathlib import Path

import fitz

from accounts.models import SystemSettings

from .models import IdCardPdfTemplate, StudentIdCard

logger = logging.getLogger(__name__)

IMAGE_FIELD_KEYS = frozenset({"passport_photo", "qr_code"})
DEFAULT_PHOTO_WIDTH = 85.0
DEFAULT_PHOTO_HEIGHT = 105.0
DEFAULT_QR_SIZE = 70.0


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


def build_id_card_qr_payload(card: StudentIdCard) -> str:
    """
    Short paycode / student number only — dense URLs on a CR80 QR fail laptop cameras.
    The scan desk accepts this value and still resolves the student.
    """
    st = card.admitted_student
    lookup = (st.student_id or st.reg_no or "").strip()
    if not lookup:
        lookup = str(st.pk)
    return lookup


def _qr_png_bytes(payload: str) -> bytes | None:
    try:
        import qrcode
        from qrcode.constants import ERROR_CORRECT_M
    except ImportError:
        logger.warning("qrcode package not installed; skipping ID card QR")
        return None
    try:
        qr = qrcode.QRCode(
            version=None,
            error_correction=ERROR_CORRECT_M,
            box_size=8,
            border=3,
        )
        qr.add_data(payload)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        logger.exception("Failed to generate ID card QR PNG")
        return None


def fill_id_card_pdf_template(
    template_path: str,
    context: dict[str, str],
    field_positions: dict,
    *,
    image_paths: dict[str, str] | None = None,
    image_streams: dict[str, bytes] | None = None,
) -> bytes:
    """Overlay mapped text and optional images onto the PDF template."""
    doc = fitz.open(template_path)
    image_paths = image_paths or {}
    image_streams = image_streams or {}

    for field_name, pos in (field_positions or {}).items():
        if not isinstance(pos, dict):
            continue
        page_num = int(pos.get("page", 0))
        if page_num >= len(doc):
            continue
        page = doc[page_num]

        if field_name in IMAGE_FIELD_KEYS:
            default_w = DEFAULT_QR_SIZE if field_name == "qr_code" else DEFAULT_PHOTO_WIDTH
            default_h = DEFAULT_QR_SIZE if field_name == "qr_code" else DEFAULT_PHOTO_HEIGHT
            x = float(pos.get("x", 0))
            y = float(pos.get("y", 0))
            width = float(pos.get("width") or default_w)
            height = float(pos.get("height") or default_h)
            rect = fitz.Rect(x, y, x + width, y + height)
            try:
                stream = image_streams.get(field_name)
                if stream:
                    page.insert_image(rect, stream=stream, keep_proportion=True)
                    continue
                img_path = image_paths.get(field_name)
                if not img_path:
                    continue
                page.insert_image(rect, filename=img_path, keep_proportion=True)
            except Exception:
                logger.exception("Failed to insert %s on ID card PDF", field_name)
            continue

        value = str(context.get(field_name, "") or "")
        if not value:
            continue
        x = float(pos.get("x", 0))
        y = float(pos.get("y", 0))
        font_size = float(pos.get("font_size", 11))
        font_kwargs = _resolve_font(pos)
        max_w = float(pos.get("width") or 0)
        if max_w <= 0:
            max_w = max(40.0, page.rect.width - x - 8)
        # insert_text uses a baseline point and overflows long programmes;
        # a box wraps / shrinks to the mapped width.
        rect = fitz.Rect(x, max(0, y - font_size), x + max_w, y + font_size * 2.8)
        try:
            page.insert_textbox(
                rect,
                value,
                fontsize=font_size,
                color=(0, 0, 0),
                align=fitz.TEXT_ALIGN_LEFT,
                **font_kwargs,
            )
        except Exception:
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
    image_streams: dict[str, bytes] = {}
    photo_path = _passport_photo_path(card)
    positions = template.field_positions or {}
    if photo_path and "passport_photo" in positions:
        image_paths["passport_photo"] = photo_path
    if "qr_code" in positions:
        qr_bytes = _qr_png_bytes(build_id_card_qr_payload(card))
        if qr_bytes:
            image_streams["qr_code"] = qr_bytes

    return fill_id_card_pdf_template(
        pdf_path,
        context,
        positions,
        image_paths=image_paths,
        image_streams=image_streams,
    )


def pdf_pages_png_base64(pdf_bytes: bytes, *, scale: float = 2.0) -> list[str]:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        pages = []
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
            pages.append(base64.b64encode(pix.tobytes("png")).decode())
        return pages
    finally:
        doc.close()


def pdf_first_page_png_base64(pdf_bytes: bytes, *, scale: float = 2.0) -> str:
    pages = pdf_pages_png_base64(pdf_bytes, scale=scale)
    return pages[0] if pages else ""
