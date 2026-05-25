"""Compute graduation eligibility from published examination results."""
from decimal import Decimal

from admissions.models import AdmittedStudent
from examinations.models import CourseUnitResult
from examinations.services.award_classification import resolve_award_class
from examinations.services.transcript import build_student_transcript
from Programs.models import StudentProgrammeEnrollment


DEFAULT_MIN_CGPA = Decimal("2.00")


def _min_graduation_load(enrollment: StudentProgrammeEnrollment) -> Decimal:
    program = enrollment.program
    cv = enrollment.curriculum_version
    if cv and cv.minimum_graduation_load is not None:
        return cv.minimum_graduation_load
    if program.minimum_graduation_load is not None:
        return program.minimum_graduation_load
    return Decimal("0")


def evaluate_student_graduation(
    student: AdmittedStudent,
    *,
    min_cgpa: Decimal | None = None,
) -> dict:
    """
    Returns eligibility snapshot for one student based on published results.
    """
    min_cgpa = min_cgpa if min_cgpa is not None else DEFAULT_MIN_CGPA
    blockers: list[str] = []
    reasons: list[str] = []

    if student.application and student.application.is_revoked:
        blockers.append("Admission revoked.")

    try:
        enrollment = student.programme_enrollment
    except StudentProgrammeEnrollment.DoesNotExist:
        blockers.append("No programme enrollment.")
        enrollment = None

    if enrollment and enrollment.status not in ("enrolled", "completed"):
        blockers.append(f"Programme status is '{enrollment.status}', not enrolled.")

    transcript = build_student_transcript(student)
    summary = transcript.get("summary") or {}
    cgpa = summary.get("cgpa")
    total_cu = summary.get("total_credit_units") or 0
    published_count = summary.get("published_course_count") or 0

    cgpa_dec = Decimal(str(cgpa)) if cgpa is not None else None
    total_cu_dec = Decimal(str(total_cu))

    failed_count = CourseUnitResult.objects.filter(
        enrollment__student=student,
        status=CourseUnitResult.STATUS_PUBLISHED,
        is_pass=False,
    ).count()

    min_load = _min_graduation_load(enrollment) if enrollment else Decimal("0")

    if published_count == 0:
        blockers.append("No published course results.")
    else:
        reasons.append(f"{published_count} published course(s).")

    if enrollment and min_load > 0 and total_cu_dec < min_load:
        blockers.append(
            f"Credit units {total_cu_dec} below minimum graduation load {min_load}."
        )
    elif enrollment and min_load > 0:
        reasons.append(f"Meets minimum graduation load ({min_load} CU).")

    if cgpa_dec is None:
        blockers.append("CGPA cannot be calculated (no graded credits).")
    elif cgpa_dec < min_cgpa:
        blockers.append(f"CGPA {cgpa_dec} below minimum {min_cgpa}.")
    else:
        reasons.append(f"CGPA {cgpa_dec} meets minimum {min_cgpa}.")

    if failed_count > 0:
        blockers.append(f"{failed_count} published failed course(s).")

    already_assigned = student.graduation_assignments.exists()
    if already_assigned:
        reasons.append("Already assigned to a graduation session.")

    qualified = len(blockers) == 0

    return {
        "student_id": student.id,
        "reg_no": student.reg_no or "",
        "student_name": student.full_name or "",
        "program_id": enrollment.program_id if enrollment else None,
        "program_name": enrollment.program.name if enrollment else None,
        "batch_id": enrollment.program_batch_id if enrollment else None,
        "batch_name": enrollment.program_batch.name if enrollment else None,
        "cgpa": str(cgpa_dec) if cgpa_dec is not None else None,
        "total_credit_units": str(total_cu_dec),
        "min_graduation_load": str(min_load) if enrollment else None,
        "min_cgpa": str(min_cgpa),
        "failed_published_count": failed_count,
        "published_course_count": published_count,
        "award_class": resolve_award_class(cgpa_dec, student=student),
        "qualified": qualified,
        "reasons": reasons,
        "blockers": blockers,
        "already_assigned": already_assigned,
    }


def qualified_students_queryset(
    *,
    program_batch_id: int | None = None,
    program_id: int | None = None,
    min_cgpa: Decimal | None = None,
):
    """Return list of qualification dicts for students in scope."""
    qs = AdmittedStudent.objects.filter(is_admitted=True).select_related(
        "programme_enrollment",
        "programme_enrollment__program",
        "programme_enrollment__program_batch",
        "application",
    )
    if program_batch_id:
        qs = qs.filter(programme_enrollment__program_batch_id=program_batch_id)
    if program_id:
        qs = qs.filter(programme_enrollment__program_id=program_id)

    qs = qs.filter(programme_enrollment__status__in=("enrolled", "completed"))

    rows = []
    for student in qs.order_by("reg_no"):
        row = evaluate_student_graduation(student, min_cgpa=min_cgpa)
        rows.append(row)
    return rows
