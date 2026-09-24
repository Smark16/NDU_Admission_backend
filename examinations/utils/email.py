"""Marks-workflow email notifications, via the existing SendGrid integration."""
import logging

from ndu_portal.send_grid import send_configurable_email
from accounts.portal_branding import get_university_display_name

logger = logging.getLogger(__name__)


def _department_for_course_unit(course_unit):
    program = getattr(course_unit.program_batch, "program", None)
    return getattr(program, "department", None) if program else None


def send_marks_submitted_email(course_unit, *, submitted_by, submitted_count: int) -> None:
    """Notify the HOD and Exam Coordinator that a lecturer submitted marks for review."""
    department = _department_for_course_unit(course_unit)
    if department is None:
        logger.info(
            "send_marks_submitted_email: no department for course_unit id=%s, skipping",
            course_unit.id,
        )
        return

    recipients = {
        u.email: u
        for u in (department.head_of_department, department.exam_coordinator)
        if u is not None and u.email
    }
    if not recipients:
        logger.info(
            "send_marks_submitted_email: no HOD/Exam Coordinator email on file for "
            "department id=%s, skipping",
            department.id,
        )
        return

    uni = get_university_display_name()
    lecturer_name = submitted_by.get_full_name() if submitted_by else "A lecturer"
    subject = f"Marks submitted for review — {course_unit.code}"
    body = (
        f"<p>{lecturer_name} has submitted {submitted_count} mark(s) for "
        f"<strong>{course_unit.code} — {course_unit.name}</strong> "
        f"({course_unit.program_batch}) and they are now awaiting your review.</p>"
        f"<p>Please log in to {uni} STEWARD ERP to review and approve.</p>"
    )
    plain_fallback = (
        f"{lecturer_name} has submitted {submitted_count} mark(s) for "
        f"{course_unit.code} - {course_unit.name} ({course_unit.program_batch}), "
        f"now awaiting your review. Please log in to {uni} STEWARD ERP to review and approve."
    )
    for email, _user in recipients.items():
        try:
            send_configurable_email(email, subject, body, is_html=True, plain_text_fallback=plain_fallback)
        except Exception:
            logger.exception("send_marks_submitted_email: failed to send to %s", email)
