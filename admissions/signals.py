# signals.py
import logging

from django.core.cache import cache
from django.db.models.signals import post_save, post_delete, m2m_changed
from django.dispatch import receiver
from .models import Batch, AcademicLevel, ALevelSubject, OLevelSubject

logger = logging.getLogger(__name__)


def bump_batch_version():
    """Bump cache version so active-batch views refresh. Fails soft if Redis is down."""
    try:
        try:
            return cache.incr("active_batch_version")
        except ValueError:
            cache.set("active_batch_version", 1, timeout=None)
            return 1
    except Exception as exc:
        logger.warning("Cache unavailable; skipped active_batch_version bump: %s", exc)
        return None


def _safe_cache_delete(key: str) -> None:
    try:
        cache.delete(key)
    except Exception as exc:
        logger.warning("Cache unavailable; skipped delete %s: %s", key, exc)

@receiver([post_save, post_delete], sender=Batch)
def invalidate_on_batch_change(sender, instance, **kwargs):
    bump_batch_version()


def _connect_program_batch_cache_invalidation():
    try:
        from Programs.models import ProgramBatch
    except ImportError:
        return

    @receiver([post_save, post_delete], sender=ProgramBatch)
    def invalidate_on_program_batch_change(sender, instance, **kwargs):
        bump_batch_version()


_connect_program_batch_cache_invalidation()

@receiver(m2m_changed, sender=Batch.programs.through)
def invalidate_on_programs_change(sender, instance, action, **kwargs):
    if action in ('post_add', 'post_remove', 'post_clear'):
        bump_batch_version()

# academic levels
@receiver([post_save, post_delete], sender=AcademicLevel)
def invalidate_academic_levels_cache(sender, instance, **kwargs):
    _safe_cache_delete("active_academic_levels_list")

# Alevel results
@receiver([post_save, post_delete], sender=ALevelSubject)
def invalidate_alevel_subjects_cache(sender, instance, **kwargs):
    _safe_cache_delete("all_alevel_subjects_list")

@receiver([post_save, post_delete], sender=OLevelSubject)
def invalidate_olevel_subjects_cache(sender, instance, **kwargs):
    _safe_cache_delete("all_olevel_subjects_list")