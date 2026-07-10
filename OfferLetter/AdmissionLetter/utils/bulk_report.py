"""Bulk offer-letter job reporting (CSV export)."""
from __future__ import annotations

import csv
import io
from typing import Any

from admissions.models import AdmittedStudent, Application


def append_bulk_report_row(
    job: dict[str, Any],
    application_id: int,
    outcome: str,
    detail: str = "",
) -> None:
    rows = job.setdefault("report_rows", [])
    rows.append(
        {
            "application_id": application_id,
            "outcome": outcome,
            "detail": (detail or "").strip(),
        }
    )


def _student_label(app: Application | None, admitted: AdmittedStudent | None) -> str:
    if app is not None:
        parts = [app.first_name or "", app.middle_name or "", app.last_name or ""]
        name = " ".join(p for p in parts if p).strip()
        if name:
            return name
    if admitted is not None and admitted.application_id:
        return f"Application #{admitted.application_id}"
    return ""


def build_bulk_offer_letter_csv(job: dict[str, Any], *, errors_only: bool = False) -> str:
    """Build CSV text for a completed bulk offer-letter job."""
    rows: list[dict[str, Any]] = list(job.get("report_rows") or [])
    if not rows and job.get("errors"):
        rows = [
            {
                "application_id": item.get("id"),
                "outcome": "failed",
                "detail": item.get("detail") or "Generation failed.",
            }
            for item in job["errors"]
        ]

    if errors_only:
        rows = [r for r in rows if r.get("outcome") == "failed"]

    app_ids = [int(r["application_id"]) for r in rows if r.get("application_id") is not None]
    admitted_by_app: dict[int, AdmittedStudent] = {}
    if app_ids:
        for adm in AdmittedStudent.objects.filter(application_id__in=app_ids).select_related(
            "admitted_program",
            "admitted_batch",
            "application",
        ):
            admitted_by_app[adm.application_id] = adm

    apps_by_id: dict[int, Application] = {}
    missing_ids = [aid for aid in app_ids if aid not in admitted_by_app]
    if missing_ids:
        for app in Application.objects.filter(pk__in=missing_ids).only(
            "id",
            "first_name",
            "middle_name",
            "last_name",
            "admission_letter_pdf",
        ):
            apps_by_id[app.id] = app

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "application_id",
            "student_id",
            "reg_no",
            "student_name",
            "program",
            "admission_intake",
            "outcome",
            "error_reason",
            "pdf_available_now",
        ]
    )

    for row in rows:
        app_id = row.get("application_id")
        if app_id is None:
            continue
        try:
            app_id_int = int(app_id)
        except (TypeError, ValueError):
            continue

        admitted = admitted_by_app.get(app_id_int)
        app = apps_by_id.get(app_id_int) or (admitted.application if admitted else None)
        has_pdf = bool(
            app
            and getattr(app, "admission_letter_pdf", None)
            and getattr(app.admission_letter_pdf, "name", None)
        )
        outcome = str(row.get("outcome") or "")
        detail = str(row.get("detail") or "")

        writer.writerow(
            [
                app_id_int,
                (admitted.student_id if admitted else "") or "",
                (admitted.reg_no if admitted else "") or "",
                _student_label(app, admitted),
                (admitted.admitted_program.name if admitted and admitted.admitted_program else "")
                or "",
                (admitted.admitted_batch.name if admitted and admitted.admitted_batch else "")
                or "",
                outcome,
                detail if outcome == "failed" else "",
                "yes" if has_pdf else "no",
            ]
        )

    return buffer.getvalue()
