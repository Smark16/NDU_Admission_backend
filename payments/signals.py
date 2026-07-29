from django.core.cache import cache
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import (
    ApplicationFee,
    FeePlanRule,
    RegistrationSettings,
    StudentTuitionPayment,
    TuitionLedger,
)
from .programme_enrollment_activation import (
    try_activate_programme_enrollment_after_payment,
)


def _refresh_tuition_pct_for_student_id(student_id: int | None) -> None:
    if not student_id:
        return
    try:
        from admissions.models import AdmittedStudent
        from payments.tuition_pct_cache import refresh_student_tuition_pct_cache

        student = AdmittedStudent.objects.filter(pk=student_id).first()
        if student is None:
            return
        refresh_student_tuition_pct_cache(student)
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "tuition %% cache refresh failed for student_id=%s", student_id
        )


@receiver([post_save, post_delete], sender=ApplicationFee)
def invalidate_fee_plans_cache(sender, instance, **kwargs):
    cache.delete('all_fee_plans_list')
    print("Cleared cache: all_fee_plans_list")


@receiver(post_save, sender=StudentTuitionPayment)
def auto_enroll_after_commitment_payment(sender, instance, **kwargs):
    if instance.status != "completed" or not instance.student_id:
        return
    try_activate_programme_enrollment_after_payment(instance.student)
    _refresh_tuition_pct_for_student_id(instance.student_id)


@receiver(post_save, sender=TuitionLedger)
def auto_enroll_after_schoolpay_ledger_payment(sender, instance, **kwargs):
    if instance.transaction_completion_status != "Completed" or not instance.student_id:
        return
    try_activate_programme_enrollment_after_payment(instance.student)
    _refresh_tuition_pct_for_student_id(instance.student_id)


@receiver(post_save, sender=RegistrationSettings)
def invalidate_tuition_pct_cache_on_settings_change(sender, instance, **kwargs):
    """Min % changes must recompute cached gate flags."""
    try:
        from payments.tuition_pct_cache import invalidate_all_tuition_pct_cache
        from payments.tasks import celery_refresh_bonafide_tuition_pct_cache

        invalidate_all_tuition_pct_cache()
        celery_refresh_bonafide_tuition_pct_cache.delay()
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "failed to invalidate/requeue tuition %% cache after settings change"
        )


@receiver([post_save, post_delete], sender=FeePlanRule)
def invalidate_tuition_pct_cache_on_fee_plan_change(sender, instance, **kwargs):
    try:
        from payments.tuition_pct_cache import invalidate_all_tuition_pct_cache
        from payments.tasks import celery_refresh_bonafide_tuition_pct_cache

        invalidate_all_tuition_pct_cache()
        celery_refresh_bonafide_tuition_pct_cache.delay()
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "failed to invalidate/requeue tuition %% cache after fee plan change"
        )
