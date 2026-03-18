from django.core.cache import cache
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import ApplicationFee

@receiver([post_save, post_delete], sender=ApplicationFee)
def invalidate_fee_plans_cache(sender, instance, **kwargs):
    cache.delete('all_fee_plans_list')
    print("Cleared cache: all_fee_plans_list")