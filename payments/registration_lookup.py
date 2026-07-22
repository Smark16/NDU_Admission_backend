"""Staff registration card payload (same data as student portal / QR verify)."""
from __future__ import annotations

from django.db.models import Q

from admissions.models import AdmittedStudent
from Programs.models import StudentCourseUnitEnrollment, StudentProgrammeEnrollment

from accounts.portal_branding import get_university_display_name
from .student_portal_finance import registration_card_payment_history, student_finance_totals


def _course_rows_for_student(student: AdmittedStudent) -> list[dict]:
    enrollments = (
        StudentCourseUnitEnrollment.objects.filter(student=student, registration_date__isnull=False)
        .select_related(
            "course_unit",
            "course_unit__semester",
            "course_unit__program_batch",
        )
        .order_by("course_unit__code")
    )
    rows = []
    for enrollment in enrollments:
        cu = enrollment.course_unit
        semester = cu.semester if cu else None
        batch = cu.program_batch if cu else None
        if not batch and semester:
            batch = semester.program_batch
        rows.append(
            {
                "enrollment_id": enrollment.id,
                "course_code": cu.code if cu else "—",
                "course_name": cu.name if cu else "—",
                "credit_units": float(cu.credit_units) if cu and cu.credit_units else None,
                "semester_name": semester.name if semester else (batch.name if batch else None),
                "registration_date": enrollment.registration_date.isoformat()
                if enrollment.registration_date
                else None,
                "status": enrollment.status,
            }
        )
    return rows


def _passport_photo_url(student: AdmittedStudent, request) -> str | None:
    try:
        photo = student.application.passport_photo
        if photo and photo.name and request is not None:
            return request.build_absolute_uri(photo.url)
    except Exception:
        pass
    return None


def build_registration_lookup_payload(student: AdmittedStudent, request=None) -> dict:
    finance = student_finance_totals(student)
    registered_courses = _course_rows_for_student(student)

    enrollment_status = "none"
    enrollment_status_display = "Not enrolled"
    current_year = None
    current_term = None
    try:
        spe = StudentProgrammeEnrollment.objects.select_related("program_batch").get(student=student)
        enrollment_status = spe.status
        enrollment_status_display = spe.get_status_display()
        current_year = spe.current_year_of_study
        current_term = spe.current_term_number
    except StudentProgrammeEnrollment.DoesNotExist:
        pass

    return {
        "id": student.id,
        "valid": True,
        "student_id": student.student_id,
        "schoolpay_code": student.effective_schoolpay_code,
        "reg_no": student.reg_no,
        "student_name": student.full_name,
        "programme": student.admitted_program.name if student.admitted_program_id else None,
        "campus": student.admitted_campus.name if student.admitted_campus_id else None,
        "passport_photo": _passport_photo_url(student, request),
        "enrollment_status": enrollment_status,
        "enrollment_status_display": enrollment_status_display,
        "current_year_of_study": current_year,
        "current_term_number": current_term,
        "registered_courses_count": len(registered_courses),
        "registered_courses": registered_courses,
        "percentage_paid": finance["percentage_paid"],
        "total_paid": finance["total_paid"],
        "total_required": finance["total_required"],
        "balance": finance["balance"],
        "display_currency": finance["display_currency"],
        "commitment_met": finance["commitment_met"],
        "commitment_paid_ugx": finance["commitment_paid_ugx"],
        "commitment_threshold": finance["commitment_threshold"],
        "admission_fee_paid": student.admission_fee_paid,
        "payment_history": registration_card_payment_history(student, limit=12),
        "system": get_university_display_name(),
    }


def _student_search_qs():
    return AdmittedStudent.objects.filter(is_admitted=True).select_related(
        "admitted_program",
        "admitted_campus",
        "application",
    )


def search_admitted_students(query: str, limit: int = 15):
    q = (query or "").strip()
    if not q:
        return _student_search_qs().none()

    if q.isdigit():
        return _student_search_qs().filter(pk=int(q))[:limit]

    exact = _student_search_qs().filter(Q(student_id__iexact=q) | Q(reg_no__iexact=q))
    if exact.exists():
        return exact[:limit]

    return _student_search_qs().filter(
        Q(student_id__icontains=q)
        | Q(reg_no__icontains=q)
        | Q(application__first_name__icontains=q)
        | Q(application__last_name__icontains=q)
        | Q(application__email__icontains=q)
    ).order_by("application__last_name", "application__first_name")[:limit]


def student_summary_row(student: AdmittedStudent) -> dict:
    return {
        "id": student.id,
        "student_id": student.student_id,
        "reg_no": student.reg_no,
        "student_name": student.full_name,
        "programme": student.admitted_program.name if student.admitted_program_id else None,
        "campus": student.admitted_campus.name if student.admitted_campus_id else None,
    }
