from django.conf import settings
from rest_framework import status
from Programs.permissions import CommunicationTemplatesPermission
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.email_templates import (
    EMAIL_TEMPLATE_DEFINITIONS,
    render_email_template,
)
from admissions.models import EmailTemplate
from admissions.serializers import EmailTemplateSerializer, EmailTemplateUpdateSerializer


class EmailTemplateListView(APIView):
    permission_classes = [CommunicationTemplatesPermission]

    def get(self, request):
        templates = EmailTemplate.objects.all().order_by("name")
        return Response(EmailTemplateSerializer(templates, many=True).data, status=status.HTTP_200_OK)


class EmailTemplateDetailView(APIView):
    permission_classes = [CommunicationTemplatesPermission]

    def get(self, request, key):
        template = EmailTemplate.objects.filter(key=key).first()
        if not template:
            return Response({"detail": "Template not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(EmailTemplateSerializer(template).data, status=status.HTTP_200_OK)

    def patch(self, request, key):
        template = EmailTemplate.objects.filter(key=key).first()
        if not template:
            return Response({"detail": "Template not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = EmailTemplateUpdateSerializer(template, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save(updated_by=request.user)
        return Response(EmailTemplateSerializer(updated).data, status=status.HTTP_200_OK)


class EmailTemplatePreviewView(APIView):
    permission_classes = [CommunicationTemplatesPermission]

    def post(self, request, key):
        if key not in EMAIL_TEMPLATE_DEFINITIONS:
            return Response({"detail": "Unknown template key."}, status=status.HTTP_404_NOT_FOUND)

        from accounts.portal_branding import get_erp_frontend_url

        sample_context = {
            "first_name": "John",
            "last_name": "Doe",
            "full_name": "John Doe",
            "full_name_upper": "JOHN DOE",
            "application_id": "1001",
            "submitted_date": "05 May 2026",
            "program": "Bachelor of Business Administration",
            "campus": "Main Campus",
            "study_mode": "Day",
            "batch_name": "August Intake",
            "academic_year": "2025/2026",
            "student_id": "SP123456",
            "reg_no": "26/1/377/D/1154",
            "default_password": "NDU@1234",
            "portal_url": get_erp_frontend_url(),
        }
        if key == EmailTemplate.KEY_WEEKLY_ADMISSIONS_DIGEST:
            from admissions.utils.weekly_report import build_weekly_report_metrics, week_bounds_for

            week_start, week_end = week_bounds_for()
            sample_context = build_weekly_report_metrics(week_start, week_end)
        sample_context.update(request.data.get("context", {}))

        subject, html_body, plain_text = render_email_template(key, sample_context)
        return Response(
            {
                "key": key,
                "subject": subject,
                "html_body": html_body,
                "plain_text": plain_text,
            },
            status=status.HTTP_200_OK,
        )


class EmailTemplateResetDefaultView(APIView):
    permission_classes = [CommunicationTemplatesPermission]

    def post(self, request, key):
        definition = EMAIL_TEMPLATE_DEFINITIONS.get(key)
        if not definition:
            return Response({"detail": "Unknown template key."}, status=status.HTTP_404_NOT_FOUND)

        template = EmailTemplate.objects.filter(key=key).first()
        if not template:
            template = EmailTemplate(key=key, name=str(definition["name"]))

        template.name = str(definition["name"])
        template.description = str(definition.get("description", ""))
        template.subject_template = str(definition["subject_template"])
        template.body_template_html = str(definition["body_template_html"])
        template.is_active = True
        template.updated_by = request.user
        template.save()
        return Response(EmailTemplateSerializer(template).data, status=status.HTTP_200_OK)

