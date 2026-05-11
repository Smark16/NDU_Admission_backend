from django.core.cache import cache
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import ApplicationFee, StudentTuitionPayment
from .programme_enrollment_activation import (
    activate_programme_enrollment_after_commitment_payment,
)


@receiver([post_save, post_delete], sender=ApplicationFee)
def invalidate_fee_plans_cache(sender, instance, **kwargs):
    cache.delete('all_fee_plans_list')
    print("Cleared cache: all_fee_plans_list")


@receiver(post_save, sender=StudentTuitionPayment)
def auto_enroll_after_commitment_payment(sender, instance, **kwargs):
    if instance.status != "completed" or not instance.student_id:
        return
    activate_programme_enrollment_after_commitment_payment(instance.student)