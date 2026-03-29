# signals.py
from django.core.cache import cache
from django.db.models.signals import post_save, post_delete, m2m_changed
from django.dispatch import receiver
from .models import Batch, AcademicLevel, ALevelSubject, OLevelSubject

def bump_batch_version():
    try:
        new_version = cache.incr('active_batch_version')
    except ValueError:
        cache.set('active_batch_version', 1, timeout=None)
        new_version = 1
    
    return new_version

@receiver([post_save, post_delete], sender=Batch)
def invalidate_on_batch_change(sender, instance, **kwargs):
    bump_batch_version()

@receiver(m2m_changed, sender=Batch.programs.through)
def invalidate_on_programs_change(sender, instance, action, **kwargs):
    if action in ('post_add', 'post_remove', 'post_clear'):
        bump_batch_version()

# academic levels
@receiver([post_save, post_delete], sender=AcademicLevel)
def invalidate_academic_levels_cache(sender, instance, **kwargs):
    cache.delete('active_academic_levels_list')

# Alevel results
@receiver([post_save, post_delete], sender=ALevelSubject)
def invalidate_alevel_subjects_cache(sender, instance, **kwargs):
    cache.delete('all_alevel_subjects_list')

@receiver([post_save, post_delete], sender=OLevelSubject)
def invalidate_olevel_subjects_cache(sender, instance, **kwargs):
    cache.delete('all_olevel_subjects_list')