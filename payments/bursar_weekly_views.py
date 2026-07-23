"""API for Bursar weekly admissions & commitment fee PDF report."""
from __future__ import annotations

from django.http import HttpResponse
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.erp_drf_permissions import FinanceModuleAdminPermission
from payments.bursar_weekly_metrics import build_bursar_weekly_metrics
from payments.bursar_weekly_pdf import render_bursar_weekly_pdf
from payments.bursar_weekly_send import send_bursar_report_to_email, send_bursar_weekly_report
from payments.models import BursarWeeklyReportRecipient, BursarWeeklyReportSettings
from payments.tasks import celery_send_bursar_weekly_report


class BursarWeeklySettingsSerializer(serializers.ModelSerializer):
    schedule_day_label = serializers.CharField(source="get_schedule_day_display", read_only=True)

    class Meta:
        model = BursarWeeklyReportSettings
        fields = [
            "is_enabled",
            "schedule_day",
            "schedule_day_label",
            "schedule_hour",
            "schedule_minute",
            "intake_label",
            "last_sent_at",
            "last_sent_summary",
        ]


class BursarWeeklyRecipientSerializer(serializers.ModelSerializer):
    class Meta:
        model = BursarWeeklyReportRecipient
        fields = ["id", "email", "name", "is_active", "notes", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class BursarWeeklySettingsView(APIView):
    permission_classes = [FinanceModuleAdminPermission]

    def get(self, request):
        row = BursarWeeklyReportSettings.get_solo()
        data = BursarWeeklySettingsSerializer(row).data
        data["active_recipients_count"] = BursarWeeklyReportRecipient.objects.filter(
            is_active=True
        ).count()
        return Response(data)

    def patch(self, request):
        row = BursarWeeklyReportSettings.get_solo()
        ser = BursarWeeklySettingsSerializer(row, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        updated = ser.save(updated_by=request.user)
        return Response(BursarWeeklySettingsSerializer(updated).data)


class BursarWeeklyRecipientListCreateView(APIView):
    permission_classes = [FinanceModuleAdminPermission]

    def get(self, request):
        qs = BursarWeeklyReportRecipient.objects.all().order_by("email")
        return Response(BursarWeeklyRecipientSerializer(qs, many=True).data)

    def post(self, request):
        ser = BursarWeeklyRecipientSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        obj = ser.save(created_by=request.user)
        return Response(BursarWeeklyRecipientSerializer(obj).data, status=status.HTTP_201_CREATED)


class BursarWeeklyRecipientDetailView(APIView):
    permission_classes = [FinanceModuleAdminPermission]

    def patch(self, request, pk):
        obj = BursarWeeklyReportRecipient.objects.filter(pk=pk).first()
        if not obj:
            return Response({"detail": "Recipient not found."}, status=404)
        ser = BursarWeeklyRecipientSerializer(obj, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        updated = ser.save()
        return Response(BursarWeeklyRecipientSerializer(updated).data)

    def delete(self, request, pk):
        obj = BursarWeeklyReportRecipient.objects.filter(pk=pk).first()
        if not obj:
            return Response({"detail": "Recipient not found."}, status=404)
        obj.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class BursarWeeklyPreviewMetricsView(APIView):
    permission_classes = [FinanceModuleAdminPermission]

    def get(self, request):
        metrics = build_bursar_weekly_metrics()
        # Drop non-JSON-friendly Decimals for API preview
        def scrub(obj):
            from decimal import Decimal

            if isinstance(obj, dict):
                return {k: scrub(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [scrub(v) for v in obj]
            if isinstance(obj, Decimal):
                return float(obj)
            return obj

        return Response({"metrics": scrub(metrics)})


class BursarWeeklyDownloadPdfView(APIView):
    permission_classes = [FinanceModuleAdminPermission]

    def get(self, request):
        try:
            metrics = build_bursar_weekly_metrics()
            pdf_bytes, filename = render_bursar_weekly_pdf(metrics)
        except Exception as exc:
            return Response({"detail": f"PDF generation failed: {exc}"}, status=500)
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class BursarWeeklyTestSendView(APIView):
    permission_classes = [FinanceModuleAdminPermission]

    def post(self, request):
        test_email = (request.data.get("email") or request.user.email or "").strip()
        if not test_email:
            return Response({"detail": "email is required."}, status=400)
        try:
            ok, subject = send_bursar_report_to_email(test_email)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=500)
        if not ok:
            return Response(
                {"detail": f"Failed to send to {test_email}. Check SendGrid logs."},
                status=500,
            )
        return Response(
            {"detail": f"Test bursar report sent to {test_email}.", "subject": subject, "sent_to": test_email}
        )


class BursarWeeklyRecipientTestSendView(APIView):
    permission_classes = [FinanceModuleAdminPermission]

    def post(self, request, pk):
        recipient = BursarWeeklyReportRecipient.objects.filter(pk=pk).first()
        if not recipient:
            return Response({"detail": "Recipient not found."}, status=404)
        try:
            ok, subject = send_bursar_report_to_email(recipient.email)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=500)
        if not ok:
            return Response(
                {"detail": f"Failed to send to {recipient.email}."},
                status=500,
            )
        return Response(
            {
                "detail": f"Test bursar report sent to {recipient.email}.",
                "subject": subject,
                "sent_to": recipient.email,
            }
        )


class BursarWeeklySendNowView(APIView):
    permission_classes = [FinanceModuleAdminPermission]

    def post(self, request):
        async_mode = str(request.data.get("async") or "").lower() in ("1", "true", "yes")
        if async_mode:
            celery_send_bursar_weekly_report.delay(triggered_by_user_id=request.user.id)
            return Response({"detail": "Bursar weekly report queued."})
        result = send_bursar_weekly_report(triggered_by_user_id=request.user.id)
        code = status.HTTP_200_OK if result.get("ok") else status.HTTP_400_BAD_REQUEST
        return Response(result, status=code)
