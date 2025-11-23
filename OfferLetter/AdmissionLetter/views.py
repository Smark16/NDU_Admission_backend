from django.shortcuts import render
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import generics, status
from rest_framework.permissions import *
from rest_framework.parsers import MultiPartParser, FormParser
from .models import *
from .serializers import *

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

import logging
logger = logging.getLogger(__name__)


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
        serializer = self.get_serializer(instance, data=request.data)  # Critical line
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

@api_view(['POST'])
@permission_classes( [IsAuthenticated])
def send_offer_letter(request, applicant_id):
    applicant = get_object_or_404(Application, pk=applicant_id)

    admission = get_object_or_404(AdmittedStudent, application=applicant)

    # choose a template 
    template = (
    OfferLetterTemplate.objects
    .filter(programs__id=admission.admitted_program_id)
    .filter(status="active")
    .order_by('-uploaded_at')
    .first()
     )
    if not template:
        return Response({"detail": "No template for this program is uploaded yet"}, status=400)

    # build context dictionary for placeholders
    context = {
        "full_name": f"{applicant.first_name} {applicant.last_name}",
        "student_no": admission.student_id or "TBD",
        "reg_no": admission.reg_no or "TBD",
        "program_name": admission.admitted_program.name,
        "duration": admission.admitted_program.max_years,
        "campus": admission.admitted_campus,
        # add any other placeholders
    }

    # Render docx bytes
    docx_bytes = render_docx_from_template(template.file.path, context)

    # Save docx to a temp file (so LibreOffice can convert)
    tmp_docx = NamedTemporaryFile(delete=False, suffix=".docx")
    tmp_docx.write(docx_bytes)
    tmp_docx.flush()
    tmp_docx.close()
    tmp_docx_path = tmp_docx.name

    # Save docx into applicant FileField
    docx_filename = f"OfferLetter_{applicant.id}.docx"
    applicant.admission_letter_docx.save(docx_filename, ContentFile(docx_bytes))
    applicant.save()

    # Convert to PDF (uses LibreOffice on Linux, docx2pdf on Windows)
    try:
        pdf_bytes = convert_docx_to_pdf_bytes(tmp_docx_path)
    except Exception as e:
        # cleanup temp docx
        os.remove(tmp_docx_path)
        return Response({"detail": "PDF conversion failed", "error": str(e)}, status=500)

    # cleanup temp docx before saving
    os.remove(tmp_docx_path)

    # Save pdf bytes to FileField
    pdf_filename = f"OfferLetter_{applicant.id}.pdf"
    applicant.admission_letter_pdf.save(pdf_filename, ContentFile(pdf_bytes))
    applicant.status = "Admitted"
    applicant.save()

    # Optionally send email/notification to student here
    try:
        send_mail(
          subject="Admission letter sent successfully",

            message=(
                f"Dear {applicant.first_name} {applicant.last_name},\n\n"
                f"CONGRATULATIONS!\n\n"
                f"We are delighted to inform you that your admission letter has been **successfully sent to your portal**.\n\n"
                f"Next Steps:\n"
                f"1. Log in to your portal to download your official admission letter\n"
                f"2. Confirm every thing is ok and sign where necessary\n"
                f"3. Complete registration before the deadline\n\n"
                f"We look forward to welcoming you to the Ndejje University family!\n\n"
                f"Warm regards,\n"
                f"Admissions Office\n"
                f"Ndejje University\n"
                f"Email: admissions@ndejjeuniversity.ac.ug\n"
                f"Website: www.ndejjeuniversity.ac.ug"
                    ),

                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[applicant.email],
                fail_silently=False,
                    )

        create_notification(applicant.applicant, "Admission letter sent successfully", "Your adimission Letter has been successfully delivered.")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return Response({"detail":"Failed to send email please check connection"}, status=400)

    return Response({
        "detail": "Offer letter generated and attached",
        "pdf_url": applicant.admission_letter_pdf.url
    })

