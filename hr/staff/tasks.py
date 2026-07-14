"""
Celery tasks for staff login provisioning.
Queued via transaction.on_commit so the HTTP request stays fast and only
runs after the staff profile transaction has committed. On hard failure the
task compensates by removing the staff row (and clearing application.is_staff)
so the overall create is rolled back.
"""
from __future__ import annotations

import logging

from celery import shared_task
from django.db import transaction

logger = logging.getLogger(__name__)


def _compensate_failed_provision(staff_id: int) -> None:
    from hr.hiring.models import JobApplication
    from hr.staff.models import StaffProfile

    with transaction.atomic():
        staff = (
            StaffProfile.objects.select_for_update()
            .filter(pk=staff_id)
            .select_related("application")
            .first()
        )
        if not staff:
            return
        # Only compensate if login was never linked.
        if staff.user_id:
            return
        app_id = staff.application_id
        staff.delete()
        if app_id:
            JobApplication.objects.filter(pk=app_id, is_staff=True).update(is_staff=False)
        logger.warning("Compensated staff %s after failed login provisioning", staff_id)


@shared_task(bind=True, max_retries=5, default_retry_delay=20, retry_backoff=True)
def celery_provision_staff_login(self, staff_id: int) -> dict:
    from hr.staff.models import StaffProfile
    from hr.staff.utils.create_user import create_user_for_staff
    from accounts.utils.passwords import generate_changeme_password

    try:
        with transaction.atomic():
            staff = (
                StaffProfile.objects.select_for_update()
                .select_related("application")
                .get(pk=staff_id)
            )
            if not staff.system_login:
                return {"ok": True, "skipped": "system_login_false"}
            if staff.user_id:
                return {"ok": True, "already_linked": True}

            create_user_for_staff(
                staff,
                initial_password=generate_changeme_password(),
                activate=False,
                assign_role_groups=False,
            )
            return {"ok": True, "staff_id": staff_id, "user_id": staff.user_id}
    except StaffProfile.DoesNotExist:
        logger.warning("celery_provision_staff_login: staff %s missing", staff_id)
        return {"ok": False, "missing": True}
    except Exception as exc:
        logger.exception("celery_provision_staff_login failed for staff %s", staff_id)
        if self.request.retries >= self.max_retries:
            try:
                _compensate_failed_provision(int(staff_id))
            except Exception:
                logger.exception("Compensation failed for staff %s", staff_id)
            raise
        raise self.retry(exc=exc)


def queue_staff_login_provision(staff_id: int) -> None:
    """Safe inside @atomic — schedules after commit."""

    def _enqueue():
        celery_provision_staff_login.delay(int(staff_id))

    transaction.on_commit(_enqueue)
