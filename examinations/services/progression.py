"""ARMS progression standings from published results.

Semester GPA below 2.0 builds a streak. A streak longer than two semesters,
or a streak of two plus this semester also below 2.0, is discontinued on GPA.
A course failed on every sitting, with at least three sittings, is discontinued on that course.
A failed paper that was sat is probation on the course.
Credit units below the programme minimum load, when one is set, is probation
on load. Anything else is normal progress.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from admissions.faculty_scope import filter_admitted_students_for_user
from admissions.models import AdmittedStudent
from Programs.models import StudentCourseUnitEnrollment

from ..models import CourseUnitResult, StudentProgressionStanding

GPA_FLOOR = Decimal("2.0")


def _weighted_gpa(results) -> Decimal | None:
    points = Decimal("0")
    units = Decimal("0")
    for result in results:
        credit = result.enrollment.course_unit.credit_units
        if result.grade_point is None or not credit:
            continue
        units += Decimal(credit)
        points += Decimal(result.grade_point) * Decimal(credit)
    if units == 0:
        return None
    return (points / units).quantize(Decimal("0.01"))


def _is_missed(result: CourseUnitResult) -> bool:
    outcome = (result.paper_outcome or "").strip()
    if outcome == CourseUnitResult.OUTCOME_MISSED:
        return True
    return result.exam_mark is None and result.is_pass is not True


def _is_course_fail(result: CourseUnitResult) -> bool:
    return result.is_pass is False and not _is_missed(result)


def compute_student_progression(student: AdmittedStudent) -> dict:
    results = list(
        CourseUnitResult.objects.filter(
            enrollment__student=student,
            status=CourseUnitResult.STATUS_PUBLISHED,
        ).select_related(
            "enrollment",
            "enrollment__course_unit",
            "enrollment__course_unit__semester",
            "enrollment__course_unit__program_batch__program",
        )
    )

    by_semester: dict[int, list] = defaultdict(list)
    semester_order: dict[int, tuple] = {}
    for result in results:
        semester = result.enrollment.course_unit.semester
        if semester is None:
            continue
        by_semester[semester.id].append(result)
        semester_order[semester.id] = (semester.start_date, semester.id)

    ordered_ids = sorted(by_semester, key=lambda sid: semester_order[sid])
    semester_gpas = [_weighted_gpa(by_semester[sid]) for sid in ordered_ids]
    cgpa = _weighted_gpa(results)
    current_gpa = semester_gpas[-1] if semester_gpas else None
    previous_gpas = [gpa for gpa in semester_gpas[:-1] if gpa is not None]

    streak = 0
    for gpa in previous_gpas:
        if gpa < GPA_FLOOR:
            streak += 1
        else:
            streak = 0
    discontinued_gpa = streak > 2 or (
        streak == 2 and current_gpa is not None and current_gpa < GPA_FLOOR
    )

    by_code: dict[str, list] = defaultdict(list)
    for result in results:
        code = (result.enrollment.course_unit.code or "").strip().upper()
        if code:
            by_code[code].append(result)

    discontinued_codes = []
    failed_codes = []
    for code, rows in sorted(by_code.items()):
        all_failed = bool(rows) and all(row.is_pass is False for row in rows)
        if all_failed and len(rows) >= 3:
            discontinued_codes.append(code)
        elif any(_is_course_fail(row) for row in rows):
            failed_codes.append(code)

    below_load = False
    min_load = None
    if ordered_ids:
        latest_results = by_semester[ordered_ids[-1]]
        program = None
        for result in latest_results:
            batch = result.enrollment.course_unit.program_batch
            if batch is not None and batch.program_id:
                program = batch.program
                break
        if program is not None and program.modular_min_credits_per_session is not None:
            min_load = Decimal(program.modular_min_credits_per_session)
            taken = Decimal("0")
            seen_units = set()
            registered = StudentCourseUnitEnrollment.objects.filter(
                student=student,
                course_unit__semester_id=ordered_ids[-1],
                registration_date__isnull=False,
            ).select_related("course_unit")
            for enrollment in registered:
                unit = enrollment.course_unit
                if unit.id in seen_units or not unit.credit_units:
                    continue
                seen_units.add(unit.id)
                taken += Decimal(unit.credit_units)
            below_load = taken < min_load

    if discontinued_gpa:
        status = StudentProgressionStanding.STATUS_DISCONTINUED_GPA
        remark = "DISC(GPA)"
    elif discontinued_codes:
        status = StudentProgressionStanding.STATUS_DISCONTINUED_COURSE
        remark = "DISC (C) " + ", ".join(discontinued_codes)
    elif failed_codes:
        status = StudentProgressionStanding.STATUS_PROBATION_COURSE
        remark = "PP(CTR) " + ", ".join(failed_codes)
    elif below_load:
        status = StudentProgressionStanding.STATUS_PROBATION_LOAD
        remark = "PP(NL)"
    else:
        status = StudentProgressionStanding.STATUS_NORMAL
        remark = "NP"

    standing, _ = StudentProgressionStanding.objects.update_or_create(
        student=student,
        defaults={
            "status": status,
            "remark": remark[:500],
            "semester_gpa": current_gpa,
            "cgpa": cgpa,
        },
    )
    return {
        "student_id": student.id,
        "reg_no": student.reg_no or "",
        "name": getattr(student, "full_name", "") or "",
        "status": standing.status,
        "status_label": standing.get_status_display(),
        "remark": standing.remark,
        "semester_gpa": str(current_gpa) if current_gpa is not None else None,
        "cgpa": str(cgpa) if cgpa is not None else None,
        "gpa_floor": str(GPA_FLOOR),
        "minimum_load": str(min_load) if min_load is not None else None,
    }


def progression_for_scope(*, user, program_id=None, program_batch_id=None, semester_id=None) -> list[dict]:
    enrollments = StudentCourseUnitEnrollment.objects.filter(
        course_result__status=CourseUnitResult.STATUS_PUBLISHED,
    )
    if program_id:
        enrollments = enrollments.filter(course_unit__program_batch__program_id=program_id)
    if program_batch_id:
        enrollments = enrollments.filter(course_unit__program_batch_id=program_batch_id)
    if semester_id:
        enrollments = enrollments.filter(course_unit__semester_id=semester_id)
    students = filter_admitted_students_for_user(
        AdmittedStudent.objects.filter(pk__in=enrollments.values("student_id")),
        user,
    ).select_related("application").order_by("reg_no")[:500]
    return [compute_student_progression(student) for student in students]
