"""Staff-assisted application entry for prospective registrants."""
from __future__ import annotations

from django.shortcuts import get_object_or_404

from accounts.erp_drf_permissions import user_has_any_erp_perm
from accounts.models import User
from accounts.prospective_students import PROSPECTIVE_EXCLUDED_APPLICATION_STATUSES
from accounts.super_admin import user_is_super_admin
from admissions.models import Application


def staff_may_assist_applicant(staff, applicant: User) -> bool:
    if not staff or not staff.is_authenticated:
        return False
    if user_is_super_admin(staff):
        return True
    if user_has_any_erp_perm(
        staff,
        "access_admissions",
        "approve_admissions",
        "manage_batches",
    ):
        return True
    return staff.has_perm("accounts.view_user")


def get_assistable_applicant(staff, applicant_id: int) -> User:
    applicant = get_object_or_404(User, pk=applicant_id, is_applicant=True)
    if not staff_may_assist_applicant(staff, applicant):
        from rest_framework.exceptions import PermissionDenied

        raise PermissionDenied("You do not have permission to assist this applicant.")
    if Application.objects.filter(
        applicant=applicant,
        status__in=PROSPECTIVE_EXCLUDED_APPLICATION_STATUSES,
    ).exists():
        from rest_framework.exceptions import ValidationError

        raise ValidationError(
            {"detail": "This applicant already has a submitted application."}
        )
    return applicant


def resolve_assisted_applicant(request):
    """
    Return the applicant account staff are acting for, or the logged-in applicant.
    """
    raw_id = (
        request.data.get("applicant_id")
        or request.query_params.get("applicant_id")
    )
    if raw_id in (None, ""):
        return request.user, None

    try:
        applicant_id = int(raw_id)
    except (TypeError, ValueError):
        from rest_framework.exceptions import ValidationError

        raise ValidationError({"detail": "Invalid applicant_id."})

    applicant = get_assistable_applicant(request.user, applicant_id)
    return applicant, request.user


def draft_progress_payload(draft) -> dict:
    """Simple checklist for staff follow-up on phone."""
    if not draft:
        return {
            "steps_complete": 0,
            "steps_total": 8,
            "checklist": [],
        }

    checks = [
        ("Personal details", bool(draft.first_name and draft.last_name and draft.phone)),
        ("Campus & level", bool(draft.campus_id and draft.academic_level_id)),
        (
            "Programme choices",
            draft.program_choices.exists() if hasattr(draft, "program_choices") else False,
        ),
        ("O-Level", draft.has_olevel or bool(draft.olevel_data)),
        ("A-Level", draft.has_alevel or bool(draft.alevel_data)),
        ("Passport photo", bool(draft.passport_photo)),
        (
            "Supporting documents",
            bool(
                draft.olevel_document
                or draft.alevel_document
                or draft.other_documents
                or draft.other_document_files.exists()
            ),
        ),
        ("Application fee", bool(draft.application_fee_paid)),
    ]
    complete = sum(1 for _, done in checks if done)
    return {
        "steps_complete": complete,
        "steps_total": len(checks),
        "checklist": [{"label": label, "done": done} for label, done in checks],
    }
