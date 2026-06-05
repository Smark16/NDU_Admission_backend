"""Helpers for matching admitted students to academic programme batches."""
from django.db.models import Q

from admissions.models import AdmittedStudent


def admitted_students_for_program_batch(program, program_batch):
    """
    Admitted students eligible for a programme batch.

    Includes students with matching intended batch, programme enrollment batch,
    or no intended batch yet (cohort not set at admission — common for new admits).
    """
    return (
        AdmittedStudent.objects.filter(admitted_program=program, is_admitted=True)
        .filter(
            Q(intended_program_batch=program_batch)
            | Q(programme_enrollment__program_batch=program_batch)
            | Q(intended_program_batch__isnull=True)
        )
        .distinct()
        .select_related("application", "application__applicant", "programme_enrollment")
    )
