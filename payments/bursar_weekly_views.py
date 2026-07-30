"""API for Bursar weekly admissions & commitment fee PDF report."""
from __future__ import annotations

import logging

from django.db import DatabaseError, IntegrityError
from django.http import HttpResponse
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.erp_drf_permissions import FinanceModuleAdminPermission
from payments.bursar_weekly_excel import render_bursar_weekly_excel
from payments.bursar_weekly_metrics import build_bursar_weekly_metrics
from payments.bursar_weekly_pdf import render_bursar_weekly_pdf
from payments.bursar_weekly_send import send_bursar_report_to_email, send_bursar_weekly_report
from payments.models import BursarWeeklyReportRecipient, BursarWeeklyReportSettings

logger = logging.getLogger(__name__)

MIGRATE_HINT = (
    "Bursar weekly report tables are missing. On the server run: "
    "python manage.py migrate payments "
    "&& sudo systemctl restart gunicorn"
)


def _db_error_response(exc: Exception) -> Response:
    logger.exception("Bursar weekly report DB error: %s", exc)
    detail = str(exc)
    if "does not exist" in detail.lower() or "no such table" in detail.lower():
        return Response({"detail": MIGRATE_HINT}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response(
        {"detail": f"Database error: {detail}"},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def _batch_scope_from_request(request) -> tuple[int | None, bool]:
    """
    Returns (batch_id, use_settings_batch).

    If the client sends batch_id, that wins (empty/"all"/"0" = all cohorts).
    Otherwise metrics may fall back to settings.report_batch.
    """
    params = getattr(request, "query_params", {}) or {}
    data = getattr(request, "data", {}) or {}
    if "batch_id" in params or "batch_id" in data:
        raw = params.get("batch_id")
        if raw is None or raw == "":
            raw = data.get("batch_id")
        if raw in (None, "", "all", "0", 0):
            return None, False
        try:
            return int(raw), False
        except (TypeError, ValueError) as exc:
            raise ValueError("batch_id must be an integer, 'all', or empty.") from exc
    return None, True


def _admission_batches_payload() -> list[dict]:
    from admissions.models import Batch

    rows = (
        Batch.objects.all()
        .order_by("-is_active", "-id")
        .values("id", "name", "code", "academic_year", "is_active")[:200]
    )
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "code": r["code"],
            "academic_year": r["academic_year"] or "",
            "is_active": bool(r["is_active"]),
            "label": (
                f"{r['name']} ({r['academic_year']})"
                if r.get("academic_year")
                else r["name"]
            ),
        }
        for r in rows
    ]


class BursarWeeklySettingsSerializer(serializers.ModelSerializer):
    schedule_day_label = serializers.CharField(source="get_schedule_day_display", read_only=True)
    report_batch_id = serializers.IntegerField(allow_null=True, required=False)
    report_batch_label = serializers.SerializerMethodField()

    class Meta:
        model = BursarWeeklyReportSettings
        fields = [
            "is_enabled",
            "schedule_day",
            "schedule_day_label",
            "schedule_hour",
            "schedule_minute",
            "intake_label",
            "report_batch_id",
            "report_batch_label",
            "last_sent_at",
            "last_sent_summary",
        ]

    def get_report_batch_label(self, obj):
        batch = getattr(obj, "report_batch", None)
        if not batch:
            return ""
        if batch.academic_year:
            return f"{batch.name} ({batch.academic_year})"
        return batch.name

    def update(self, instance, validated_data):
        if "report_batch_id" in validated_data:
            batch_id = validated_data.pop("report_batch_id")
            instance.report_batch_id = batch_id
        return super().update(instance, validated_data)


