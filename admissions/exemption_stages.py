"""Multi-stage course exemption review pipeline (HOD → Dean → AR; Accounts after HOD)."""
from __future__ import annotations

from django.utils import timezone

from accounts.super_admin import user_is_super_admin

EXEMPTION_STAGE_CHOICES = [
    ("pending", "Pending"),
    ("approved", "Approved"),
    ("rejected", "Rejected"),
]

EXEMPTION_ACCOUNTS_STATUS_CHOICES = [
    ("pending", "Pending"),
    ("billed", "Billed"),
    ("confirmed", "Confirmed"),
]

EXEMPTION_REVIEW_STAGES = ("hod", "dean", "ar")
EXEMPTION_PIPELINE_STAGES = ("hod", "dean", "ar", "accounts")


def _stage_status_attr(stage: str) -> str:
    if stage == "accounts":
        return "accounts_status"
    return f"{stage}_status"


def exemption_stage_status(change_request, stage: str) -> str:
    return getattr(change_request, _stage_status_attr(stage), "pending")


def prior_exemption_stage_approved(change_request, stage: str) -> bool:
    if change_request.change_type != "exemption":
        return True
    if stage == "hod":
        return True
    if stage == "dean":
        return change_request.hod_status == "approved"
    if stage == "ar":
        return change_request.dean_status == "approved"
    # Accounts bills as soon as HOD has approved papers (Dean/AR may still be reviewing).
    if stage == "accounts":
        return change_request.hod_status == "approved"
    return False


def exemption_stage_is_actionable(change_request, stage: str) -> bool:
    if change_request.change_type != "exemption":
        return False
    if not prior_exemption_stage_approved(change_request, stage):
        return False
    if stage == "accounts":
        return change_request.accounts_status == "pending"
    return exemption_stage_status(change_request, stage) == "pending"


def compute_exemption_pipeline_from_lines(lines) -> tuple[str, str, str]:
    """Derive HOD / Dean / AR status from per-paper decisions (source of truth)."""
    from admissions.models import ExemptionRequestLine

    if not lines:
        return "pending", "pending", "pending"

    dec = ExemptionRequestLine
    pending = dec.DECISION_PENDING
    approved = dec.DECISION_APPROVED
    rejected = dec.DECISION_REJECTED

    if all(l.decision == rejected for l in lines):
        hod = "rejected"
    elif any(l.decision == pending for l in lines):
        hod = "pending"
    elif any(l.decision == approved for l in lines):
        hod = "approved"
    else:
        hod = "pending"

    hod_approved = [l for l in lines if l.decision == approved]
    if hod != "approved" or not hod_approved:
        return hod, "pending", "pending"

    if any(l.dean_decision == pending for l in hod_approved):
        dean = "pending"
    elif all(l.dean_decision == rejected for l in hod_approved):
        dean = "rejected"
    elif any(l.dean_decision == approved for l in hod_approved):
        dean = "approved"
    else:
        dean = "pending"

    dean_approved = [l for l in hod_approved if l.dean_decision == approved]
    if dean != "approved" or not dean_approved:
        return hod, dean, "pending"

    if any(l.ar_decision == pending for l in dean_approved):
        ar = "pending"
    elif all(l.ar_decision == rejected for l in dean_approved):
        ar = "rejected"
    elif any(l.ar_decision == approved for l in dean_approved):
        ar = "approved"
    else:
        ar = "pending"

    return hod, dean, ar


def sync_exemption_overall_status(change_request) -> None:
    """Keep legacy ``status`` aligned with pipeline outcomes."""
    if change_request.change_type != "exemption":
        return
    if (
        change_request.hod_status == "rejected"
        or change_request.dean_status == "rejected"
        or change_request.ar_status == "rejected"
    ):
        change_request.status = "rejected"
        return
    if change_request.ar_status == "approved":
        change_request.status = "approved"
        return
    change_request.status = "pending"


def apply_exemption_stage_review(
    change_request,
    *,
    stage: str,
    action: str,
    reviewer,
    notes: str = "",
) -> None:
    """Record approve/reject for dean or AR (HOD uses dedicated paper logic)."""
    now = timezone.now()
    status_val = "approved" if action == "approve" else "rejected"
    setattr(change_request, _stage_status_attr(stage), status_val)
    setattr(change_request, f"{stage}_reviewed_by", reviewer)
    setattr(change_request, f"{stage}_reviewed_at", now)
    setattr(change_request, f"{stage}_notes", notes or "")
    sync_exemption_overall_status(change_request)


def filter_exemption_requests_for_stage(qs, stage: str, status_filter: str | None):
    """Narrow exemption queryset for admin list tabs."""
    if not stage:
        return qs
    stage = stage.strip().lower()
    if stage not in EXEMPTION_PIPELINE_STAGES:
        return qs

    if stage == "hod":
        if status_filter == "pending":
            return qs.filter(hod_status="pending")
        if status_filter == "approved":
            return qs.filter(hod_status="approved")
        if status_filter == "rejected":
            return qs.filter(hod_status="rejected")
        return qs

    if stage == "dean":
        qs = qs.filter(hod_status="approved")
        if status_filter == "pending":
            return qs.filter(dean_status="pending")
        if status_filter == "approved":
            return qs.filter(dean_status="approved")
        if status_filter == "rejected":
            return qs.filter(dean_status="rejected")
        return qs

    if stage == "ar":
        qs = qs.filter(dean_status="approved")
        if status_filter == "pending":
            return qs.filter(ar_status="pending")
        if status_filter == "approved":
            return qs.filter(ar_status="approved")
        if status_filter == "rejected":
            return qs.filter(ar_status="rejected")
        return qs

    # accounts — visible once HOD has approved (parallel with Dean/AR)
    qs = qs.filter(hod_status="approved")
    if status_filter == "pending":
        return qs.filter(accounts_status="pending")
    if status_filter == "approved":
        return qs.filter(accounts_status="billed")
    if status_filter == "rejected":
        return qs.filter(accounts_status="confirmed")
    return qs


def user_can_review_exemption_stage(user, stage: str) -> bool:
    from admissions.permissions import (
        user_can_approve_exemption_requests,
        user_can_bill_exemption_accounts,
        user_can_review_exemption_ar,
        user_can_review_exemption_dean,
    )

    if not user.is_authenticated:
        return False
    if user_is_super_admin(user):
        return True
    if stage == "hod":
        return user_can_approve_exemption_requests(user)
    if stage == "dean":
        return user_can_review_exemption_dean(user)
    if stage == "ar":
        return user_can_review_exemption_ar(user)
    if stage == "accounts":
        return user_can_bill_exemption_accounts(user)
    return False
