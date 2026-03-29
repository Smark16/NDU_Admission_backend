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
from .utils.letters import render_docx_from_template, save_docx_to_field, convert_docx_to_pdf_bytes, save_docx_to_field
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

    # 2. Build placeholders
    context = {
        "full_name": f"{applicant.first_name} {applicant.last_name}",
        "student_no": admission.student_id or "TBD",
        "reg_no": admission.reg_no or "TBD",
        "program_name": admission.admitted_program.name,
        "min_years": admission.admitted_program.max_years,
        "max_years":admission.admitted_program.min_years,
        "campus": admission.admitted_campus,
        "study_mode":admission.study_mode
    }

    # 3. Render DOCX bytes (Synchronous and fast)
    try:
        docx_bytes = render_docx_from_template(template.file.path, context)
    except Exception as e:
        logger.error(f"DOCX rendering failed for applicant {applicant_id}: {e}")
        return Response({"detail": "DOCX template rendering failed"}, status=500)

    # 4. Save DOCX immediately (fast storage operation)
    docx_filename = f"OfferLetter_{applicant.id}.docx"
    applicant.admission_letter_docx.save(docx_filename, ContentFile(docx_bytes))
    applicant.save()

    # 5. Start heavy task (PDF conversion, status update, email) in background thread
    threading.Thread(
        target=convert_and_save_pdf_task,
        args=(docx_bytes, applicant.id),
        daemon=True
    ).start()

    # 6. Instant response to the client
    # This prevents the client request from timing out while Word is converting the PDF
    return Response({
        "detail": "Offer letter DOCX saved. PDF generation, status update, and email are starting in the background.",
        "status": "processing",
        "docx_url": applicant.admission_letter_docx.url 
    })

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
    