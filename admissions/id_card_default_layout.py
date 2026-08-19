"""Default merge-field boxes for the Ndejje CR80 student ID artwork."""

from __future__ import annotations

import fitz

# Physical card is ~86.4 x 55.4 mm. Boxes sit in the blank area under the crest
# and university name so print pulls live student data from the portal.
_TEXT = {
    "inline": True,
    "bold": True,
    "font_family": "helvetica",
    "page": 0,
    "height": 11,
}

NDEJJE_CR80_STUDENT_FIELD_POSITIONS = {
    "passport_photo": {"x": 10, "y": 48, "page": 0, "width": 52, "height": 72},
    "name": {
        **_TEXT,
        "x": 66,
        "y": 42,
        "font_size": 8,
        "caption_size": 7.5,
        "width": 120,
        "height": 11,
        "single_line": True,
        "caption": "Name",
    },
    "student_id": {
        **_TEXT,
        "x": 66,
        "y": 54,
        "font_size": 8,
        "caption_size": 7.5,
        "width": 120,
        "caption": "Student ID",
        "single_line": True,
    },
    "reg_no": {
        **_TEXT,
        "x": 66,
        "y": 66,
        "font_size": 8,
        "caption_size": 7.5,
        "width": 120,
        "caption": "Reg No.",
        "single_line": True,
    },
    "course": {
        **_TEXT,
        "x": 66,
        "y": 78,
        "font_size": 7.5,
        "caption_size": 7.5,
        "bold": False,
        "width": 120,
        "height": 20,
        "caption": "Course",
    },
    "gender": {
        **_TEXT,
        "x": 66,
        "y": 100,
        "font_size": 8,
        "caption_size": 7.5,
        "width": 50,
        "caption": "Gender",
        "single_line": True,
    },
    "expiry_date": {
        **_TEXT,
        "x": 118,
        "y": 100,
        "font_size": 8,
        "caption_size": 7.5,
        "width": 68,
        "caption": "Expiry",
        "single_line": True,
    },
    "card_number": {
        **_TEXT,
        "x": 66,
        "y": 140,
        "font_size": 7.5,
        "caption_size": 7.5,
        "width": 118,
        "height": 11,
        "caption": "Card No.",
        "single_line": True,
    },
    "qr_code": {"x": 190, "y": 88, "page": 0, "width": 50, "height": 50},
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
