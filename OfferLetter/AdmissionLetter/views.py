from django.shortcuts import render
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import generics, status
from rest_framework.permissions import *
from rest_framework.parsers import MultiPartParser, FormParser
from .models import *
from .serializers import *
from django.utils import timezone

import os
from django.core.files.base import ContentFile
from tempfile import NamedTemporaryFile
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from admissions.models import Application, AdmittedStudent
from .utils.letters import render_docx_from_template, save_docx_to_field, convert_docx_to_pdf_bytes, save_docx_to_field, fill_pdf_template
from admissions.utils.notification import create_notification
from django.core.mail import send_mail
from django.conf import settings
import threading
from django.db import close_old_connections
import logging
import platform
from .tasks import send_offerletter_email

logger = logging.getLogger(__name__)


if platform.system() == "Windows":
    try:
        import pythoncom
    except ImportError:
        # This will only happen if pywin32 is not installed on Windows
        print("Warning: pythoncom not found. DOCX to PDF conversion may fail on Windows.")

# import win32com.client

# Create your views here.

# upload template
class UploadTemplate(generics.CreateAPIView):
    queryset = OfferLetterTemplate.objects.all()
    serializer_class = TemplateSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    parser_classes = [MultiPartParser, FormParser]

# list templates
class ListTemplates(generics.ListAPIView):
    queryset = OfferLetterTemplate.objects.all()
    serializer_class = TemplateSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

# edit template
class EditTemplate(generics.UpdateAPIView):
    queryset = OfferLetterTemplate.objects.all()
    serializer_class = TemplateSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def put(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)  
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=200)
    
# delete template
class DeleteTemplate(generics.RetrieveDestroyAPIView):
    queryset = OfferLetterTemplate.objects.all()
    serializer_class = TemplateSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def delete(self, request, *args, **kwargs):
        insatnce = self.get_object()
        insatnce.delete()

        return Response({"detail":"template deleted successfully"})
    
