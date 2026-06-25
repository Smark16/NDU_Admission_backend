from rest_framework import status
from Programs.permissions import CommunicationTemplatesPermission
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.email_templates import render_email_template
from admissions.models import EmailTemplate, WeeklyReportRecipient, WeeklyReportSettings
from admissions.serializers import WeeklyReportRecipientSerializer, WeeklyReportSettingsSerializer
from admissions.utils.weekly_report import (
    build_weekly_report_metrics,
    send_weekly_admissions_digest,
    send_weekly_digest_to_email,
    week_bounds_for,
)


class WeeklyReportSettingsView(APIView):
    permission_classes = [CommunicationTemplatesPermission]

    def get(self, request):
        settings_row = WeeklyReportSettings.get_solo()
        recipients_count = WeeklyReportRecipient.objects.filter(is_active=True).count()
        data = WeeklyReportSettingsSerializer(settings_row).data
        data["active_recipients_count"] = recipients_count
        return Response(data, status=status.HTTP_200_OK)

    def patch(self, request):
        settings_row = WeeklyReportSettings.get_solo()
        serializer = WeeklyReportSettingsSerializer(settings_row, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save(updated_by=request.user)
        return Response(WeeklyReportSettingsSerializer(updated).data, status=status.HTTP_200_OK)


class WeeklyReportRecipientListCreateView(APIView):
    permission_classes = [CommunicationTemplatesPermission]

    def get(self, request):
        recipients = WeeklyReportRecipient.objects.all().order_by("email")
        return Response(WeeklyReportRecipientSerializer(recipients, many=True).data)

    def post(self, request):
        serializer = WeeklyReportRecipientSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        recipient = serializer.save(created_by=request.user)
        return Response(WeeklyReportRecipientSerializer(recipient).data, status=status.HTTP_201_CREATED)


class WeeklyReportRecipientDetailView(APIView):
    permission_classes = [CommunicationTemplatesPermission]

    def patch(self, request, pk):
        recipient = WeeklyReportRecipient.objects.filter(pk=pk).first()
        if not recipient:
            return Response({"detail": "Recipient not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = WeeklyReportRecipientSerializer(recipient, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        return Response(WeeklyReportRecipientSerializer(updated).data)

    def delete(self, request, pk):
        recipient = WeeklyReportRecipient.objects.filter(pk=pk).first()
        if not recipient:
            return Response({"detail": "Recipient not found."}, status=status.HTTP_404_NOT_FOUND)
        recipient.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class WeeklyReportPreviewView(APIView):
    permission_classes = [CommunicationTemplatesPermission]

    def get(self, request):
        week_start, week_end = week_bounds_for()
        metrics = build_weekly_report_metrics(week_start, week_end)
        subject, html_body, plain_text = render_email_template(
            EmailTemplate.KEY_WEEKLY_ADMISSIONS_DIGEST,
            metrics,
        )
        return Response(
            {
                "metrics": metrics,
                "subject": subject,
                "html_body": html_body,
                "plain_text": plain_text,
            },
            status=status.HTTP_200_OK,
        )


class WeeklyReportTestSendView(APIView):
    permission_classes = [CommunicationTemplatesPermission]

    def post(self, request):
        test_email = (request.data.get("email") or request.user.email or "").strip()
        if not test_email:
            return Response({"detail": "email is required."}, status=status.HTTP_400_BAD_REQUEST)

        ok = send_weekly_digest_to_email(test_email)
        if not ok:
            return Response({"detail": "Failed to send test email."}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({"detail": f"Test digest sent to {test_email}."}, status=status.HTTP_200_OK)


class WeeklyReportSendNowView(APIView):
    permission_classes = [CommunicationTemplatesPermission]

    def post(self, request):
        active_count = WeeklyReportRecipient.objects.filter(is_active=True).count()
        if active_count == 0:
            return Response(
                {"detail": "Add at least one active recipient before sending."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Send immediately (same path as test email) so delivery does not depend on Celery worker.
        result = send_weekly_admissions_digest(triggered_by_user_id=request.user.id)
        http_status = status.HTTP_200_OK if result.get("ok") else status.HTTP_502_BAD_GATEWAY
        return Response(result, status=http_status)


class WeeklyReportRecipientTestSendView(APIView):
    permission_classes = [CommunicationTemplatesPermission]

    def post(self, request, pk):
        recipient = WeeklyReportRecipient.objects.filter(pk=pk).first()
        if not recipient:
            return Response({"detail": "Recipient not found."}, status=status.HTTP_404_NOT_FOUND)
        if not recipient.is_active:
            return Response({"detail": "Recipient is paused. Set to Active first."}, status=status.HTTP_400_BAD_REQUEST)

        ok = send_weekly_digest_to_email(recipient.email)
        if not ok:
            return Response(
                {"detail": f"Failed to send digest to {recipient.email}. Check server logs / SendGrid."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response({"detail": f"Test digest sent to {recipient.email}."}, status=status.HTTP_200_OK)
