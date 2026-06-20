"""Query helpers for the Prospective Students admin list."""
from __future__ import annotations

from django.db.models import OuterRef, Subquery, Value
from django.db.models.functions import Coalesce

from accounts.models import User


def _last_audit_login_subquery():
    from audit.models import AuditLog

    return AuditLog.objects.filter(
        user=OuterRef("pk"),
        action="login",
    ).order_by("-timestamp").values("timestamp")[:1]

# Applicants leave the prospective list once they enter the review pipeline.
PROSPECTIVE_EXCLUDED_APPLICATION_STATUSES = (
    "submitted",
    "under_review",
    "accepted",
    "Admitted",
    "rejected",
)


def prospective_applicant_queryset():
    """
    Applicant accounts that have not submitted an application yet.

    In-progress work lives in DraftApplication (portal autosave), not always in
    Application rows — annotate both sources for Draft Started detection.
    """
    from admissions.models import Application
    from Drafts.models import DraftApplication

    latest_app_draft = Application.objects.filter(
        applicant=OuterRef("pk"),
        status__iexact="draft",
    ).order_by("-created_at")

    latest_portal_draft = DraftApplication.objects.filter(
        applicant=OuterRef("pk"),
    ).order_by("-updated_at")

    return (
        User.objects.filter(is_applicant=True)
        .exclude(
            pk__in=Application.objects.filter(
                status__in=PROSPECTIVE_EXCLUDED_APPLICATION_STATUSES
            ).values("applicant")
        )
        .annotate(
            app_draft_status=Subquery(latest_app_draft.values("status")[:1]),
            app_draft_started_at=Subquery(latest_app_draft.values("created_at")[:1]),
            portal_draft_id=Subquery(latest_portal_draft.values("id")[:1]),
            portal_draft_started_at=Subquery(latest_portal_draft.values("updated_at")[:1]),
            has_draft=Coalesce(
                Subquery(latest_app_draft.values("status")[:1]),
                Value("no_application"),
            ),
            draft_started_at=Subquery(latest_app_draft.values("created_at")[:1]),
            audit_last_login=Subquery(_last_audit_login_subquery()),
        )
    )


def prospective_status_label(user) -> str:
    if getattr(user, "portal_draft_id", None):
        return "Draft Started"
    if (getattr(user, "app_draft_status", None) or "").lower() == "draft":
        return "Draft Started"
    if getattr(user, "has_draft", None) == "draft":
        return "Draft Started"
    return "Never Started"


def prospective_draft_started_at(user):
    portal_at = getattr(user, "portal_draft_started_at", None)
    app_at = getattr(user, "app_draft_started_at", None) or getattr(
        user, "draft_started_at", None
    )
    return portal_at or app_at


def filter_prospective_queryset_by_status(qs, status_filter: str):
    from django.db.models import Q

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
