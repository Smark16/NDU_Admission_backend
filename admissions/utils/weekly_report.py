"""Weekly admissions digest — metrics and email delivery."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone

from admissions.email_templates import render_email_template
from admissions.models import Application, EmailTemplate, WeeklyReportRecipient, WeeklyReportSettings
from ndu_portal.send_grid import send_configurable_email

ADMITTED_STATUSES = ["Admitted", "admitted", "accepted"]


def week_bounds_for(reference: date | None = None) -> tuple[date, date]:
    """Monday–Sunday week containing reference date (local calendar)."""
    ref = reference or timezone.localdate()
    monday = ref - timedelta(days=ref.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def build_weekly_report_metrics(
    week_start: date,
    week_end: date,
) -> dict[str, Any]:
    base = Application.objects.exclude(status="draft")
    week_qs = base.filter(
        created_at__date__gte=week_start,
        created_at__date__lte=week_end,
    )

    prev_start = week_start - timedelta(days=7)
    prev_end = week_end - timedelta(days=7)
    prev_week_count = base.filter(
        created_at__date__gte=prev_start,
        created_at__date__lte=prev_end,
    ).count()
    received = week_qs.count()
    received_delta = received - prev_week_count

    admitted_filter = Q(status__in=ADMITTED_STATUSES)
    agg = week_qs.aggregate(
        submitted=Count("id", filter=Q(status="submitted")),
        under_review=Count("id", filter=Q(status="under_review")),
        admitted=Count("id", filter=admitted_filter),
        rejected=Count("id", filter=Q(status__iexact="rejected")),
        direct_entry=Count("id", filter=Q(is_direct_entry=True)),
    )
    pipeline = base.aggregate(
        total_pipeline=Count("id"),
        total_pending=Count("id", filter=Q(status__in=["submitted", "under_review"])),
        total_admitted=Count("id", filter=admitted_filter),
        total_rejected=Count("id", filter=Q(status__iexact="rejected")),
    )

    horizon_url = (getattr(settings, "ERP_FRONTEND_URL", "") or "").rstrip("/")
    report_url = f"{horizon_url}/admin/reports/all-applicants" if horizon_url else ""

    delta_label = f"+{received_delta}" if received_delta > 0 else str(received_delta)

    return {
        "week_start": week_start.strftime("%d %b %Y"),
        "week_end": week_end.strftime("%d %b %Y"),
        "applications_received": received,
        "applications_received_delta": delta_label,
        "submitted": agg["submitted"] or 0,
        "under_review": agg["under_review"] or 0,
        "admitted": agg["admitted"] or 0,
        "rejected": agg["rejected"] or 0,
        "direct_entry": agg["direct_entry"] or 0,
        "online": received - (agg["direct_entry"] or 0),
        "total_pipeline": pipeline["total_pipeline"] or 0,
        "total_pending": pipeline["total_pending"] or 0,
        "total_admitted": pipeline["total_admitted"] or 0,
        "total_rejected": pipeline["total_rejected"] or 0,
        "report_url": report_url,
        "generated_at": timezone.localtime().strftime("%d %b %Y %H:%M %Z"),
    }


def send_weekly_digest_to_email(to_email: str, metrics: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Returns (success, subject)."""
    if metrics is None:
        week_start, week_end = week_bounds_for()
        metrics = build_weekly_report_metrics(week_start, week_end)

    subject, html_body, plain_text = render_email_template(
        EmailTemplate.KEY_WEEKLY_ADMISSIONS_DIGEST,
        metrics,
    )
    ok = send_configurable_email(
        to_email=to_email,
        subject=subject,
        body=html_body,
        is_html=True,
        plain_text_fallback=plain_text,
    )
    return ok, subject


def send_weekly_admissions_digest(*, triggered_by_user_id: int | None = None) -> dict[str, Any]:
    """Send digest to all active recipients. Returns summary dict."""
    week_start, week_end = week_bounds_for()
    metrics = build_weekly_report_metrics(week_start, week_end)

    recipients = list(
        WeeklyReportRecipient.objects.filter(is_active=True)
        .exclude(email__isnull=True)
        .exclude(email="")
        .values_list("email", flat=True)
    )
    if not recipients:
        return {
            "ok": False,
            "detail": "No active recipients configured.",
            "sent": 0,
            "failed": 0,
            "total": 0,
        }

    sent = 0
    failed = 0
    sent_emails: list[str] = []
    failed_emails: list[str] = []
    for email in recipients:
        ok, _subject = send_weekly_digest_to_email(email, metrics)
        if ok:
            sent += 1
            sent_emails.append(email)
        else:
            failed += 1
            failed_emails.append(email)

    settings_row = WeeklyReportSettings.get_solo()
    sent_at = timezone.now()
    settings_row.last_sent_at = sent_at
    settings_row.last_sent_summary = f"{sent}/{len(recipients)} delivered"
    if triggered_by_user_id:
        settings_row.updated_by_id = triggered_by_user_id
    settings_row.save(update_fields=["last_sent_at", "last_sent_summary", "updated_by", "updated_at"])

    subject, _, _ = render_email_template(EmailTemplate.KEY_WEEKLY_ADMISSIONS_DIGEST, metrics)

    detail = f"Weekly digest sent to {sent} of {len(recipients)} recipients."
    if failed_emails:
        detail += f" Failed: {', '.join(failed_emails)}."

    return {
        "ok": failed == 0,
        "detail": detail,
        "sent": sent,
        "failed": failed,
        "sent_emails": sent_emails,
        "failed_emails": failed_emails,
        "total": len(recipients),
        "week_start": metrics["week_start"],
        "week_end": metrics["week_end"],
        "subject": subject,
        "sent_at": sent_at.isoformat(),
    }
