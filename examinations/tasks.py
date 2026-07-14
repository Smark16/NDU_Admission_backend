"""Celery tasks for examinations notifications."""
import logging

from celery import shared_task
from django.apps import apps

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def notify_exam_session_published(self, session_id):
    """Email + in-app notify enrolled students when an exam session is published."""
    from admissions.utils.notification import create_notification
    from ndu_portal.send_grid import send_configurable_email

    from .models import ExamRetakeRegistration, ExamSession
    from .services.clash import candidate_student_ids

    try:
        session = ExamSession.objects.select_related(
            "course_unit", "venue"
        ).get(pk=session_id)
    except ExamSession.DoesNotExist:
        logger.warning("notify_exam_session_published: session %s missing", session_id)
        return

    if not session.is_published:
        return

    course = session.course_unit
    venue = ""
    if session.venue_id:
        venue = session.venue.name
        if session.venue.building:
            venue = f"{session.venue.building} — {venue}"
    elif session.venue_text:
        venue = session.venue_text

    when = str(session.exam_date)
    if session.start_time:
        when = f"{when} {session.start_time}"
        if session.end_time:
            when = f"{when}–{session.end_time}"

    title = f"Exam published: {course.code}"
    body = (
        f"Your exam for {course.code} — {course.name} is scheduled on {when}"
        f"{f' at {venue}' if venue else ''}. "
        f"Check the student portal exam timetable for details."
    )

    AdmittedStudent = apps.get_model("admissions", "AdmittedStudent")
    student_ids = candidate_student_ids(course, session.session_type)
    if session.session_type in (ExamSession.TYPE_RETAKE, ExamSession.TYPE_SUPPLEMENTARY):
        retake_ids = set(
            ExamRetakeRegistration.objects.filter(
                exam_session=session,
                status__in=(
                    ExamRetakeRegistration.STATUS_APPROVED,
                    ExamRetakeRegistration.STATUS_SCHEDULED,
                ),
            ).values_list("enrollment__student_id", flat=True)
        )
        if retake_ids:
            student_ids = student_ids | retake_ids

    students = AdmittedStudent.objects.filter(id__in=student_ids).select_related(
        "student_user", "application"
    )
    for student in students:
        user = getattr(student, "student_user", None)
        email = None
        if user and user.email:
            email = user.email
        elif student.application and student.application.email:
            email = student.application.email

        if user:
            try:
                create_notification(user, title, body)
            except Exception:
                logger.exception("Portal notification failed for student %s", student.id)

        if email:
            try:
                send_configurable_email(email, title, body)
            except Exception:
                logger.exception("Exam publish email failed for %s", email)
