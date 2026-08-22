"""Render student ID cards from active PDF template + mapped field positions."""

from __future__ import annotations

import base64
import io
import logging
import os
import platform
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path

import fitz

from django.db.utils import OperationalError, ProgrammingError

from accounts.models import SystemSettings

from .models import IdCardPdfTemplate, StudentIdCard

logger = logging.getLogger(__name__)

IMAGE_FIELD_KEYS = frozenset({"passport_photo", "qr_code"})
DEFAULT_PHOTO_WIDTH = 85.0
DEFAULT_PHOTO_HEIGHT = 105.0
DEFAULT_QR_SIZE = 70.0


def _add_years_and_months(start: date, *, years: int = 0, months: int = 0) -> date:
    total_months = start.month - 1 + (years * 12) + months
    year = start.year + total_months // 12
    month = total_months % 12 + 1
    day = min(start.day, monthrange(year, month)[1])
    return date(year, month, day)


def _default_expiry(issue: date, *, years: int | None = None) -> date:
    """Issue date + programme min years + 6 months grace."""
    n = int(years) if years is not None else 4
    if n < 1:
        n = 4
    return _add_years_and_months(issue, years=n, months=6)


def _programme_min_years(admitted) -> int:
    program = getattr(admitted, "admitted_program", None) if admitted else None
    raw = getattr(program, "min_years", None) if program else None
    try:
        years = int(raw)
    except (TypeError, ValueError):
        years = 0
    return years if years >= 1 else 4


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


def _active_id_card_template_key(audience: str = "student") -> str:
    """Read the active template key without loading every SystemSettings column."""
    field = "active_staff_id_card_template" if audience == "staff" else "active_id_card_template"
    from django.db import connection

    try:
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT {field} FROM accounts_systemsettings WHERE id = 1")
            row = cursor.fetchone()
        return (str(row[0]).strip() if row and row[0] else "")
    except (OperationalError, ProgrammingError):
        if audience == "staff":
            return ""
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT active_id_card_template FROM accounts_systemsettings WHERE id = 1")
                row = cursor.fetchone()
            return (str(row[0]).strip() if row and row[0] else "")
        except (OperationalError, ProgrammingError):
            return ""


def _pdf_template_row_for_key(key: str) -> IdCardPdfTemplate | None:
    row = IdCardPdfTemplate.objects.filter(key=key).first()
    if row is None or not row.template_pdf or not (row.template_pdf.name or "").strip():
        return None
    return row


def resolve_active_pdf_template(audience: str = "student") -> IdCardPdfTemplate | None:
    """Active IdCardPdfTemplate with PDF file and at least one mapped field."""
    active_key = _active_id_card_template_key(audience)
    if not active_key:
        return None

    row = _pdf_template_row_for_key(active_key)
    if row is None or not row.field_positions:
        return None
    if (getattr(row, "audience", "student") or "student") != audience:
        return None
    return row


def maybe_auto_activate_id_card_template(key: str) -> bool:
    """Set active template when none is configured or the current key is invalid."""
    key = (key or "").strip()
    row = _pdf_template_row_for_key(key)
    if not key or row is None:
        return False

    audience = getattr(row, "audience", "student") or "student"
    if audience == "staff":
        active_key = _active_id_card_template_key("staff")
        if active_key and _pdf_template_row_for_key(active_key) is not None:
            return False
        try:
            return bool(
                SystemSettings.objects.filter(pk=1).update(active_staff_id_card_template=key)
            )
        except (OperationalError, ProgrammingError):
            return False

    active_key = _active_id_card_template_key("student")
    if active_key and _pdf_template_row_for_key(active_key) is not None:
        return False
    return bool(SystemSettings.objects.filter(pk=1).update(active_id_card_template=key))


