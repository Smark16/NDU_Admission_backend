from celery import shared_task
from django.apps import apps
from .utils.emails import offerletter_email
import os
import base64
import logging
import platform

from django.core.files.base import ContentFile
from django.db import close_old_connections
from django.utils import timezone
from tempfile import NamedTemporaryFile

from admissions.models import Application
from .utils.letters import convert_docx_to_pdf_bytes
from .utils.offer_generation import generate_offer_letter_for_application, resolve_verify_base
from .utils.bulk_report import append_bulk_report_row

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
def convert_and_save_pdf_task(self, encoded_docx, applicant_id, send_email=True):
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

        if send_email:
            send_offerletter_email.delay(applicant.id)

        applicant.offer_letter_status = "email_sent" if send_email else "pdf_ready"
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


def _bulk_job_cache_key(job_id: str) -> str:
    return f"offer_letter_bulk_job:{job_id}"


def load_bulk_offer_letter_job(job_id: str):
    from django.core.cache import cache

    return cache.get(_bulk_job_cache_key(job_id))


def save_bulk_offer_letter_job(job_id: str, payload: dict, timeout: int = 60 * 60 * 24 * 7) -> None:
    from django.core.cache import cache

    cache.set(_bulk_job_cache_key(job_id), payload, timeout=timeout)


@shared_task(bind=True)
def bulk_generate_offer_letters_task(
    self,
    job_id: str,
    application_ids: list,
    user_id: int,
    send_email: bool = False,
    skip_if_pdf_exists: bool = True,
    verify_base: str | None = None,
):
    close_old_connections()

    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User.objects.filter(pk=user_id).first()
    verify_base = verify_base or resolve_verify_base()

    job = load_bulk_offer_letter_job(job_id) or {}
    job["status"] = "running"
    job["celery_task_id"] = self.request.id
    save_bulk_offer_letter_job(job_id, job)

    for index, application_id in enumerate(application_ids, start=1):
        close_old_connections()
        try:
            app = Application.objects.filter(pk=application_id).only("id", "admission_letter_pdf").first()
            has_pdf = bool(app and app.admission_letter_pdf and getattr(app.admission_letter_pdf, "name", None))
            if not app:
                job["failed"] = job.get("failed", 0) + 1
                append_bulk_report_row(job, application_id, "failed", "Applicant not found.")
            elif skip_if_pdf_exists and has_pdf:
                job["reused"] = job.get("reused", 0) + 1
                append_bulk_report_row(
                    job,
                    application_id,
                    "reused_existing_pdf",
                    "PDF already on file; skipped regeneration.",
                )
                if send_email:
                    send_offerletter_email.delay(application_id)
            else:
                result = generate_offer_letter_for_application(
                    application_id,
                    user,
                    verify_base=verify_base,
                    send_email=send_email,
                    skip_if_pdf_exists=False,
                )
                if result.get("ok"):
                    if result.get("status") == "skipped":
                        job["reused"] = job.get("reused", 0) + 1
                        append_bulk_report_row(
                            job,
                            application_id,
                            "reused_existing_pdf",
                            result.get("detail") or "Existing PDF reused.",
                        )
                    elif result.get("status") == "processing":
                        job["generated"] = job.get("generated", 0) + 1
                        append_bulk_report_row(
                            job,
                            application_id,
                            "processing",
                            "DOCX rendered; PDF conversion queued in background.",
                        )
                    else:
                        job["generated"] = job.get("generated", 0) + 1
                        append_bulk_report_row(
                            job,
                            application_id,
                            "generated",
                            result.get("detail") or "Offer letter PDF generated.",
                        )
                else:
                    job["failed"] = job.get("failed", 0) + 1
                    append_bulk_report_row(
                        job,
                        application_id,
                        "failed",
                        result.get("detail", "Generation failed."),
                    )
        except Exception as exc:
            logger.error("Bulk offer letter failed for application %s: %s", application_id, exc, exc_info=True)
            job["failed"] = job.get("failed", 0) + 1
            message = str(exc).strip() or exc.__class__.__name__
            append_bulk_report_row(job, application_id, "failed", f"Unexpected server error: {message[:400]}")

        job["processed"] = index
        if index % 25 == 0 or index == len(application_ids):
            save_bulk_offer_letter_job(job_id, job)

    job["status"] = "complete"
    job["finished_at"] = timezone.now().isoformat()
    job["errors"] = [
        {"id": r["application_id"], "detail": r.get("detail") or "Generation failed."}
        for r in job.get("report_rows", [])
        if r.get("outcome") == "failed"
    ]
    save_bulk_offer_letter_job(job_id, job)
    return {
        "job_id": job_id,
        "processed": job.get("processed", 0),
        "generated": job.get("generated", 0),
        "reused": job.get("reused", 0),
        "failed": job.get("failed", 0),
    }