"""
Hiring email builders — HTML + plain text via Django templates.
Sending goes through SendGrid (`send_configurable_email`) so all portal mail shares one path.
"""
from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)

STAGE_LABELS = {
    "SHORTLISTED": "Shortlist / Screening",
    "PERSONALITY": "Personality Assessment",
    "WRITTEN": "Written Assessment",
    "ORAL": "Oral Interview",
}

# After passing a stage, tell the candidate what comes next.
NEXT_STAGE_AFTER = {
    "PERSONALITY": "WRITTEN",
    "WRITTEN": "ORAL",
    "ORAL": None,  # hiring decision
}


def _careers_track_url() -> str:
    base = (getattr(settings, "CAREERS_PORTAL_URL", None) or "").rstrip("/")
    if base:
        return f"{base}/status"
    return ""


def _university_name() -> str:
    try:
        from accounts.portal_branding import get_university_display_name

        return get_university_display_name()
    except Exception:
        return "Ndejje University"


def build_interview_invitation_context(interview, application) -> dict[str, Any]:
    interview_datetime = timezone.localtime(interview.interview_date)
    stage = (interview.interview_type or "").upper()
    return {
        "university_name": _university_name(),
        "applicant_name": application.get_full_name(),
        "first_name": application.first_name,
        "position_title": application.job_opening.title,
        "department_name": application.job_opening.department.name,
        "reference": application.reference,
        "stage_code": stage,
        "stage_label": STAGE_LABELS.get(stage, stage.replace("_", " ").title()),
        "interview_datetime": interview_datetime.strftime("%A, %d %B %Y at %I:%M %p"),
        "duration_minutes": interview.duration_minutes or 60,
        "location": interview.location or "As communicated / Online",
        "meeting_link": interview.meeting_link or "",
        "notes": interview.feedback or "",
        "is_online_assessment": stage == "PERSONALITY",
        "track_url": _careers_track_url(),
        "from_email": getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@ndu.ac.ug"),
        "hr_contact_email": getattr(settings, "HR_RECRUITMENT_EMAIL", "") or "",
    }


def render_interview_invitation(interview, application) -> tuple[str, str, str]:
    """Return (subject, html_body, plain_text)."""
    ctx = build_interview_invitation_context(interview, application)
    subject = (
        f"Interview Invitation — {ctx['stage_label']} · {ctx['position_title']}"
    )
    html = render_to_string("hiring/emails/interview_invitation.html", ctx)
    plain = render_to_string("hiring/emails/interview_invitation.txt", ctx)
    return subject, html, plain.strip() or strip_tags(html)


def render_application_received(application) -> tuple[str, str, str]:
    ctx = {
        "university_name": _university_name(),
        "applicant_name": application.get_full_name(),
        "first_name": application.first_name,
        "position_title": application.job_opening.title,
        "department_name": application.job_opening.department.name,
        "reference": application.reference,
        "track_url": _careers_track_url(),
        "from_email": getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@ndu.ac.ug"),
    }
    subject = f"Application Received — {ctx['position_title']} ({ctx['reference']})"
    html = render_to_string("hiring/emails/application_received.html", ctx)
    plain = render_to_string("hiring/emails/application_received.txt", ctx)
    return subject, html, plain.strip() or strip_tags(html)


def send_interview_email(interview, application) -> bool:
    """
    Send one interview invitation synchronously via SendGrid.
    Prefer `tasks.queue_interview_invitation` from request handlers.
    """
    from ndu_portal.send_grid import send_configurable_email

    subject, html, plain = render_interview_invitation(interview, application)
    ok = send_configurable_email(
        to_email=application.email,
        subject=subject,
        body=html,
        is_html=True,
        plain_text_fallback=plain,
    )
    if not ok:
        logger.error(
            "Failed interview invite email for application=%s interview=%s",
            application.id,
            interview.id,
        )
    return ok


def send_application_received_email(application) -> bool:
    from ndu_portal.send_grid import send_configurable_email

    subject, html, plain = render_application_received(application)
    ok = send_configurable_email(
        to_email=application.email,
        subject=subject,
        body=html,
        is_html=True,
        plain_text_fallback=plain,
    )
    if not ok:
        logger.error(
            "Failed application received email for application=%s",
            application.id,
        )
    return ok


def _common_applicant_ctx(application) -> dict[str, Any]:
    return {
        "university_name": _university_name(),
        "applicant_name": application.get_full_name(),
        "first_name": application.first_name,
        "position_title": application.job_opening.title,
        "department_name": application.job_opening.department.name,
        "reference": application.reference,
        "track_url": _careers_track_url(),
        "from_email": getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@ndu.ac.ug"),
        "hr_contact_email": getattr(settings, "HR_RECRUITMENT_EMAIL", "") or "",
    }


def render_interview_outcome(interview, application, outcome: str) -> tuple[str, str, str]:
    """outcome is PASSED or FAILED."""
    stage = (interview.interview_type or "").upper()
    next_code = NEXT_STAGE_AFTER.get(stage) if outcome == "PASSED" else None
    ctx = {
        **_common_applicant_ctx(application),
        "outcome": outcome,
        "stage_code": stage,
        "stage_label": STAGE_LABELS.get(stage, stage.replace("_", " ").title()),
        "next_stage_code": next_code or "",
        "next_stage_label": STAGE_LABELS.get(next_code, "") if next_code else "",
    }
    if outcome == "PASSED":
        if next_code:
            subject = (
                f"You Passed — Next: {ctx['next_stage_label']} · {ctx['position_title']}"
            )
        else:
            subject = f"Interview Complete — {ctx['position_title']}"
    else:
        subject = f"Application Update — {ctx['position_title']} ({ctx['reference']})"

    html = render_to_string("hiring/emails/interview_outcome.html", ctx)
    plain = render_to_string("hiring/emails/interview_outcome.txt", ctx)
    return subject, html, plain.strip() or strip_tags(html)


def render_hired_congratulation(application) -> tuple[str, str, str]:
    ctx = _common_applicant_ctx(application)
    subject = f"Congratulations — Selected for {ctx['position_title']}"
    html = render_to_string("hiring/emails/hired_congratulation.html", ctx)
    plain = render_to_string("hiring/emails/hired_congratulation.txt", ctx)
    return subject, html, plain.strip() or strip_tags(html)


def send_interview_outcome_email(interview, application, outcome: str) -> bool:
    from ndu_portal.send_grid import send_configurable_email

    subject, html, plain = render_interview_outcome(interview, application, outcome)
    ok = send_configurable_email(
        to_email=application.email,
        subject=subject,
        body=html,
        is_html=True,
        plain_text_fallback=plain,
    )
    if not ok:
        logger.error(
            "Failed interview outcome email application=%s interview=%s outcome=%s",
            application.id,
            interview.id,
            outcome,
        )
    return ok


def send_hired_email(application) -> bool:
    from ndu_portal.send_grid import send_configurable_email

    subject, html, plain = render_hired_congratulation(application)
    ok = send_configurable_email(
        to_email=application.email,
        subject=subject,
        body=html,
        is_html=True,
        plain_text_fallback=plain,
    )
    if not ok:
        logger.error("Failed hired email for application=%s", application.id)
    return ok
