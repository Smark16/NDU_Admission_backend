# utils/letters.py
from django.core.files.base import ContentFile
import platform
import subprocess
import os
import time
from docxtpl import DocxTemplate
from tempfile import NamedTemporaryFile
from docx2pdf import convert as docx2pdf_convert 

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

def save_docx_to_field(instance, field_name: str, filename: str, docx_bytes: bytes):
    content = ContentFile(docx_bytes)
    getattr(instance, field_name).save(filename, content)
    instance.save()

def fill_pdf_template(template_path: str, context: dict, field_positions: dict) -> bytes:
    """Overlay text onto a PDF at admin-specified coordinates using PyMuPDF."""
    import fitz
    from pathlib import Path

    doc = fitz.open(template_path)

    def _resolve_font(pos: dict):
        """Resolve mapped font settings to fitz insert_text options."""
        bold = bool(pos.get('bold', False))
        font_family = str(pos.get('font_family', 'helvetica')).strip().lower()

        # Built-in PDF fonts for broad compatibility.
        if font_family in ('helvetica', 'arial', ''):
            return {'fontname': 'hebo' if bold else 'helv'}
        if font_family in ('times', 'times new roman'):
            return {'fontname': 'tibo' if bold else 'tiro'}
        if font_family in ('courier', 'courier new'):
            return {'fontname': 'cobo' if bold else 'cour'}

        # Century fallback via system font files where available.
        if font_family == 'century':
            candidates = []
            if platform.system() == "Windows":
                win_fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
                candidates = [
                    win_fonts / "CENTURY.TTF",
                    win_fonts / "CENTURYB.TTF",
                    win_fonts / "GOTHIC.TTF",   # Century Gothic Regular
                    win_fonts / "GOTHICB.TTF",  # Century Gothic Bold
                ]
            else:
                candidates = [
                    Path("/usr/share/fonts/truetype/msttcorefonts/Times_New_Roman.ttf"),
                    Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
                ]

            for font_path in candidates:
                if font_path.exists():
                    return {'fontname': f'font_{font_family}', 'fontfile': str(font_path)}

            # Final fallback if Century files are unavailable.
            return {'fontname': 'tibo' if bold else 'tiro'}

        # Unknown family -> safe default.
        return {'fontname': 'hebo' if bold else 'helv'}

    for field_name, pos in field_positions.items():
        value = str(context.get(field_name, ''))
        if not value:
            continue
        page_num = int(pos.get('page', 0))
        x = float(pos.get('x', 0))
        y = float(pos.get('y', 0))
        font_size = float(pos.get('font_size', 11))
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

    pdf_bytes = doc.write()
    doc.close()
    return pdf_bytes

def convert_docx_to_pdf_bytes(docx_path: str) -> bytes:
    system = platform.system()
    pdf_path = os.path.splitext(docx_path)[0] + ".pdf"

    if system == "Windows":
        # docx2pdf requires MS Word installed. Accepts paths.
        docx2pdf_convert(docx_path, pdf_path)
        os.system("taskkill /f /im WINWORD.EXE")
    else:
        # Linux: use libreoffice soffice/soffice.bin executable
        subprocess.run([
            "libreoffice", "--headless", "--convert-to", "pdf", docx_path, "--outdir", os.path.dirname(docx_path)
        ], check=True)

         # Wait a moment for file to be fully written
        for _ in range(10):
            if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
                break
            time.sleep(0.5)
        else:
            raise TimeoutError("PDF was not generated in time")

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()
    # optionally remove temp files
    os.remove(pdf_path)
    return pdf_bytes
