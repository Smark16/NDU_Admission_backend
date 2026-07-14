"""
Celery tasks for hiring notifications and vacancy lifecycle.
Queue from views with transaction.on_commit(...) so emails never block the HTTP response
and never run against uncommitted rows.
"""
from __future__ import annotations

import logging

from celery import shared_task
from django.db import transaction

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=5, default_retry_delay=30, autoretry_for=(Exception,), retry_backoff=True)
def celery_send_interview_invitation(self, interview_id: int) -> bool:
    from hr.hiring.models import Interview
    from hr.hiring.utils.interview_email import send_interview_email

    try:
        interview = Interview.objects.select_related(
            "application",
            "application__job_opening",
            "application__job_opening__department",
        ).get(pk=interview_id)
    except Interview.DoesNotExist:
        logger.warning("celery_send_interview_invitation: interview %s missing", interview_id)
        return False

    application = interview.application
    if not (application.email or "").strip():
        logger.warning("Interview %s has no applicant email", interview_id)
        return False

    ok = send_interview_email(interview, application)
    if not ok:
        raise RuntimeError(f"SendGrid failed for interview {interview_id}")
    return True


@shared_task(bind=True, max_retries=3, default_retry_delay=20, autoretry_for=(Exception,), retry_backoff=True)
def celery_send_interview_invitations_batch(self, interview_ids: list[int]) -> dict:
    """Fan-out wrapper used when scheduling many candidates at once."""
    queued = 0
    for iid in interview_ids or []:
        celery_send_interview_invitation.delay(int(iid))
        queued += 1
    return {"queued": queued}


@shared_task(bind=True, max_retries=5, default_retry_delay=30, autoretry_for=(Exception,), retry_backoff=True)
def celery_send_application_received(self, application_id: int) -> bool:
    from hr.hiring.models import JobApplication
    from hr.hiring.utils.interview_email import send_application_received_email

    try:
        application = JobApplication.objects.select_related(
            "job_opening", "job_opening__department"
        ).get(pk=application_id)
    except JobApplication.DoesNotExist:
        logger.warning("celery_send_application_received: application %s missing", application_id)
        return False

    if not (application.email or "").strip():
        return False

    ok = send_application_received_email(application)
    if not ok:
        raise RuntimeError(f"SendGrid failed for application {application_id}")
    return True


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def celery_sync_job_opening_statuses(self) -> dict:
    """
    Periodically open scheduled drafts and close expired vacancies.

    Runs via Celery Beat. Public list/apply also enforce the date window so
    careers stay correct even if a beat tick is briefly delayed.
    """
    from hr.hiring.utils.job_lifecycle import sync_job_opening_statuses

    result = sync_job_opening_statuses()
    if result["opened"] or result["closed"]:
        logger.info(
            "Job opening sync on %s: opened=%s closed=%s",
            result["date"],
            result["opened_ids"],
            result["closed_ids"],
        )
    return result


def queue_interview_invitation(interview_id: int) -> None:
    """Safe to call inside @atomic — schedules after commit."""

    def _enqueue():
        celery_send_interview_invitation.delay(int(interview_id))

    transaction.on_commit(_enqueue)


def queue_interview_invitations(interview_ids: list[int]) -> None:
    ids = [int(i) for i in interview_ids if i is not None]
    if not ids:
        return

    def _enqueue():
        # One batch task then fan-out; keeps request transaction small.
        if len(ids) == 1:
            celery_send_interview_invitation.delay(ids[0])
        else:
            celery_send_interview_invitations_batch.delay(ids)

    transaction.on_commit(_enqueue)


def queue_application_received(application_id: int) -> None:
    def _enqueue():
        celery_send_application_received.delay(int(application_id))

    transaction.on_commit(_enqueue)


@shared_task(bind=True, max_retries=5, default_retry_delay=30, autoretry_for=(Exception,), retry_backoff=True)
def celery_send_interview_outcome(self, interview_id: int, outcome: str) -> bool:
    from hr.hiring.models import Interview
    from hr.hiring.utils.interview_email import send_interview_outcome_email

    try:
        interview = Interview.objects.select_related(
            "application",
            "application__job_opening",
            "application__job_opening__department",
        ).get(pk=interview_id)
    except Interview.DoesNotExist:
        logger.warning("celery_send_interview_outcome: interview %s missing", interview_id)
        return False

    application = interview.application
    if not (application.email or "").strip():
        logger.warning("Interview outcome %s: no applicant email", interview_id)
        return False

    ok = send_interview_outcome_email(interview, application, outcome)
    if not ok:
        raise RuntimeError(f"SendGrid failed for interview outcome {interview_id}")
    return True


@shared_task(bind=True, max_retries=5, default_retry_delay=30, autoretry_for=(Exception,), retry_backoff=True)
def celery_send_hired_email(self, application_id: int) -> bool:
    from hr.hiring.models import JobApplication
    from hr.hiring.utils.interview_email import send_hired_email

    try:
        application = JobApplication.objects.select_related(
            "job_opening", "job_opening__department"
        ).get(pk=application_id)
    except JobApplication.DoesNotExist:
        logger.warning("celery_send_hired_email: application %s missing", application_id)
        return False

    if not (application.email or "").strip():
        return False

    ok = send_hired_email(application)
    if not ok:
        raise RuntimeError(f"SendGrid failed for hired application {application_id}")
    return True


def queue_interview_outcome(interview_id: int, outcome: str) -> None:
    """Queue PASSED/FAILED notification after commit."""

    def _enqueue():
        celery_send_interview_outcome.delay(int(interview_id), str(outcome).upper())

    transaction.on_commit(_enqueue)


def queue_hired_emails(application_ids: list[int]) -> None:
    ids = [int(i) for i in application_ids if i is not None]
    if not ids:
        return

    def _enqueue():
        for aid in ids:
            celery_send_hired_email.delay(aid)

    transaction.on_commit(_enqueue)
