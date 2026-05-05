from celery import shared_task
from django.apps import apps
from .utils.emails import offerletter_email
import os
import base64
import logging
import platform

from django.core.files.base import ContentFile
from django.db import close_old_connections
from django.conf import settings
from tempfile import NamedTemporaryFile

from admissions.models import Application
from .utils.letters import convert_docx_to_pdf_bytes 

logger = logging.getLogger(__name__)

if platform.system() == "Windows":
    try:
        import pythoncom
    except ImportError:
        # This will only happen if pywin32 is not installed on Windows
        print("Warning: pythoncom not found. DOCX to PDF conversion may fail on Windows.")

@shared_task
def send_offerletter_email(application_id):
    Application = apps.get_model('admissions', 'Application')
    application = Application.objects.get(id=application_id)

    offerletter_email(application)

@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def convert_and_save_pdf_task(self, encoded_docx, applicant_id):
    # 🔥 Always ensure fresh DB connection in Celery worker
    close_old_connections()

    tmp_path = None
    applicant = None

    is_windows = platform.system() == "Windows"
    if is_windows and 'pythoncom' in globals():
        try:
            pythoncom.CoInitialize()
        except Exception as e:
            logger.warning(f"Failed to initialize COM in thread for {applicant_id}: {e}")

    try:
        # 1. Decode docx
        docx_bytes = base64.b64decode(encoded_docx)

        # 2. Fetch applicant safely
        applicant = Application.objects.get(id=applicant_id)

        # Step 1: DOCX ready
        applicant.offer_letter_status = "docx_generated"
        applicant.offer_letter_progress = 30
        applicant.save(update_fields=["offer_letter_status", "offer_letter_progress"])

        # Step 2: Start conversion
        applicant.offer_letter_status = "converting_pdf"
        applicant.offer_letter_progress = 50
        applicant.save(update_fields=["offer_letter_status", "offer_letter_progress"])

        # 3. Save temp DOCX
        tmp = NamedTemporaryFile(delete=False, suffix=".docx")
        tmp.write(docx_bytes)
        tmp.flush()
        tmp.close()
        tmp_path = tmp.name

        logger.info(f"[PDF TASK] Starting conversion for applicant {applicant_id}")

        # 4. Convert DOCX → PDF
        pdf_bytes = convert_docx_to_pdf_bytes(tmp_path)

        logger.info(f"[PDF TASK] Conversion success for applicant {applicant_id}")

        # Step 3: PDF ready
        applicant.offer_letter_status = "pdf_ready"
        applicant.offer_letter_progress = 90
        applicant.save(update_fields=["offer_letter_status", "offer_letter_progress"])

        # 5. Save PDF
        pdf_filename = f"OfferLetter_{applicant_id}.pdf"
        applicant.admission_letter_pdf.save(
            pdf_filename,
            ContentFile(pdf_bytes)
        )

        applicant.status = "Admitted"
        applicant.save(update_fields=["admission_letter_pdf", "status"])

        # Step 4: Send email
        send_offerletter_email.delay(applicant.id)

        applicant.offer_letter_status = "email_sent"
        applicant.offer_letter_progress = 100
        applicant.save(update_fields=["offer_letter_status", "offer_letter_progress"])

        logger.info(f"[PDF TASK] Completed for applicant {applicant_id}")

    except Application.DoesNotExist:
        logger.error(f"[PDF TASK] Applicant {applicant_id} not found")

    except Exception as e:
        logger.error(f"[PDF TASK] Failed for {applicant_id}: {e}", exc_info=True)

        if applicant:
            applicant.offer_letter_status = "failed"
            applicant.offer_letter_progress = 0
            applicant.save(update_fields=["offer_letter_status", "offer_letter_progress"])

        raise self.retry(exc=e)

    finally:
        # Cleanup temp file
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

        if is_windows:
            try:
                import pythoncom
                pythoncom.CoUninitialize()
            except Exception as e:
                logger.warning(f"COM uninit failed: {e}")