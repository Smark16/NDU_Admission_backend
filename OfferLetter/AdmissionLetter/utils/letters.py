# utils/letters.py
from __future__ import annotations

import os
import platform
import subprocess
import time
from io import BytesIO
from tempfile import NamedTemporaryFile

from django.core.files.base import ContentFile
from docxtpl import DocxTemplate
from docx2pdf import convert as docx2pdf_convert


def _read_filefield_bytes(file_field) -> bytes:
    if not file_field or not getattr(file_field, "name", None):
        raise FileNotFoundError("Template file is not set on the server.")
    with file_field.open("rb") as handle:
        return handle.read()


def render_docx_from_template(template_path: str, context: dict) -> bytes:
    doc = DocxTemplate(template_path)
    doc.render(context)
    tmp = NamedTemporaryFile(delete=False, suffix=".docx")
    tmp_name = tmp.name
    tmp.close()
    doc.save(tmp_name)
    with open(tmp_name, "rb") as f:
        data = f.read()
    os.remove(tmp_name)
    return data


def render_docx_from_template_file(template_file, context: dict) -> bytes:
    """Render DOCX from a Django FileField (works when .path is unavailable)."""
    doc = DocxTemplate(BytesIO(_read_filefield_bytes(template_file)))
    doc.render(context)
    tmp = NamedTemporaryFile(delete=False, suffix=".docx")
    tmp_name = tmp.name
    tmp.close()
    doc.save(tmp_name)
    with open(tmp_name, "rb") as f:
        data = f.read()
    os.remove(tmp_name)
    return data


def save_docx_to_field(instance, field_name: str, filename: str, docx_bytes: bytes):
    content = ContentFile(docx_bytes)
    getattr(instance, field_name).save(filename, content)
    instance.save()


def _fill_pdf_template_bytes(pdf_bytes: bytes, context: dict, field_positions: dict) -> bytes:
    """Overlay text onto PDF bytes at admin-specified coordinates using PyMuPDF."""
    import fitz
    from pathlib import Path

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    def _resolve_font(pos: dict):
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
                    Path("/usr/share/fonts/truetype/msttcorefonts/Times_New_Roman.ttf"),
                    Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
                ]

            for font_path in candidates:
                if font_path.exists():
                    return {"fontname": f"font_{font_family}", "fontfile": str(font_path)}

            return {"fontname": "tibo" if bold else "tiro"}

        return {"fontname": "hebo" if bold else "helv"}

    for field_name, pos in field_positions.items():
        value = str(context.get(field_name, "") or "")
        if not value:
            continue
        page_num = int(pos.get("page", 0))
        x = float(pos.get("x", 0))
        y = float(pos.get("y", 0))
        font_size = float(pos.get("font_size", 11))
        font_kwargs = _resolve_font(pos)
        if page_num < len(doc):
            page = doc[page_num]
            page.insert_text(
                fitz.Point(x, y),
                value,
                fontsize=font_size,
                color=(0, 0, 0),
                **font_kwargs,
            )

    out = doc.write()
    doc.close()
    return out


def fill_pdf_template(template_path: str, context: dict, field_positions: dict) -> bytes:
    with open(template_path, "rb") as handle:
        return _fill_pdf_template_bytes(handle.read(), context, field_positions)


def fill_pdf_template_file(template_file, context: dict, field_positions: dict) -> bytes:
    """Fill a PDF template from a Django FileField (works when .path is unavailable)."""
    return _fill_pdf_template_bytes(_read_filefield_bytes(template_file), context, field_positions)


def convert_docx_to_pdf_bytes(docx_path: str) -> bytes:
    system = platform.system()
    pdf_path = os.path.splitext(docx_path)[0] + ".pdf"

    if system == "Windows":
        docx2pdf_convert(docx_path, pdf_path)
        os.system("taskkill /f /im WINWORD.EXE")
    else:
        subprocess.run(
            [
                "libreoffice",
                "--headless",
                "--convert-to",
                "pdf",
                docx_path,
                "--outdir",
                os.path.dirname(docx_path),
            ],
            check=True,
        )

        for _ in range(10):
            if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
                break
            time.sleep(0.5)
        else:
            raise TimeoutError("PDF was not generated in time")

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()
    os.remove(pdf_path)
    return pdf_bytes
