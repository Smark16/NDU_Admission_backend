"""Course registration: set registration_date on StudentCourseUnitEnrollment."""
from django.db import transaction
from django.utils import timezone

from admissions.models import AdmittedStudent


def register_student_for_course_units(student: AdmittedStudent, course_unit_ids: list) -> dict:
    from Programs.models import CourseUnit, StudentCourseUnitEnrollment, StudentProgrammeEnrollment

    registered = []
    errors = []
    t = timezone.now()
    spe = (
        StudentProgrammeEnrollment.objects.select_related("program")
        .filter(student=student)
        .first()
    )
    selected_specialization = (spe.specialization or "").strip() if spe else ""
    ids = []
    for x in course_unit_ids:
        if x is None:
            continue
        try:
            ids.append(int(x))
        except (TypeError, ValueError):
            errors.append(f"Invalid course id: {x}")
    with transaction.atomic():
        for cid in ids:
            try:
                cu = CourseUnit.objects.select_related("curriculum_line").get(id=cid)
            except CourseUnit.DoesNotExist:
                errors.append(f"Course unit {cid} not found")
                continue

            # Protect specialization tracks at write-time too (not just list-time).
            if cu.curriculum_line_id:
                line_spec = (cu.curriculum_line.specialization or "").strip()
                if line_spec and not selected_specialization:
                    errors.append(
                        f"{cu.code} requires a specialization to be selected before registration."
                    )
                    continue
                if line_spec and selected_specialization.lower() != line_spec.lower():
                    errors.append(
                        f"{cu.code} belongs to '{line_spec}' specialization, not '{selected_specialization}'."
                    )
                    continue

            en = StudentCourseUnitEnrollment.objects.filter(student=student, course_unit=cu).first()
            if not en:
                errors.append(f"Not enrolled in {cu.code}; ask admin to enroll you first.")
                continue
            if en.registration_date:
                errors.append(f"Already registered for {cu.code}")
                continue
            en.registration_date = t
            en.save()
            registered.append({"id": en.id, "course_code": cu.code, "course_name": cu.name})
        if registered:
            student.is_registered = True
            if not student.registration_date:
                student.registration_date = t
            student.save()
    return {"registered": registered, "errors": errors, "registration_time": t}
