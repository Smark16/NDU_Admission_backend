"""Whether a student receives provisional results vs academic transcript."""
from __future__ import annotations

from django.utils import timezone

from admissions.models import AdmittedStudent


def student_has_graduated(student: AdmittedStudent) -> bool:
    """
    True when the student has completed the programme or has walked at a
    graduation session whose date has passed.
    """
    try:
        enr = student.programme_enrollment
        if enr.status == "completed":
            return True
    except Exception:
        pass

    from graduation.models import GraduationAssignment

    today = timezone.localdate()
    return GraduationAssignment.objects.filter(
        student=student,
        session__graduation_date__lte=today,
    ).exists()


def get_transcript_document_meta(student: AdmittedStudent) -> dict:
    graduated = student_has_graduated(student)
    if graduated:
        return {
            "kind": "academic_transcript",
            "title": "Academic Transcript",
            "is_graduated": True,
            "filename_prefix": "Academic_Transcript",
        }
    return {
        "kind": "provisional_results",
        "title": "Provisional Results",
        "is_graduated": False,
        "filename_prefix": "Provisional_Results",
    }


def graduation_show_scores_default(student: AdmittedStudent) -> bool:
    """Ceremony flag for hiding numeric marks on transcript printouts."""
    from graduation.models import GraduationAssignment

    assignment = (
        GraduationAssignment.objects.filter(student=student)
        .select_related("session__ceremony")
        .order_by("-session__graduation_date")
        .first()
    )
    if assignment and assignment.session and assignment.session.ceremony:
        return assignment.session.ceremony.show_marks_on_transcript
    return True
