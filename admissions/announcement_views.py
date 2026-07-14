"""Bulk email/SMS communication to applicants (admin Send Communication dialog)."""
from __future__ import annotations

import logging

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Application
from ndu_portal.send_grid import send_configurable_email

logger = logging.getLogger(__name__)


def _personalise(body: str, first_name: str, last_name: str) -> str:
    return (
        (body or "")
        .replace("{first_name}", first_name or "")
        .replace("{last_name}", last_name or "")
    )


def _applications_queryset(data):
    """Resolve recipient applications from explicit IDs or filter fields."""
    raw_ids = data.get("application_ids")
    if raw_ids is not None:
        if not isinstance(raw_ids, list):
            return Application.objects.none()
        try:
            ids = [int(x) for x in raw_ids if int(x) > 0]
        except (TypeError, ValueError):
            return Application.objects.none()
        if not ids:
            return Application.objects.none()
        return (
            Application.objects.filter(pk__in=ids)
            .exclude(email__isnull=True)
            .exclude(email="")
            .select_related("batch", "academic_level")
        )

    qs = Application.objects.exclude(email__isnull=True).exclude(email="").select_related(
        "batch", "academic_level"
    )

    status_filter = (data.get("status") or "all").strip()
    if status_filter and status_filter.lower() != "all":
        qs = qs.filter(status__iexact=status_filter)

    batch_filter = (data.get("batch") or "all").strip()
    if batch_filter and batch_filter.lower() != "all":
        qs = qs.filter(batch__name=batch_filter)

    level_filter = (data.get("academic_level") or "all").strip()
    if level_filter and level_filter.lower() != "all":
        qs = qs.filter(academic_level__name=level_filter)

    return qs


class TestAnnouncementView(APIView):
    """Send one preview email to an address (subject/body from the dialog)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        subject = (request.data.get("subject") or "").strip()
        body = (request.data.get("body") or "").strip()
        test_email = (request.data.get("test_email") or "").strip()

        if not subject or not body:
            return Response({"detail": "Subject and body are required."}, status=400)
        if not test_email:
            return Response({"detail": "test_email is required."}, status=400)

        sample_first = request.user.first_name or "Test"
        sample_last = request.user.last_name or "Applicant"
        personalised = _personalise(body, sample_first, sample_last)
        preview_note = (
            "\n\n---\n(This is a test message. Placeholders were filled with your account name.)\n"
        )
        if send_configurable_email(test_email, subject, personalised + preview_note):
            return Response(
                {"detail": f"Test email sent to {test_email}."},
                status=status.HTTP_200_OK,
            )
        return Response(
            {"detail": "Failed to send test email. Check SendGrid configuration and logs."},
            status=status.HTTP_502_BAD_GATEWAY,
        )


class SendAnnouncementView(APIView):
    """Broadcast email to filtered applicants or explicit application_ids."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        data = request.data
        subject = (data.get("subject") or "").strip()
        body = (data.get("body") or "").strip()
        message_type = (data.get("message_type") or "email").strip().lower()

        if not subject or not body:
            return Response({"detail": "Subject and body are required."}, status=400)

        if message_type not in ("email", "both"):
            return Response(
                {"detail": "Only email is supported at this time."},
                status=400,
            )

        mark_verification_sent = bool(data.get("mark_program_choice_verification_sent"))

        applications = list(_applications_queryset(data))
        if not applications:
            return Response(
                {"detail": "No applicants match the selected filters."},
                status=400,
            )

        sent = failed = 0
        now = timezone.now()
        for app in applications:
            email = (app.email or "").strip()
            if not email:
                failed += 1
                continue
            personalised = _personalise(body, app.first_name, app.last_name)
            if send_configurable_email(email, subject, personalised):
                sent += 1
                if mark_verification_sent:
                    Application.objects.filter(pk=app.pk).update(
                        program_choices_verification_sent_at=now
                    )
            else:
                failed += 1

        detail = f"Sent to {sent} applicant(s)."
        if failed:
            detail += f" {failed} failed."

        return Response(
            {
                "detail": detail,
                "sent": sent,
                "failed": failed,
                "total_matched": len(applications),
            },
            status=status.HTTP_200_OK,
        )