class BursarWeeklyRecipientSerializer(serializers.ModelSerializer):
    class Meta:
        model = BursarWeeklyReportRecipient
        fields = ["id", "email", "name", "is_active", "notes", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class BursarWeeklySettingsView(APIView):
    permission_classes = [FinanceModuleAdminPermission]

    def get(self, request):
        try:
            row = BursarWeeklyReportSettings.get_solo()
            data = BursarWeeklySettingsSerializer(row).data
            data["active_recipients_count"] = BursarWeeklyReportRecipient.objects.filter(
                is_active=True
            ).count()
            data["batches"] = _admission_batches_payload()
            return Response(data)
        except DatabaseError as exc:
            return _db_error_response(exc)

    def patch(self, request):
        try:
            row = BursarWeeklyReportSettings.get_solo()
            ser = BursarWeeklySettingsSerializer(row, data=request.data, partial=True)
            ser.is_valid(raise_exception=True)
            updated = ser.save(updated_by=request.user)
            data = BursarWeeklySettingsSerializer(updated).data
            data["batches"] = _admission_batches_payload()
            return Response(data)
        except DatabaseError as exc:
            return _db_error_response(exc)


class BursarWeeklyRecipientListCreateView(APIView):
    permission_classes = [FinanceModuleAdminPermission]

    def get(self, request):
        try:
            qs = BursarWeeklyReportRecipient.objects.all().order_by("email")
            return Response(BursarWeeklyRecipientSerializer(qs, many=True).data)
        except DatabaseError as exc:
            return _db_error_response(exc)

    def post(self, request):
        try:
            ser = BursarWeeklyRecipientSerializer(data=request.data)
            ser.is_valid(raise_exception=True)
            obj = ser.save(created_by=request.user)
            return Response(BursarWeeklyRecipientSerializer(obj).data, status=status.HTTP_201_CREATED)
        except IntegrityError:
            return Response(
                {"detail": "That email is already on the recipient list."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except DatabaseError as exc:
            return _db_error_response(exc)


class BursarWeeklyRecipientDetailView(APIView):
    permission_classes = [FinanceModuleAdminPermission]

    def patch(self, request, pk):
        try:
            obj = BursarWeeklyReportRecipient.objects.filter(pk=pk).first()
            if not obj:
                return Response({"detail": "Recipient not found."}, status=404)
            ser = BursarWeeklyRecipientSerializer(obj, data=request.data, partial=True)
            ser.is_valid(raise_exception=True)
            updated = ser.save()
            return Response(BursarWeeklyRecipientSerializer(updated).data)
        except DatabaseError as exc:
            return _db_error_response(exc)

    def delete(self, request, pk):
        try:
            obj = BursarWeeklyReportRecipient.objects.filter(pk=pk).first()
            if not obj:
                return Response({"detail": "Recipient not found."}, status=404)
            obj.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except DatabaseError as exc:
            return _db_error_response(exc)


class BursarWeeklyPreviewMetricsView(APIView):
    permission_classes = [FinanceModuleAdminPermission]

    def get(self, request):
        try:
            batch_id, use_settings = _batch_scope_from_request(request)
            metrics = build_bursar_weekly_metrics(
                batch_id=batch_id,
                use_settings_batch=use_settings,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        except DatabaseError as exc:
            return _db_error_response(exc)
        except Exception as exc:
            logger.exception("Bursar metrics failed")
            return Response({"detail": str(exc)}, status=500)

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
            batch_id, use_settings = _batch_scope_from_request(request)
            metrics = build_bursar_weekly_metrics(
                batch_id=batch_id,
                use_settings_batch=use_settings,
            )
            pdf_bytes, filename = render_bursar_weekly_pdf(metrics)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        except DatabaseError as exc:
            return _db_error_response(exc)
        except Exception as exc:
            return Response({"detail": f"PDF generation failed: {exc}"}, status=500)
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class BursarWeeklyDownloadExcelView(APIView):
    permission_classes = [FinanceModuleAdminPermission]

    def get(self, request):
        try:
            batch_id, use_settings = _batch_scope_from_request(request)
            metrics = build_bursar_weekly_metrics(
                batch_id=batch_id,
                use_settings_batch=use_settings,
            )
            xlsx_bytes, filename = render_bursar_weekly_excel(metrics)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        except DatabaseError as exc:
            return _db_error_response(exc)
        except Exception as exc:
            return Response({"detail": f"Excel generation failed: {exc}"}, status=500)
        response = HttpResponse(
            xlsx_bytes,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class BursarWeeklyTestSendView(APIView):
    permission_classes = [FinanceModuleAdminPermission]

    def post(self, request):
        test_email = (request.data.get("email") or request.user.email or "").strip()
        if not test_email:
            return Response({"detail": "email is required."}, status=400)
        try:
            batch_id, use_settings = _batch_scope_from_request(request)
            ok, subject = send_bursar_report_to_email(
                test_email,
                batch_id=batch_id,
                use_settings_batch=use_settings,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        except DatabaseError as exc:
            return _db_error_response(exc)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=500)
        if not ok:
            return Response(
                {"detail": f"Failed to send to {test_email}. Check SendGrid logs."},
                status=500,
            )
        return Response(
            {
                "detail": f"Test bursar report sent to {test_email}.",
                "confirmation": f"Email confirmed: test bursar report sent to {test_email}.",
                "subject": subject,
                "sent_to": test_email,
            }
        )


class BursarWeeklyRecipientTestSendView(APIView):
    permission_classes = [FinanceModuleAdminPermission]

    def post(self, request, pk):
        try:
            recipient = BursarWeeklyReportRecipient.objects.filter(pk=pk).first()
        except DatabaseError as exc:
            return _db_error_response(exc)
        if not recipient:
            return Response({"detail": "Recipient not found."}, status=404)
        try:
            batch_id, use_settings = _batch_scope_from_request(request)
            ok, subject = send_bursar_report_to_email(
                recipient.email,
                batch_id=batch_id,
                use_settings_batch=use_settings,
            )
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
                "confirmation": f"Email confirmed sent to {recipient.email}.",
                "subject": subject,
                "sent_to": recipient.email,
            }
        )


class BursarWeeklySendNowView(APIView):
    permission_classes = [FinanceModuleAdminPermission]

    def post(self, request):
        """
        Send bursar weekly report and prefer a confirmed send result.

        Runs in a worker thread and waits briefly so the UI can show
        "email confirmed sent to …". If still running after the wait,
        returns queued=true while the thread keeps sending.
        Pass {"sync": true} to run fully inline (debug only — can 502).
        """
        import logging
        import threading

        logger = logging.getLogger(__name__)
        user_id = request.user.id
        force_sync = str(request.data.get("sync") or "").lower() in ("1", "true", "yes")
        try:
            batch_id, use_settings = _batch_scope_from_request(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)

        def _do_send() -> dict:
            return send_bursar_weekly_report(
                triggered_by_user_id=user_id,
                batch_id=batch_id,
                use_settings_batch=use_settings,
            )

        if force_sync:
            try:
                result = _do_send()
            except DatabaseError as exc:
                return _db_error_response(exc)
            except Exception as exc:
                logger.exception("Bursar weekly sync send_now failed")
                return Response(
                    {
                        "ok": False,
                        "queued": False,
                        "detail": str(exc) or "Failed to send bursar weekly report.",
                        "confirmation": None,
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
            code = status.HTTP_200_OK if result.get("ok") else status.HTTP_400_BAD_REQUEST
            return Response(result, status=code)

        box: dict = {}

        def _target():
            try:
                box["result"] = _do_send()
                logger.info("Bursar weekly send_now finished: %s", box["result"])
            except Exception as exc:
                logger.exception("Bursar weekly send_now worker failed")
                box["error"] = str(exc) or "Failed to send bursar weekly report."

        worker = threading.Thread(
            target=_target,
            name="bursar-weekly-send",
            daemon=True,
        )
        worker.start()
        # Stay under common nginx/gunicorn timeouts while still confirming send.
        worker.join(timeout=50)

        if "result" in box:
            result = box["result"]
            code = status.HTTP_200_OK if result.get("ok") else status.HTTP_400_BAD_REQUEST
            return Response(result, status=code)
        if "error" in box:
            return Response(
                {
                    "ok": False,
                    "queued": False,
                    "detail": box["error"],
                    "confirmation": None,
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "ok": True,
                "queued": True,
                "via": "thread",
                "detail": (
                    "Report is still generating in the background. "
                    "Check Last sent below in about a minute for confirmation, "
                    "and check recipients' inboxes."
                ),
                "confirmation": None,
            }
        )