# ================================================Offer letters======================================================
# The function that runs in the background thread (the heavy lifting)
def convert_and_save_pdf_task(docx_bytes_local, applicant_id_local):
    # 1. Thread safety: Close old connections from the main thread
    close_old_connections()
    
    tmp_path = None
    
    # === CRITICAL FIX: Initialize COM for this specific thread on Windows ===
    is_windows = platform.system() == "Windows"
    if is_windows and 'pythoncom' in globals():
        try:
            pythoncom.CoInitialize()
        except Exception as e:
            logger.warning(f"Failed to initialize COM in thread for {applicant_id_local}: {e}")

    try:
        # 2. Re-fetch the applicant inside the thread
        applicant_local = Application.objects.get(id=applicant_id_local)

         # Step 1: DOCX saved → update status
        applicant_local.offer_letter_status = "docx_generated"
        applicant_local.offer_letter_progress = 30
        applicant_local.save(update_fields=['offer_letter_status', 'offer_letter_progress'])

         # Step 2: Start PDF conversion
        applicant_local.offer_letter_status = "converting_pdf"
        applicant_local.offer_letter_progress = 50
        applicant_local.save(update_fields=['offer_letter_status', 'offer_letter_progress'])

        # 3. Save DOCX to a temp file for conversion
        # Using NamedTemporaryFile within the thread for its lifecycle
        tmp = NamedTemporaryFile(delete=False, suffix=".docx")
        tmp.write(docx_bytes_local)
        tmp.flush()
        tmp.close()
        tmp_path = tmp.name

        logger.info(f"Starting PDF conversion for applicant {applicant_id_local}")
        
        # 4. Perform the conversion (this is the call that required COM initialization)
        pdf_bytes = convert_docx_to_pdf_bytes(tmp_path) 
        
        logger.info(f"PDF conversion successful for applicant {applicant_id_local}")

         # Step 3: PDF ready
        applicant_local.offer_letter_status = "pdf_ready"
        applicant_local.offer_letter_progress = 90
        applicant_local.save(update_fields=['offer_letter_status', 'offer_letter_progress'])

        # 5. Save the resulting PDF bytes
        pdf_filename = f"OfferLetter_{applicant_id_local}.pdf"
        applicant_local.admission_letter_pdf.save(
            pdf_filename, ContentFile(pdf_bytes)
        )
        applicant_local.status = "Admitted"
        applicant_local.save()

        # 6. Handle Email/Notification (detailed version)
        send_offerletter_email.delay(applicant_local.id)

        try:
            applicant_local.offer_letter_status = "email_sent"
            applicant_local.offer_letter_progress = 100
            applicant_local.save(update_fields=['offer_letter_status', 'offer_letter_progress'])

        except Exception as e:
            logger.error(f"Failed to send email/notification for {applicant_id_local}: {e}")

    except Application.DoesNotExist:
        logger.error(f"Applicant with ID {applicant_id_local} not found in background thread.")
    except Exception as e:
        # Log the error if PDF conversion fails
        applicant_local.offer_letter_status = "failed"
        applicant_local.offer_letter_progress = 0
        applicant_local.save(update_fields=['offer_letter_status', 'offer_letter_progress'])
        logger.error(f"PDF failed: {e}")
        logger.error(f"Critical error during PDF generation for {applicant_id_local}: {e}", exc_info=True)
    finally:
        # 7. Cleanup temp file
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
            
        # === CRITICAL FIX: Uninitialize COM when thread finishes ===
        if is_windows and 'pythoncom' in globals():
            try:
                pythoncom.CoUninitialize()
            except Exception as e:
                 logger.warning(f"CoUninitialize failed for thread: {e}")

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def send_offer_letter(request, applicant_id):
    applicant = get_object_or_404(Application, pk=applicant_id)
    admission = get_object_or_404(AdmittedStudent, application=applicant)

    # 1. Choose template
    template = (
        OfferLetterTemplate.objects
        .filter(programs__id=admission.admitted_program_id)
        .filter(status="active")
        .order_by('-uploaded_at')
        .first()
    )

    if not template:
        return Response({"detail": "No template for this program is uploaded yet"}, status=400)

    # 2. Build context
    import random as _random

    if template.start_date:
        start_date_formatted = template.start_date.strftime("%B %d, %Y")
    else:
        start_date_formatted = "To Be Announced"

    halls = ["AKIIBUA", "NJUKI", "MUTEESA", "KAKUNGULU", "YOKANA"]
    if template.hall_of_residence == "RANDOM":
        hall = _random.choice(halls)
    elif template.hall_of_residence:
        hall = template.hall_of_residence
    else:
        hall = "To Be Assigned"

    # check title
    title = (applicant.title or "").strip()
    if not applicant.title:
       if applicant.gender and applicant.gender.lower() == "male":
           title = "MR."
       elif applicant.gender and applicant.gender.lower() == "female":
           title = "MS."    
           
    context = {
        "full_name": f"{title} {(applicant.first_name or '').strip()} {(applicant.last_name or '').strip()}".upper(),
        "phone_number": applicant.phone or "",
        "phone": applicant.phone or "",
        "student_no": admission.student_id or "TBD",
        "reg_no": admission.reg_no or "TBD",
        "program_name": admission.admitted_program.name,
        "min_years": admission.admitted_program.max_years,
        "max_years": admission.admitted_program.min_years,
        "campus": admission.admitted_campus,
        "study_mode": admission.study_mode,
        "start_date": start_date_formatted,
        "hall_of_residence": hall,
    }

    # 3. PDF template path: overlay text directly → no DOCX/LibreOffice needed
    if template.file_type == 'pdf':
        if not template.field_positions:
            return Response({"detail": "PDF template has no field positions configured. Use 'Map Fields' first."}, status=400)
        try:
            pdf_bytes = fill_pdf_template(template.file.path, context, template.field_positions)
        except Exception as e:
            logger.error(f"PDF fill failed for applicant {applicant_id}: {e}")
            return Response({"detail": "PDF template filling failed."}, status=500)

        pdf_filename = f"OfferLetter_{applicant.id}.pdf"
        applicant.admission_letter_pdf.save(pdf_filename, ContentFile(pdf_bytes))
        applicant.status = "Admitted"
        applicant.offer_letter_status = "email_sent"
        applicant.offer_letter_progress = 100
        applicant.save()
        send_offerletter_email.delay(applicant.id)
        return Response({
            "detail": "Offer letter generated from PDF template.",
            "status": "complete",
            "pdf_url": applicant.admission_letter_pdf.url,
        })

    # 4. DOCX template: render then convert in background
    try:
        docx_bytes = render_docx_from_template(template.file.path, context)
    except Exception as e:
        logger.error(f"DOCX rendering failed for applicant {applicant_id}: {e}")
        return Response({"detail": "DOCX template rendering failed"}, status=500)

    docx_filename = f"OfferLetter_{applicant.id}.docx"
    applicant.admission_letter_docx.save(docx_filename, ContentFile(docx_bytes))
    applicant.save()

    threading.Thread(
        target=convert_and_save_pdf_task,
        args=(docx_bytes, applicant.id),
        daemon=True
    ).start()

    return Response({
        "detail": "Offer letter DOCX saved. PDF generation, status update, and email are starting in the background.",
        "status": "processing",
        "docx_url": applicant.admission_letter_docx.url,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def resend_offer_letter(request, applicant_id):
    """Re-send an already generated offer letter email without regenerating files."""
    applicant = get_object_or_404(Application, pk=applicant_id)

    if not applicant.admission_letter_pdf:
        return Response(
            {"detail": "No generated offer letter PDF found for this applicant. Generate first."},
            status=400,
        )

    send_offerletter_email.delay(applicant.id)
    return Response(
        {"detail": "Offer letter email queued successfully.", "status": "queued"},
        status=200,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def bulk_send_offer_letters(request):
    """Generate (if needed) and queue offer letter emails for multiple applicants."""
    raw_ids = request.data.get("application_ids", [])
    if not isinstance(raw_ids, list) or not raw_ids:
        return Response({"detail": "application_ids must be a non-empty list."}, status=400)

    cleaned_ids = []
    for raw_id in raw_ids:
        try:
            cleaned_ids.append(int(raw_id))
        except (TypeError, ValueError):
            continue

    if not cleaned_ids:
        return Response({"detail": "No valid applicant IDs provided."}, status=400)

    generated = 0
    reused_pdf = 0
    failed = 0
    errors = []

    for applicant_id in cleaned_ids:
        try:
            applicant = Application.objects.filter(pk=applicant_id).first()
            if not applicant:
                failed += 1
                errors.append({"id": applicant_id, "detail": "Applicant not found."})
                continue

            # If a PDF already exists, simply queue resend.
            if applicant.admission_letter_pdf:
                send_offerletter_email.delay(applicant.id)
                reused_pdf += 1
                continue

            # Reuse existing single-app generation/send flow.
            single_response = send_offer_letter(request, applicant.id)
            if 200 <= single_response.status_code < 300:
                generated += 1
            else:
                failed += 1
                error_detail = "Failed to generate/send offer letter."
                if isinstance(single_response.data, dict):
                    error_detail = single_response.data.get("detail", error_detail)
                errors.append({"id": applicant_id, "detail": error_detail})
        except Exception as e:
            logger.error(f"Bulk offer letter processing failed for applicant {applicant_id}: {e}", exc_info=True)
            failed += 1
            errors.append({"id": applicant_id, "detail": "Unexpected server error."})

    total = len(cleaned_ids)
    return Response(
        {
            "detail": f"Processed {total} applicants. Generated+queued: {generated}, Reused existing PDF+queued: {reused_pdf}, Failed: {failed}.",
            "summary": {
                "total": total,
                "generated_and_queued": generated,
                "reused_existing_pdf_and_queued": reused_pdf,
                "failed": failed,
            },
            "errors": errors[:50],
        },
        status=200 if failed == 0 else 207,
    )

# offer letter status
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def offer_letter_status(request, applicant_id):
    app = get_object_or_404(Application, id=applicant_id)
    return Response({
        "status": app.offer_letter_status,
        "progress": app.offer_letter_progress,
        "docx_url": app.admission_letter_docx.url if app.admission_letter_docx else None,
        "pdf_url": app.admission_letter_pdf.url if app.admission_letter_pdf else None,
    })


# ── PDF template: preview first page as base64 PNG ──────────────────────────
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def pdf_template_preview(request, pk):
    template = get_object_or_404(OfferLetterTemplate, pk=pk)
    file_ext = os.path.splitext(template.file.name or "")[1].lower()
    is_pdf = (template.file_type == 'pdf') or (file_ext == '.pdf')
    if not is_pdf:
        return Response({'detail': 'Selected template is not a PDF file.'}, status=400)

    import fitz
    import base64

    try:
        doc = fitz.open(template.file.path)
        page = doc[0]
        pdf_width = page.rect.width
        pdf_height = page.rect.height
        mat = fitz.Matrix(2, 2)  # 2× zoom for sharp preview
        pix = page.get_pixmap(matrix=mat)
        img_b64 = base64.b64encode(pix.tobytes('png')).decode()
        doc.close()
    except Exception as e:
        logger.error(f"Failed to generate PDF preview for template {template.id}: {e}", exc_info=True)
        return Response({'detail': 'Failed to render PDF preview. Ensure the uploaded template is a valid PDF.'}, status=500)

    return Response({
        'image': img_b64,
        'pdf_width': pdf_width,
        'pdf_height': pdf_height,
        'field_positions': template.field_positions,
    })


# ── PDF template: save field positions ──────────────────────────────────────
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def save_pdf_field_positions(request, pk):
    template = get_object_or_404(OfferLetterTemplate, pk=pk)
    file_ext = os.path.splitext(template.file.name or "")[1].lower()
    is_pdf = (template.file_type == 'pdf') or (file_ext == '.pdf')
    if not is_pdf:
        return Response({'detail': 'Selected template is not a PDF file.'}, status=400)

    positions = request.data.get('field_positions', {})
    template.field_positions = positions
    template.save(update_fields=['field_positions'])
    return Response({'detail': 'Field positions saved successfully.'})