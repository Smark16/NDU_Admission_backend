"""Default merge-field boxes for the Ndejje CR80 student ID artwork."""

from __future__ import annotations

import fitz

# Physical card is ~86.4 x 55.4 mm. Boxes sit in the blank area under the crest
# and university name so print pulls live student data from the portal.
# Labels sit on the same line as values so type can stay large enough to read.
_TEXT = {
    "inline": True,
    "bold": True,
    "font_family": "helvetica",
    "page": 0,
}

NDEJJE_CR80_STUDENT_FIELD_POSITIONS = {
    "passport_photo": {"x": 10, "y": 48, "page": 0, "width": 52, "height": 72},
    "name": {
        **_TEXT,
        "x": 68,
        "y": 42,
        "font_size": 10,
        "caption_size": 8,
        "width": 118,
        "caption": "Name",
    },
    "student_id": {
        **_TEXT,
        "x": 68,
        "y": 58,
        "font_size": 8.5,
        "caption_size": 8,
        "width": 118,
        "caption": "Student ID",
    },
    "reg_no": {
        **_TEXT,
        "x": 68,
        "y": 72,
        "font_size": 8.5,
        "caption_size": 8,
        "width": 118,
        "caption": "Reg No.",
    },
    "course": {
        "x": 68,
        "y": 82,
        "page": 0,
        "font_size": 7.5,
        "caption_size": 7.5,
        "bold": False,
        "font_family": "helvetica",
        "inline": False,
        "width": 118,
        "height": 22,
        "caption": "Course",
    },
    "gender": {
        **_TEXT,
        "x": 68,
        "y": 112,
        "font_size": 8,
        "caption_size": 8,
        "width": 52,
        "caption": "Gender",
    },
    "expiry_date": {
        **_TEXT,
        "x": 122,
        "y": 112,
        "font_size": 8,
        "caption_size": 8,
        "width": 60,
        "caption": "Expiry",
    },
    "card_number": {
        **_TEXT,
        "x": 68,
        "y": 124,
        "font_size": 8.5,
        "caption_size": 8,
        "width": 114,
        "caption": "Card No.",
    },
    # ~18.3 mm — short student-number payload.
    "qr_code": {"x": 188, "y": 88, "page": 0, "width": 52, "height": 52},
}

NDEJJE_STUDENT_ID_TEMPLATE_KEY = "ndu-student-id-cr80"
NDEJJE_STUDENT_ID_TEMPLATE_NAME = "Ndejje student ID (physical card)"


def pdf_is_cr80_id_card(width: float, height: float) -> bool:
    return 230 <= width <= 265 and 145 <= height <= 175


def default_field_positions_for_pdf(pdf_path: str) -> dict:
    """Return mapped boxes when the uploaded PDF matches the CR80 student card."""
    doc = fitz.open(pdf_path)
    try:
        page = doc[0]
        width, height = page.rect.width, page.rect.height
    finally:
        doc.close()
    if not pdf_is_cr80_id_card(width, height):
        return {}
    return {k: dict(v) for k, v in NDEJJE_CR80_STUDENT_FIELD_POSITIONS.items()}
