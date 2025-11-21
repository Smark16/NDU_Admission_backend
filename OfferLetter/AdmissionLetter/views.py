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

    # choose a template (you may allow selecting one via POST param)
    template = (
    OfferLetterTemplate.objects
    .filter(programs__id=admission.admitted_program_id)
    .filter(status="active")
    .order_by('-uploaded_at')
    .first()
     )
    if not template:
        return Response({"detail": "No template uploaded"}, status=400)

    # build context dictionary for placeholders
    context = {
        "full_name": f"{applicant.first_name} {applicant.last_name}",
        "student_no": admission.student_id or "TBD",
        "reg_no": admission.reg_no or "TBD",
        "program_name": admission.admitted_program.name ,
        "fees": admission.admitted_program.application_fee,   # ensure fields exist
        "duration": admission.admitted_program.duration_years,
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

    return Response({
        "detail": "Offer letter generated and attached",
        "pdf_url": applicant.admission_letter_pdf.url
    })