def explain_pdf_render_blocker(audience: str = "student") -> str | None:
    """Human-readable reason preview/print still uses the built-in layout."""
    qs = IdCardPdfTemplate.objects.filter(template_pdf__isnull=False).exclude(template_pdf="")
    if audience in ("student", "staff"):
        qs = qs.filter(audience=audience)
    if not qs.exists():
        return None

    active_key = _active_id_card_template_key(audience)
    kind = "staff" if audience == "staff" else "student"
    if not active_key:
        return (
            f"A {kind} PDF template is uploaded but none is set as active. "
            "Open ID card templates and click the star on your template."
        )

    row = _pdf_template_row_for_key(active_key)
    if row is None:
        return (
            f"The active {kind} template key “{active_key}” does not match any uploaded PDF. "
            "Click the star on the template you want to use."
        )
    if not row.field_positions:
        return "The active PDF template has no mapped fields yet. Use Map fields and save positions."
    return None


def _card_date(value: date | None) -> str:
    if not value:
        return ""
    return value.strftime("%d/%m/%Y")


def build_id_card_field_context(card: StudentIdCard) -> dict[str, str]:
    issue = card.issue_date or date.today()
    if card.admitted_student_id:
        st = card.admitted_student
        app = st.application
        expiry = _default_expiry(issue, years=_programme_min_years(st))
        program = st.admitted_program
        faculty = getattr(program, "faculty", None) if program else None
        department = getattr(program, "department", None) if program else None
        batch = st.admitted_batch
        return {
            "name": st.full_name or "",
            "title": ((getattr(app, "title", None) or "").strip() if app else ""),
            "student_no": (st.student_id or "").strip(),
            "student_id": (st.student_id or "").strip(),
            "reg_no": (st.reg_no or "").strip(),
            "course": program.name if program else "",
            "course_code": (program.code or "").strip() if program else "",
            "faculty": faculty.name if faculty else "",
            "department": department.name if department else "",
            "campus": st.admitted_campus.name if st.admitted_campus_id else "",
            "academic_batch": batch.name if batch else "",
            "academic_year": (getattr(batch, "academic_year", None) or "").strip() if batch else "",
            "study_mode": (st.study_mode or "").strip(),
            "gender": (app.gender or "").strip() if app else "",
            "nationality": (app.nationality or "").strip() if app else "",
            "date_of_birth": _card_date(getattr(app, "date_of_birth", None) if app else None),
            "phone": (app.phone or "").strip() if app else "",
            "issue_date": _card_date(issue),
            "expiry_date": _card_date(expiry),
            "card_number": card.card_number or "",
        }

    years = int(card.walk_in_validity_years or 4)
    if years < 1:
        years = 4
    expiry = _default_expiry(issue, years=years)
    return {
        "name": (card.walk_in_full_name or "").strip(),
        "title": "",
        "student_no": (card.walk_in_student_no or "").strip(),
        "student_id": (card.walk_in_student_no or "").strip(),
        "reg_no": (card.walk_in_reg_no or "").strip(),
        "course": (card.walk_in_programme or "").strip(),
        "course_code": "",
        "faculty": "",
        "department": "",
        "campus": (card.walk_in_campus or "").strip(),
        "academic_batch": "",
        "academic_year": "",
        "study_mode": "",
        "gender": (card.walk_in_gender or "").strip(),
        "nationality": "",
        "date_of_birth": "",
        "phone": "",
        "issue_date": _card_date(issue),
        "expiry_date": _card_date(expiry),
        "card_number": card.card_number or "",
    }


