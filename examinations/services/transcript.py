"""Build semester transcript data for a student."""
from admissions.models import AdmittedStudent

from ..models import CourseUnitResult
from .graduation_status import get_transcript_document_meta


def build_student_transcript(student: AdmittedStudent) -> dict:
    results = (
        CourseUnitResult.objects.filter(
            enrollment__student=student,
            status=CourseUnitResult.STATUS_PUBLISHED,
        )
        .select_related(
            "enrollment",
            "enrollment__course_unit",
            "enrollment__course_unit__semester",
            "policy",
        )
        .order_by(
            "enrollment__course_unit__semester__order",
            "enrollment__course_unit__code",
        )
    )

    semesters: dict[str, dict] = {}
    total_credits = 0
    weighted_gp = 0

    for r in results:
        cu = r.enrollment.course_unit
        sem = cu.semester
        sem_key = sem.name if sem else "Other"
        block = semesters.setdefault(
            sem_key,
            {"name": sem_key, "courses": [], "semester_gpa": None},
        )
        credits = float(cu.credit_units) if cu.credit_units else 0
        gp = float(r.grade_point) if r.grade_point is not None else None
        if credits and gp is not None:
            total_credits += credits
            weighted_gp += credits * gp

        block["courses"].append(
            {
                "course_code": cu.code,
                "course_name": cu.name,
                "credit_units": credits or None,
                "ca_mark": str(r.ca_mark) if r.ca_mark is not None else None,
                "exam_mark": str(r.exam_mark) if r.exam_mark is not None else None,
                "final_mark": str(r.final_mark) if r.final_mark is not None else None,
                "grade_letter": r.grade_letter,
                "grade_point": str(r.grade_point) if r.grade_point is not None else None,
                "is_pass": r.is_pass,
            }
        )

    cgpa = round(weighted_gp / total_credits, 2) if total_credits else None

    document = get_transcript_document_meta(student)

    return {
        "student": {
            "reg_no": student.reg_no,
            "student_id": student.student_id,
            "name": student.full_name,
            "program": student.admitted_program.name if student.admitted_program_id else None,
        },
        "semesters": list(semesters.values()),
        "summary": {
            "total_credit_units": total_credits,
            "cgpa": cgpa,
            "published_course_count": results.count(),
        },
        "document": document,
    }
