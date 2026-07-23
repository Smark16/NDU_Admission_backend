"""Email delivery for the Bursar weekly PDF + Excel report."""
from __future__ import annotations

import logging
from typing import Any

from django.utils import timezone

from ndu_portal.send_grid import send_configurable_email
from payments.bursar_weekly_excel import render_bursar_weekly_excel
from payments.bursar_weekly_metrics import build_bursar_weekly_metrics
from payments.bursar_weekly_pdf import render_bursar_weekly_pdf
from payments.models import BursarWeeklyReportRecipient, BursarWeeklyReportSettings

logger = logging.getLogger(__name__)


def _plain_summary(metrics: dict[str, Any]) -> str:
    return (
        f"Weekly Admissions & Commitment Fee Report — {metrics['report_date']}\n\n"
        f"Admitted: {metrics['admitted_total']:,}\n"
        f"Paid commitment: {metrics['paid_total']:,} ({metrics['collection_rate']}%)\n"
        f"Not paid: {metrics['not_paid_total']:,}\n"
        f"Total collected: {metrics['total_collected_display']}\n"
        f"Revenue at risk: {metrics['revenue_at_risk_display']}\n\n"
        "Full report attached as PDF and Excel."
    )


def send_bursar_report_to_email(to_email: str, metrics: dict[str, Any] | None = None) -> tuple[bool, str]:
    if metrics is None:
        metrics = build_bursar_weekly_metrics()
    pdf_bytes, pdf_filename = render_bursar_weekly_pdf(metrics)
    xlsx_bytes, xlsx_filename = render_bursar_weekly_excel(metrics)
    subject = f"Weekly Admissions & Commitment Fee Report — {metrics['report_date']}"
    body = _plain_summary(metrics)
    ok = send_configurable_email(
        to_email=to_email,
        subject=subject,
        body=body,
        is_html=False,
        attachments=[
            {
                "content": pdf_bytes,
                "filename": pdf_filename,
                "mime_type": "application/pdf",
            },
            {
                "content": xlsx_bytes,
                "filename": xlsx_filename,
                "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            },
        ],
    )
    return ok, subject


def send_bursar_weekly_report(*, triggered_by_user_id: int | None = None) -> dict[str, Any]:
    metrics = build_bursar_weekly_metrics()
    recipients = list(
        BursarWeeklyReportRecipient.objects.filter(is_active=True)
        .exclude(email__isnull=True)
        .exclude(email="")
        .values_list("email", flat=True)
    )
    if not recipients:
        return {
            "ok": False,
            "detail": "No active bursar report recipients configured.",
            "sent": 0,
            "failed": 0,
        }

    sent = 0
    failed = 0
    for email in recipients:
        ok, _ = send_bursar_report_to_email(email, metrics)
        if ok:
            sent += 1
        else:
            failed += 1
            logger.error("Bursar weekly report failed for %s", email)

    detail = f"Bursar weekly report sent to {sent} of {len(recipients)} recipients."
    settings_row = BursarWeeklyReportSettings.get_solo()
    settings_row.last_sent_at = timezone.now()
    settings_row.last_sent_summary = detail[:255]
    settings_row.save(update_fields=["last_sent_at", "last_sent_summary", "updated_at"])

    return {
        "ok": failed == 0 and sent > 0,
        "detail": detail,
        "sent": sent,
        "failed": failed,
        "metrics_summary": {
            "admitted_total": metrics["admitted_total"],
            "paid_total": metrics["paid_total"],
            "not_paid_total": metrics["not_paid_total"],
            "total_collected_display": metrics["total_collected_display"],
            "revenue_at_risk_display": metrics["revenue_at_risk_display"],
        },
        "triggered_by_user_id": triggered_by_user_id,
    }
