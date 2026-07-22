"""Helpers for matching admitted students to academic programme batches."""
from django.db.models import Q

from admissions.models import AdmittedStudent


def admitted_students_for_program_batch(program, program_batch):
    """
    Admitted students who belong to this programme batch only.

    Match rules (strict — no cross-batch leakage):
    - intended_program_batch is this batch, or
    - intended is unset and programme enrollment is already on this batch.

    Students with no intended cohort and no enrollment on this batch are excluded
    so staff cannot enroll Year-1 / other-cohort students into the wrong batch
    from Batch Management.
    """
    return (
        AdmittedStudent.objects.filter(admitted_program=program, is_admitted=True)
        .filter(
            Q(intended_program_batch=program_batch)
            | Q(
                intended_program_batch__isnull=True,
                programme_enrollment__program_batch=program_batch,
            )
        )
        .distinct()
        .select_related("application", "application__applicant", "programme_enrollment")
    )


def student_belongs_to_program_batch(student, program_batch) -> bool:
    """True when this admitted student is allowed into the given programme batch."""
    if student.intended_program_batch_id:
        return student.intended_program_batch_id == program_batch.id
    enrollment = getattr(student, "programme_enrollment", None)
    if enrollment is not None and enrollment.program_batch_id:
        return enrollment.program_batch_id == program_batch.id
    return False
