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
    min_pct = metrics.get("min_registration_tuition_pct")
    pct_label = f"{min_pct:g}%" if min_pct is not None else "configured %"
    return (
        f"Weekly Admissions & Commitment Fee Report — {metrics['report_date']}\n"
        f"Scope: {metrics.get('batch_scope_label') or metrics.get('intake_label')}\n\n"
        f"Admitted: {metrics['admitted_total']:,}\n"
        f"Paid commitment: {metrics['paid_total']:,} ({metrics['collection_rate']}%)\n"
        f"Not paid commitment: {metrics['not_paid_total']:,}\n"
        f"Ready for registration (≥ {pct_label} tuition): "
        f"{metrics.get('registration_ready_total', 0):,} "
        f"({metrics.get('registration_ready_rate', 0)}%)\n"
        f"Active temporary access passes: "
        f"{metrics.get('temporary_access_active_total', 0):,}\n"
        f"Total collected: {metrics['total_collected_display']}\n"
        f"Revenue at risk: {metrics['revenue_at_risk_display']}\n\n"
        "Full report attached as PDF and Excel."
    )


def _build_attachments(metrics: dict[str, Any]) -> tuple[list[dict[str, Any]], str, str]:
    pdf_bytes, pdf_filename = render_bursar_weekly_pdf(metrics)
    xlsx_bytes, xlsx_filename = render_bursar_weekly_excel(metrics)
    attachments = [
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
    ]
    return attachments, pdf_filename, xlsx_filename


def send_bursar_report_to_email(
    to_email: str,
    metrics: dict[str, Any] | None = None,
    *,
    attachments: list[dict[str, Any]] | None = None,
    batch_id: int | None = None,
    use_settings_batch: bool = True,
) -> tuple[bool, str]:
    if metrics is None:
        metrics = build_bursar_weekly_metrics(
            batch_id=batch_id,
            use_settings_batch=use_settings_batch,
        )
    if attachments is None:
        attachments, _, _ = _build_attachments(metrics)
    subject = f"Weekly Admissions & Commitment Fee Report — {metrics['report_date']}"
    body = _plain_summary(metrics)
    ok = send_configurable_email(
        to_email=to_email,
        subject=subject,
        body=body,
        is_html=False,
        attachments=attachments,
    )
    return ok, subject


def send_bursar_weekly_report(
    *,
    triggered_by_user_id: int | None = None,
    batch_id: int | None = None,
    use_settings_batch: bool = True,
) -> dict[str, Any]:
    metrics = build_bursar_weekly_metrics(
        batch_id=batch_id,
        use_settings_batch=use_settings_batch,
    )
    recipients = list(
        BursarWeeklyReportRecipient.objects.filter(is_active=True)
        .exclude(email__isnull=True)
        .exclude(email="")
        .values_list("email", flat=True)
    )
    if not recipients:
        return {
            "ok": False,
            "queued": False,
            "detail": "No active bursar report recipients configured.",
            "confirmation": None,
            "sent": 0,
            "failed": 0,
            "sent_to": [],
            "failed_to": [],
        }

    # Render PDF/Excel once — re-rendering per recipient was causing gunicorn timeouts (502).
    attachments, _, _ = _build_attachments(metrics)

    sent_to: list[str] = []
    failed_to: list[str] = []
    for email in recipients:
        ok, _ = send_bursar_report_to_email(email, metrics, attachments=attachments)
        if ok:
            sent_to.append(email)
        else:
            failed_to.append(email)
            logger.error("Bursar weekly report failed for %s", email)

    sent = len(sent_to)
    failed = len(failed_to)
    if sent and not failed:
        confirmation = (
            f"Email confirmed sent to {sent} recipient(s): {', '.join(sent_to)}."
        )
        detail = confirmation
    elif sent and failed:
        confirmation = (
            f"Email confirmed sent to {sent} recipient(s): {', '.join(sent_to)}. "
            f"Failed: {', '.join(failed_to)}."
        )
        detail = confirmation
    else:
        confirmation = None
        detail = (
            f"Failed to send bursar report to any of {len(recipients)} recipient(s): "
            f"{', '.join(failed_to)}."
        )

    settings_row = BursarWeeklyReportSettings.get_solo()
    settings_row.last_sent_at = timezone.now()
    settings_row.last_sent_summary = (confirmation or detail)[:255]
    settings_row.save(update_fields=["last_sent_at", "last_sent_summary", "updated_at"])

    return {
        "ok": failed == 0 and sent > 0,
        "queued": False,
        "detail": detail,
        "confirmation": confirmation,
        "sent": sent,
        "failed": failed,
        "sent_to": sent_to,
        "failed_to": failed_to,
        "metrics_summary": {
            "admitted_total": metrics["admitted_total"],
            "paid_total": metrics["paid_total"],
            "not_paid_total": metrics["not_paid_total"],
            "registration_ready_total": metrics.get("registration_ready_total"),
            "batch_scope_label": metrics.get("batch_scope_label"),
            "total_collected_display": metrics["total_collected_display"],
            "revenue_at_risk_display": metrics["revenue_at_risk_display"],
        },
        "triggered_by_user_id": triggered_by_user_id,
    }
