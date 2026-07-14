"""
Job opening lifecycle helpers.

Scheduling uses:
- published_date  → when the vacancy becomes visible / open for applications
- application_deadline → last calendar day applications are accepted
- status DRAFT / OPEN / CLOSED / … for manual overrides (CANCELLED, FILLED stay untouched)
"""
from __future__ import annotations

from datetime import date

from django.db.models import QuerySet

from hr.hiring.models import JobOpening

MAX_JOB_DESCRIPTION_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_PDF_CONTENT_TYPES = {
    "application/pdf",
    "application/x-pdf",
    "application/octet-stream",
}


def today_local() -> date:
    from django.utils import timezone

    return timezone.localdate()


def is_within_application_window(opening: JobOpening, on: date | None = None) -> bool:
    """True while the vacancy should accept applications (inclusive of deadline day)."""
    day = on or today_local()
    return opening.published_date <= day <= opening.application_deadline


def suggested_status_for_dates(
    published_date: date,
    application_deadline: date,
    on: date | None = None,
) -> str:
    """Derive automation-friendly status from the schedule window."""
    day = on or today_local()
    if application_deadline < day:
        return "CLOSED"
    if published_date > day:
        return "DRAFT"
    return "OPEN"


def public_openings_queryset(base: QuerySet | None = None) -> QuerySet:
    """Careers portal listing: live OPEN vacancies inside the date window."""
    day = today_local()
    qs = base if base is not None else JobOpening.objects.all()
    return (
        qs.select_related("department")
        .filter(
            status="OPEN",
            published_date__lte=day,
            application_deadline__gte=day,
        )
        .order_by("-published_date", "title")
    )


def validate_job_description_pdf(uploaded_file) -> None:
    """Raise ValueError if the upload is not an acceptable PDF."""
    if uploaded_file is None:
        raise ValueError("Job description PDF is required.")

    name = (getattr(uploaded_file, "name", "") or "").lower()
    if not name.endswith(".pdf"):
        raise ValueError("Job description must be a PDF file (.pdf).")

    size = getattr(uploaded_file, "size", None)
    if size is not None and size > MAX_JOB_DESCRIPTION_BYTES:
        raise ValueError("Job description PDF must be 10 MB or smaller.")

    content_type = (getattr(uploaded_file, "content_type", "") or "").lower()
    if content_type and content_type not in ALLOWED_PDF_CONTENT_TYPES:
        raise ValueError("Job description must be a PDF file.")


def sync_job_opening_statuses(on: date | None = None) -> dict:
    """
    Idempotent status sync used by Celery beat.

    - DRAFT → OPEN when opens-on date is reached and deadline has not passed
    - OPEN  → CLOSED when the deadline day has ended
    Never touches CANCELLED or FILLED.
    """
    day = on or today_local()

    to_open = JobOpening.objects.filter(
        status="DRAFT",
        published_date__lte=day,
        application_deadline__gte=day,
    )
    opened_ids = list(to_open.values_list("id", flat=True))
    opened = to_open.update(status="OPEN")

    to_close = JobOpening.objects.filter(
        status__in=["OPEN", "DRAFT"],
        application_deadline__lt=day,
    )
    closed_ids = list(to_close.values_list("id", flat=True))
    closed = to_close.update(status="CLOSED")

    return {
        "date": day.isoformat(),
        "opened": opened,
        "opened_ids": opened_ids,
        "closed": closed,
        "closed_ids": closed_ids,
    }
