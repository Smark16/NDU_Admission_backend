# utils/letters.py
from django.core.files.base import ContentFile
import platform
import subprocess
import os
from docxtpl import DocxTemplate
from tempfile import NamedTemporaryFile
from docx2pdf import convert as docx2pdf_convert  # optional, Windows dev

def render_docx_from_template(template_path: str, context: dict) -> bytes:
    """
    Renders a docx from `template_path` using docxtpl and returns bytes of the .docx.
    """
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
    """
    Save docx_bytes to instance.field_name (FileField).
    """
    content = ContentFile(docx_bytes)
    getattr(instance, field_name).save(filename, content)
    instance.save()

def convert_docx_to_pdf_bytes(docx_path: str) -> bytes:
    """
    Convert given docx_path to pdf and return pdf bytes.
    Uses docx2pdf on Windows; LibreOffice headless on Linux.
    """
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

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()
    # optionally remove temp files
    os.remove(pdf_path)
    return pdf_bytes