def _passport_photo_path(card: StudentIdCard) -> str | None:
    if card.admitted_student_id:
        from admissions.student_photo import admitted_student_photo_file

        photo = admitted_student_photo_file(card.admitted_student)
        if not photo:
            return None
        try:
            path = photo.path
        except (ValueError, AttributeError):
            return None
        if path and os.path.isfile(path):
            return path
        return None

    photo = card.walk_in_photo
    if not photo:
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
    The scan desk accepts this value and still resolves the student when on file.
    """
    if card.admitted_student_id:
        st = card.admitted_student
        lookup = (st.student_id or st.reg_no or "").strip()
        if not lookup:
            lookup = str(st.pk)
        return lookup
    lookup = (card.walk_in_student_no or card.walk_in_reg_no or card.card_number or "").strip()
    return lookup or str(card.pk)


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
            box_size=10,
            border=2,
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


def _wrap_text_lines(text: str, width: float, fontsize: float, fontname: str) -> list[str]:
    text = " ".join((text or "").split())
    if not text:
        return []
    if width <= 8:
        return [text]
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if fitz.get_text_length(trial, fontname=fontname, fontsize=fontsize) <= width:
            current = trial
            continue
        if current:
            lines.append(current)
        if fitz.get_text_length(word, fontname=fontname, fontsize=fontsize) <= width:
            current = word
            continue
        chunk = ""
        for char in word:
            next_chunk = chunk + char
            if fitz.get_text_length(next_chunk, fontname=fontname, fontsize=fontsize) <= width:
                chunk = next_chunk
            else:
                if chunk:
                    lines.append(chunk)
                chunk = char
        current = chunk
    if current:
        lines.append(current)
    return lines or [text]


def _draw_wrapped_text(
    page,
    rect: fitz.Rect,
    text: str,
    fontsize: float,
    font_kwargs: dict,
    color=(0, 0, 0),
    *,
    single_line: bool = False,
) -> None:
    fontname = font_kwargs.get("fontname") or "helv"
    extra = {key: val for key, val in font_kwargs.items() if key != "fontname"}
    width = max(8.0, float(rect.width))
    height = max(fontsize, float(rect.height))
    size = float(fontsize)
    if single_line:
        while size >= 5.0 and fitz.get_text_length(text, fontname=fontname, fontsize=size) > width:
            size -= 0.3
        try:
            page.insert_text(
                fitz.Point(rect.x0, min(rect.y1 - 1, rect.y0 + size)),
                text,
                fontsize=size,
                color=color,
                fontname=fontname,
                **extra,
            )
        except Exception:
            page.insert_text(fitz.Point(rect.x0, rect.y0 + size), text, fontsize=size, color=color, fontname="helv")
        return
    lines: list[str] = []
    while size >= 5.0:
        lines = _wrap_text_lines(text, width, size, fontname)
        if not lines:
            return
        if len(lines) * size * 1.18 <= height + 0.8:
            break
        size -= 0.4
    y = rect.y0 + size
    for line in lines:
        if y > rect.y1 + 1.5:
            break
        try:
            page.insert_text(
                fitz.Point(rect.x0, y),
                line,
                fontsize=size,
                color=color,
                fontname=fontname,
                **extra,
            )
        except Exception:
            page.insert_text(fitz.Point(rect.x0, y), line, fontsize=size, color=color, fontname="helv")
        y += size * 1.18


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
        if field_name == "name":
            title = str(context.get("title") or "").strip()
            if title and value and not value.lower().startswith(title.lower()):
                value = f"{title} {value}".strip()
        if not value:
            continue
        x = float(pos.get("x", 0))
        y = float(pos.get("y", 0))
        font_size = float(pos.get("font_size", 11))
        font_kwargs = _resolve_font(pos)
        max_w = float(pos.get("width") or 0)
        if max_w <= 0:
            max_w = max(40.0, page.rect.width - x - 8)
        caption = str(pos.get("caption") or "").strip()
        cap_size = float(pos.get("caption_size") or max(7.0, font_size - 1.0))
        inline = bool(pos.get("inline", False))
        label_color = (0, 0, 0.502)  # Ndejje navy #000080
        if caption and inline:
            label = caption if caption.endswith(":") else f"{caption}:"
            baseline = y + cap_size
            try:
                page.insert_text(
                    fitz.Point(x, baseline),
                    label,
                    fontsize=cap_size,
                    color=label_color,
                    fontname="helv",
                )
            except Exception:
                logger.exception("Failed to draw caption %s on ID card PDF", caption)
            label_w = fitz.get_text_length(label + "  ", fontname="helv", fontsize=cap_size)
            value_height = float(pos.get("height") or max(font_size, cap_size) * 1.45)
            rect = fitz.Rect(x + label_w, y, x + max_w, y + value_height)
        elif caption:
            try:
                page.insert_text(
                    fitz.Point(x, y + cap_size),
                    caption,
                    fontsize=cap_size,
                    color=label_color,
                    fontname="helv",
                )
            except Exception:
                logger.exception("Failed to draw caption %s on ID card PDF", caption)
            value_top = y + cap_size + 1.2
            value_height = float(pos.get("height") or font_size * 3.4)
            rect = fitz.Rect(x, value_top, x + max_w, value_top + value_height)
        else:
            value_top = max(0, y - font_size)
            value_height = float(pos.get("height") or font_size * 3.2)
            rect = fitz.Rect(x, value_top, x + max_w, value_top + value_height)
        if rect.x1 - rect.x0 < 10:
            rect = fitz.Rect(x, rect.y0, x + max_w, rect.y1)
        _draw_wrapped_text(
            page,
            rect,
            value,
            font_size,
            font_kwargs,
            single_line=bool(pos.get("single_line", False)),
        )

    pdf_bytes = doc.write()
    doc.close()
    return pdf_bytes


def _with_cr80_course_box(pdf_path: str, positions: dict) -> dict:
    """Use the current CR80 field map so name, expiry, and card number stay in place."""
    from .id_card_default_layout import NDEJJE_CR80_STUDENT_FIELD_POSITIONS, pdf_is_cr80_id_card

    try:
        doc = fitz.open(pdf_path)
        width, height = doc[0].rect.width, doc[0].rect.height
        doc.close()
    except Exception:
        return dict(positions or {})
    if not pdf_is_cr80_id_card(width, height):
        return dict(positions or {})
    return {key: dict(value) for key, value in NDEJJE_CR80_STUDENT_FIELD_POSITIONS.items()}


def render_id_card_pdf(card: StudentIdCard) -> bytes | None:
    """Return merged PDF bytes, or None when no usable active template is configured."""
    template = resolve_active_pdf_template("student")
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

    card.ensure_card_number()
    context = build_id_card_field_context(card)
    image_paths: dict[str, str] = {}
    image_streams: dict[str, bytes] = {}
    photo_path = _passport_photo_path(card)
    positions = _with_cr80_course_box(pdf_path, template.field_positions or {})
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


def _staff_photo_path(profile) -> str | None:
    photo = getattr(profile, "passport_photo", None)
    if not photo:
        return None
    try:
        path = photo.path
    except (ValueError, AttributeError):
        return None
    if path and os.path.isfile(path):
        return path
    return None


def build_staff_id_card_field_context(card) -> dict[str, str]:
    st = card.staff_profile
    issue = card.issue_date or date.today()
    expiry = card.expiry_date or _default_expiry(issue)
    campus_names = list(st.campus.order_by("name").values_list("name", flat=True)[:3])
    return {
        "name": st.get_full_name or "",
        "staff_no": (st.staff_no or "").strip(),
        "job_title": (st.job_title or "").strip(),
        "department": st.org_unit.name if st.org_unit_id else "",
        "campus": ", ".join(campus_names),
        "staff_type": st.staff_type.name if st.staff_type_id else "",
        "expiry_date": _card_date(expiry),
        "card_number": card.card_number or "",
    }


def build_staff_id_card_qr_payload(card) -> str:
    st = card.staff_profile
    lookup = (st.staff_no or "").strip()
    if not lookup:
        lookup = str(st.pk)
    return lookup


def render_staff_id_card_pdf(card) -> bytes | None:
    """Merged staff ID PDF, or None when no usable staff template is configured."""
    template = resolve_active_pdf_template("staff")
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

    context = build_staff_id_card_field_context(card)
    image_paths: dict[str, str] = {}
    image_streams: dict[str, bytes] = {}
    photo_path = _staff_photo_path(card.staff_profile)
    positions = template.field_positions or {}
    if photo_path and "passport_photo" in positions:
        image_paths["passport_photo"] = photo_path
    if "qr_code" in positions:
        qr_bytes = _qr_png_bytes(build_staff_id_card_qr_payload(card))
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
