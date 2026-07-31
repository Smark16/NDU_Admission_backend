"""Outstanding failed/missed papers and next-academic-year retake offerings."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from admissions.models import AdmittedStudent
from Programs.models import CourseUnit, StudentCourseUnitEnrollment

from ..models import CourseUnitResult


@dataclass(frozen=True)
class OutstandingPaper:
    enrollment_id: int
    course_unit_id: int
    course_code: str
    course_name: str
    year_of_study: int
    term_number: int
    semester_start: date
    semester_name: str
    paper_outcome: str  # fail | missed
    original_semester_label: str


def _period_unit(calendar_type: str | None) -> str:
    return "Trimester" if (calendar_type or "").lower() == "trimester" else "Semester"


def curriculum_period_label(
    year_of_study: int | None,
    term_number: int | None,
    *,
    calendar_type: str | None = None,
    semester_name: str | None = None,
) -> str:
    name = (semester_name or "").strip()
    if name:
        return name
    if year_of_study and term_number:
        return f"Year {year_of_study} {_period_unit(calendar_type)} {term_number}"
    return "Prior semester"


def outstanding_papers_for_student(student: AdmittedStudent) -> list[OutstandingPaper]:
    """
    Latest published fail/missed per course code with no later published pass
    for the same code.
    """
    results = (
        CourseUnitResult.objects.filter(
            enrollment__student=student,
            status=CourseUnitResult.STATUS_PUBLISHED,
        )
        .select_related(
            "enrollment",
            "enrollment__course_unit",
            "enrollment__course_unit__semester",
            "enrollment__course_unit__program_batch__program",
        )
        .order_by("enrollment__course_unit__code", "-published_at", "-id")
    )

    by_code: dict[str, CourseUnitResult] = {}
    for result in results:
        code = (result.enrollment.course_unit.code or "").strip().upper()
        if not code or code in by_code:
            continue
        by_code[code] = result

    papers: list[OutstandingPaper] = []
    for code, result in by_code.items():
        outcome = (result.paper_outcome or result.derive_paper_outcome() or "").strip()
        if outcome not in (
            CourseUnitResult.OUTCOME_FAIL,
            CourseUnitResult.OUTCOME_MISSED,
        ):
            # Legacy rows: published fail without paper_outcome
            if result.is_pass is False:
                outcome = (
                    CourseUnitResult.OUTCOME_MISSED
                    if result.exam_mark is None
                    else CourseUnitResult.OUTCOME_FAIL
                )
            else:
                continue

        cu = result.enrollment.course_unit
        sem = cu.semester
        if sem is None or not sem.year_of_study or not sem.term_number or not sem.start_date:
            continue

        cal = None
        if cu.program_batch_id and cu.program_batch.program_id:
            cal = cu.program_batch.program.calendar_type
        label = curriculum_period_label(
            sem.year_of_study,
            sem.term_number,
            calendar_type=cal,
            semester_name=sem.name,
        )
        papers.append(
            OutstandingPaper(
                enrollment_id=result.enrollment_id,
                course_unit_id=cu.id,
                course_code=cu.code,
                course_name=cu.name,
                year_of_study=int(sem.year_of_study),
                term_number=int(sem.term_number),
                semester_start=sem.start_date,
                semester_name=sem.name or "",
                paper_outcome=outcome,
                original_semester_label=label,
            )
        )
    return papers


def find_next_ay_course_unit(student: AdmittedStudent, paper: OutstandingPaper) -> CourseUnit | None:
    """
    Same curriculum Year+Term with semester.start_date strictly after the original attempt
    (coming academic year), same programme.
    """
    if not student.admitted_program_id:
        return None
    return (
        CourseUnit.objects.filter(
            code__iexact=paper.course_code,
            is_active=True,
            program_batch__program_id=student.admitted_program_id,
            semester__year_of_study=paper.year_of_study,
            semester__term_number=paper.term_number,
            semester__start_date__gt=paper.semester_start,
            semester__is_active=True,
        )
        .select_related("semester", "program_batch", "program_batch__program")
        .order_by("semester__start_date", "id")
        .first()
    )


def registration_kind_for_outcome(outcome: str) -> str:
    if outcome == CourseUnitResult.OUTCOME_MISSED:
        return StudentCourseUnitEnrollment.KIND_MISSED
    return StudentCourseUnitEnrollment.KIND_RETAKE


def next_ay_offerings_for_student(student: AdmittedStudent) -> list[dict[str, Any]]:
    """
    Course units currently available for retake/missed registration
    (next academic year, same Year+Term).
    """
    from payments.retake_fees import preview_retake_fee

    offerings: list[dict[str, Any]] = []
    fee_preview = preview_retake_fee(student)
    registered_ids = set(
        StudentCourseUnitEnrollment.objects.filter(
            student=student,
            registration_date__isnull=False,
        ).values_list("course_unit_id", flat=True)
    )

    for paper in outstanding_papers_for_student(student):
        cu = find_next_ay_course_unit(student, paper)
        if cu is None:
            offerings.append(
                {
                    "available": False,
                    "course_unit_id": None,
                    "course_code": paper.course_code,
                    "course_name": paper.course_name,
                    "registration_kind": registration_kind_for_outcome(paper.paper_outcome),
                    "paper_outcome": paper.paper_outcome,
                    "original_enrollment_id": paper.enrollment_id,
                    "original_semester_label": paper.original_semester_label,
                    "year_of_study": paper.year_of_study,
                    "term_number": paper.term_number,
                    "message": (
                        f"Available for registration in {paper.original_semester_label} "
                        "of the coming academic year (once that semester offering exists)."
                    ),
                    "fee_preview": fee_preview,
                }
            )
            continue
        if cu.id in registered_ids:
            continue
        kind = registration_kind_for_outcome(paper.paper_outcome)
        offerings.append(
            {
                "available": True,
                "course_unit_id": cu.id,
                "course_code": cu.code,
                "course_name": cu.name,
                "credit_units": float(cu.credit_units) if cu.credit_units else None,
                "registration_kind": kind,
                "paper_outcome": paper.paper_outcome,
                "original_enrollment_id": paper.enrollment_id,
                "original_semester_label": paper.original_semester_label,
                "year_of_study": paper.year_of_study,
                "term_number": paper.term_number,
                "semester": {
                    "id": cu.semester_id,
                    "name": cu.semester.name if cu.semester_id else None,
                    "year_of_study": cu.semester.year_of_study if cu.semester_id else None,
                    "term_number": cu.semester.term_number if cu.semester_id else None,
                    "start_date": (
                        cu.semester.start_date.isoformat()
                        if cu.semester_id and cu.semester.start_date
                        else None
                    ),
                },
                "program_batch": {
                    "id": cu.program_batch_id,
                    "name": cu.program_batch.name if cu.program_batch_id else None,
                },
                "message": (
                    f"{'Missed paper' if kind == 'missed' else 'Retake'} — "
                    f"{paper.original_semester_label} next sitting"
                ),
                "fee_preview": fee_preview,
            }
        )
    return offerings


def offering_meta_by_course_unit_id(student: AdmittedStudent) -> dict[int, dict[str, Any]]:
    """Map next-AY CourseUnit id → offering metadata for registration writes."""
    out: dict[int, dict[str, Any]] = {}
    for row in next_ay_offerings_for_student(student):
        cid = row.get("course_unit_id")
        if row.get("available") and cid:
            out[int(cid)] = row
    return out
