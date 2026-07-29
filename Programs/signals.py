"""Signals for teaching sections."""
from django.db.models.signals import post_save
from django.dispatch import receiver

from Programs.models import ProgramBatch


@receiver(post_save, sender=ProgramBatch)
def ensure_default_section_on_batch_save(sender, instance, created, **kwargs):
    from Programs.teaching_sections import ensure_default_teaching_section

    ensure_default_teaching_section(instance)
