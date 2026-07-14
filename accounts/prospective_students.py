"""Query helpers for the Prospective Students admin list."""
from __future__ import annotations

from django.db.models import Exists, OuterRef, Q, Subquery
from django.utils import timezone

from accounts.models import User

# Applicants leave the prospective list once they enter the review pipeline.
PROSPECTIVE_EXCLUDED_APPLICATION_STATUSES = (
    "submitted",
    "under_review",
    "accepted",
    "Admitted",
    "rejected",
)


def prospective_applicant_base_queryset():
    """Applicant accounts without a submitted application (no per-row subqueries)."""
    from admissions.models import Application

    excluded = Application.objects.filter(
        applicant=OuterRef("pk"),
        status__in=PROSPECTIVE_EXCLUDED_APPLICATION_STATUSES,
    )
    return User.objects.filter(is_applicant=True).filter(~Exists(excluded))


def annotate_prospective_list_fields(qs):
    """Add draft status fields for a paginated slice only."""
    from admissions.models import Application
    from Drafts.models import DraftApplication

    latest_app_draft = Application.objects.filter(
        applicant=OuterRef("pk"),
        status__iexact="draft",
    ).order_by("-created_at")

    latest_portal_draft = DraftApplication.objects.filter(
        applicant=OuterRef("pk"),
    ).order_by("-updated_at")

    return qs.annotate(
        has_portal_draft=Exists(
            DraftApplication.objects.filter(applicant=OuterRef("pk"))
        ),
        has_app_draft=Exists(
            Application.objects.filter(applicant=OuterRef("pk"), status__iexact="draft")
        ),
        portal_draft_started_at=Subquery(latest_portal_draft.values("updated_at")[:1]),
        app_draft_started_at=Subquery(latest_app_draft.values("created_at")[:1]),
    )


def prospective_applicant_queryset():
    """Annotated queryset — prefer base + annotate on a paginated slice for list views."""
    return annotate_prospective_list_fields(prospective_applicant_base_queryset())


def apply_prospective_list_filters(
    qs,
    *,
    search: str = "",
    status: str = "all",
    date_from: str = "",
    date_to: str = "",
):
    if search:
        qs = qs.filter(
            Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(email__icontains=search)
            | Q(phone__icontains=search)
            | Q(username__icontains=search)
        )
    if date_from:
        qs = qs.filter(date_joined__date__gte=date_from)
    if date_to:
        qs = qs.filter(date_joined__date__lte=date_to)
    if status and status != "all":
        qs = filter_prospective_queryset_by_status(qs, status)
    return qs


def prospective_list_stats() -> dict:
    base = prospective_applicant_base_queryset()
    return {
        "total": base.count(),
        "draft_started": filter_prospective_queryset_by_status(base, "Draft Started").count(),
        "never_started": filter_prospective_queryset_by_status(base, "Never Started").count(),
    }


def prospective_status_label(user) -> str:
    if getattr(user, "has_portal_draft", None) or getattr(user, "has_app_draft", None):
        return "Draft Started"
    return "Never Started"


def prospective_draft_started_at(user):
    portal_at = getattr(user, "portal_draft_started_at", None)
    app_at = getattr(user, "app_draft_started_at", None)
    return portal_at or app_at


def serialize_prospective_student(user) -> dict:
    return {
        "id": user.id,
        "name": user.get_full_name() or user.email,
        "email": user.email,
        "phone": user.phone,
        "date_joined": user.date_joined,
        "last_login": user.last_login,
        "status": prospective_status_label(user),
        "draft_started_at": prospective_draft_started_at(user),
        "days_since_joined": (timezone.now() - user.date_joined).days if user.date_joined else None,
    }


def filter_prospective_queryset_by_status(qs, status_filter: str):
    from admissions.models import Application
    from Drafts.models import DraftApplication

    if status_filter == "Draft Started":
        return qs.filter(
            Q(pk__in=DraftApplication.objects.values("applicant"))
            | Q(pk__in=Application.objects.filter(status__iexact="draft").values("applicant"))
        )
    if status_filter == "Never Started":
        return qs.exclude(pk__in=DraftApplication.objects.values("applicant")).exclude(
            pk__in=Application.objects.values("applicant")
        )
    return qs
