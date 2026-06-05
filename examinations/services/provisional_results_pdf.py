"""NDEJJE results PDF — ARMS layout (Provisional Results / Academic Transcript)."""
from __future__ import annotations

import base64
import io
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

from admissions.models import AdmittedStudent
from Programs.models import Semester

from ..models import CourseUnitResult
from .graduation_status import (
    get_transcript_document_meta,
    graduation_show_scores_default,
)
from .award_classification import resolve_award_class
from .transcript import build_student_transcript

PROVISIONAL_DISCLAIMER = (
    "For Official Purposes, this document must carry the official<br />"
    "signature of the Faculty Examination Officer and an official<br />"
    "stamp. Please note that this is not an official<br />"
    "transcript. Transcripts can only be obtained from the Academic<br />"
    "Registrar"
)

TRANSCRIPT_DISCLAIMER = (
    "For Official Purposes, this document must carry the official<br />"
    "signature and stamp of the Academic Registrar. This academic<br />"
    "transcript is issued under the authority of Ndejje University."
)


def _ordinal_year(n: int | None) -> str:
    if not n:
        return "YEAR"
    words = {1: "ONE", 2: "TWO", 3: "THREE", 4: "FOUR", 5: "FIVE", 6: "SIX"}
    return f"YEAR {words.get(n, str(n))}"


MIN_COURSE_ROWS = 6


def _empty_panel(year_num: int, term_num: int, academic_year_label: str) -> dict:
    return {
        "year_heading": _ordinal_year(year_num),
        "academic_year": academic_year_label,
        "semester_heading": f"Semester {term_num}",
        "year_num": year_num,
        "term_num": term_num,
        "courses": [],
        "term_tcus": 0,
        "term_ctcus": 0,
        "term_gpa": "0",
        "cgpa": "0.0",
    }


def _totals_text(panel: dict, *, tcu_label_only: bool = False) -> str:
    if tcu_label_only:
        return f"TCUs: {panel['term_tcus']}&nbsp;&nbsp;&nbsp;&nbsp; GPA: {panel['term_gpa']}"
    return (
        f"CTCUs: {panel['term_ctcus']}&nbsp;&nbsp;&nbsp; GPA: {panel['term_gpa']}"
        f"&nbsp;&nbsp;&nbsp; CGPA: {panel['cgpa']}"
    )


def _pad_course_rows(courses: list, row_count: int) -> list:
    rows = list(courses)
    while len(rows) < row_count:
        rows.append(None)
    return rows


def _build_year_blocks(panels: list[dict]) -> list[dict]:
    """Pair semesters per year (left = sem 1, right = sem 2) for ARMS grid."""
    from collections import defaultdict

    by_year: dict[int, list] = defaultdict(list)
    for p in panels:
        yn = p.get("year_num") or 1
        by_year[yn].append(p)

    if not by_year:
        by_year = {1: [], 2: [], 3: []}

    year_blocks = []
    is_first_year_block = True
    ay_fallback = panels[0]["academic_year"] if panels else ""

    for year_num in sorted(by_year.keys()):
        sems = sorted(by_year[year_num], key=lambda p: p.get("term_num", 1))
        ay = sems[0]["academic_year"] if sems else ay_fallback
        while len(sems) < 2:
            term_num = len(sems) + 1
            sems.append(_empty_panel(year_num, term_num, ay))

        left, right = sems[0], sems[1]
        row_count = max(len(left["courses"]), len(right["courses"]), MIN_COURSE_ROWS)
        left_rows = _pad_course_rows(left["courses"], row_count)
        right_rows = _pad_course_rows(right["courses"], row_count)

        year_blocks.append(
            {
                "year_heading": _ordinal_year(year_num),
                "left_header": (
                    f"{_ordinal_year(year_num)}&nbsp;&nbsp;&nbsp; Academic Year: "
                    f"{left['academic_year']}&nbsp;&nbsp;&nbsp; {left['semester_heading']}"
                ),
                "right_header": (
                    f"{_ordinal_year(year_num)}&nbsp;&nbsp;&nbsp; Academic Year: "
                    f"{right['academic_year']}&nbsp;&nbsp;&nbsp; {right['semester_heading']}"
                ),
                "course_rows": list(zip(left_rows, right_rows)),
                "left_totals": _totals_text(left, tcu_label_only=is_first_year_block),
                "right_totals": _totals_text(right),
            }
        )
        is_first_year_block = False

    return year_blocks


def _load_logo_b64() -> str:
    backend_root = Path(settings.BASE_DIR)
    workspace_root = backend_root.parent
    candidates = [
        workspace_root / "NDU_Admission_Frontend" / "public" / "Ndejje_University_Logo.png",
        workspace_root / "NDU_Admission_Frontend" / "public" / "Ndejje_University_Logo.jpg",
        workspace_root / "NDU-HORIZON" / "public" / "Ndejje_University_Logo.png",
        backend_root / "static" / "Ndejje_University_Logo.png",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        mime = "jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "png"
        with path.open("rb") as fh:
            encoded = base64.b64encode(fh.read()).decode("ascii")
        return f"data:image/{mime};base64,{encoded}"
    return ""


def _client_ip(request) -> str:
    if not request:
        return ""
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or ""


def _latest_graduation_assignment(student: AdmittedStudent):
    from graduation.models import GraduationAssignment

    return (
        GraduationAssignment.objects.filter(student=student)
        .select_related("session__ceremony")
        .order_by("-session__graduation_date")
        .first()
    )


def build_provisional_results_context(
    student: AdmittedStudent,
    *,
    show_scores: bool = True,
    printed_by: str = "",
    request=None,
    document_kind: str | None = None,
) -> dict:
    """Build template context matching Ndejje ARMS provisional / transcript layout."""
    doc_meta = get_transcript_document_meta(student)
    if document_kind in ("provisional_results", "academic_transcript"):
        graduated = document_kind == "academic_transcript"
        doc_meta = {
            "kind": document_kind,
            "title": "Academic Transcript" if graduated else "Provisional Results",
            "is_graduated": graduated,
            "filename_prefix": "Academic_Transcript" if graduated else "Provisional_Results",
        }

    app = student.application
    program_batch = None
    try:
        program_batch = student.programme_enrollment.program_batch
    except Exception:
        pass
    if not program_batch:
        program_batch = student.intended_program_batch

    academic_year_label = ""
    if program_batch and getattr(program_batch, "academic_year", None):
        academic_year_label = program_batch.academic_year
    elif student.admitted_batch:
        academic_year_label = getattr(student.admitted_batch, "name", "") or ""

    results = CourseUnitResult.objects.filter(
        enrollment__student=student,
        status=CourseUnitResult.STATUS_PUBLISHED,
    ).select_related(
        "enrollment__course_unit",
        "enrollment__course_unit__semester",
        "enrollment__course_unit__semester__program_batch",
    )

    by_semester_id: dict[int, list] = {}
    for r in results:
        sem = r.enrollment.course_unit.semester
        if not sem:
            continue
        by_semester_id.setdefault(sem.id, []).append(
            {
                "code": r.enrollment.course_unit.code,
                "name": r.enrollment.course_unit.name,
                "credit_units": float(r.enrollment.course_unit.credit_units or 0) or None,
                "score": int(r.final_mark) if r.final_mark is not None and show_scores else "",
                "grade": r.grade_letter or "",
                "grade_point": float(r.grade_point) if r.grade_point is not None else None,
            }
        )

    semesters_qs = Semester.objects.none()
    if program_batch:
        semesters_qs = Semester.objects.filter(
            program_batch=program_batch, is_active=True
        ).order_by("year_of_study", "term_number", "order")

    panels = []
    cumulative_credits = Decimal("0")
    cumulative_weighted = Decimal("0")

    for sem in semesters_qs:
        courses = by_semester_id.get(sem.id, [])
        term_credits = Decimal("0")
        term_weighted = Decimal("0")
        for c in courses:
            cu = Decimal(str(c["credit_units"] or 0))
            gp = c.get("grade_point")
            if cu and gp is not None:
                term_credits += cu
                term_weighted += cu * Decimal(str(gp))

        cumulative_credits += term_credits
        cumulative_weighted += term_weighted

        term_gpa = None
        if term_credits:
            term_gpa = (term_weighted / term_credits).quantize(Decimal("0.1"))

        cgpa = None
        if cumulative_credits:
            cgpa = (cumulative_weighted / cumulative_credits).quantize(Decimal("0.01"))

        ay = academic_year_label
        if sem.start_date:
            y = sem.start_date.year
            ay = f"{y}/{y + 1}"

        panels.append(
            {
                "year_heading": _ordinal_year(sem.year_of_study),
                "year_num": sem.year_of_study or max(1, (sem.order or 1 + 1) // 2),
                "term_num": sem.term_number or sem.order or 1,
                "academic_year": ay,
                "semester_heading": f"Semester {sem.term_number or sem.order}",
                "courses": courses,
                "term_tcus": int(term_credits) if term_credits else 0,
                "term_ctcus": int(cumulative_credits) if cumulative_credits else 0,
                "term_gpa": str(term_gpa) if term_gpa is not None else "0",
                "cgpa": str(cgpa) if cgpa is not None else "0.0",
            }
        )

    if not panels:
        tr = build_student_transcript(student)
        for idx, block in enumerate(tr.get("semesters", [])):
            panels.append(
                {
                    "year_heading": block.get("name", "RESULTS"),
                    "year_num": (idx // 2) + 1,
                    "term_num": (idx % 2) + 1,
                    "academic_year": academic_year_label,
                    "semester_heading": f"Semester {(idx % 2) + 1}",
                    "courses": [
                        {
                            "code": c["course_code"],
                            "name": c["course_name"],
                            "credit_units": c.get("credit_units"),
                            "score": int(float(c["final_mark"]))
                            if c.get("final_mark") and show_scores
                            else "",
                            "grade": c.get("grade_letter", ""),
                            "grade_point": float(c["grade_point"])
                            if c.get("grade_point")
                            else None,
                        }
                        for c in block.get("courses", [])
                    ],
                    "term_tcus": 0,
                    "term_ctcus": int(tr["summary"].get("total_credit_units") or 0),
                    "term_gpa": "0",
                    "cgpa": str(tr["summary"].get("cgpa") or "0.0"),
                }
            )

    if not panels:
        for year in (1, 2, 3):
            for term in (1, 2):
                panels.append(_empty_panel(year, term, academic_year_label))

    summary = build_student_transcript(student).get("summary", {})
    cgpa_final = summary.get("cgpa")

    assignment = _latest_graduation_assignment(student)
    class_of_award = (resolve_award_class(cgpa_final, student=student) or "").upper()
    if assignment and assignment.award_class:
        class_of_award = assignment.award_class.upper()

    photo_b64 = None
    if app and app.passport_photo:
        try:
            with app.passport_photo.open("rb") as fh:
                photo_b64 = base64.b64encode(fh.read()).decode("ascii")
        except Exception:
            photo_b64 = None

    faculty_name = ""
    if student.admitted_program:
        faculty_name = (
            student.admitted_program.faculty.name
            if getattr(student.admitted_program, "faculty_id", None)
            and student.admitted_program.faculty
            else student.admitted_program.name
        )

    dob_str = ""
    if app and app.date_of_birth:
        dob_str = app.date_of_birth.strftime("%d/%m/%Y")

    gender = (app.gender.upper() if app and app.gender else "") or ""
    nationality = (app.nationality.upper() if app and app.nationality else "UGANDAN") or "UGANDAN"

    graduated = doc_meta["is_graduated"]
    year_blocks = _build_year_blocks(panels)

    return {
        "student": {
            "name": (student.full_name or "").upper(),
            "sex": gender,
            "nationality": nationality,
            "reg_no": student.reg_no or "",
            "hall": "",
            "first_registration": academic_year_label or "",
            "faculty": faculty_name.upper(),
            "date_of_birth": dob_str,
            "photo_b64": photo_b64,
        },
        "year_blocks": year_blocks,
        "show_scores": show_scores,
        "logo_b64": _load_logo_b64(),
        "award": (student.admitted_program.name if student.admitted_program else "").upper(),
        "class_of_award": class_of_award,
        "printed_by": printed_by or "NDU Portal",
        "printed_from": _client_ip(request),
        "printed_at": timezone.localtime().strftime("%d/%m/%Y %I:%M %p"),
        "document_title": doc_meta["title"],
        "document_kind": doc_meta["kind"],
        "is_graduated": graduated,
        "disclaimer": TRANSCRIPT_DISCLAIMER if graduated else PROVISIONAL_DISCLAIMER,
        "signatory_label": "Academic Registrar" if graduated else "Faculty Examination Coordinator",
    }


def render_provisional_results_pdf(
    student: AdmittedStudent,
    *,
    show_scores: bool | None = None,
    printed_by: str = "",
    request=None,
) -> tuple[bytes, dict]:
    """Render PDF bytes and document metadata (title, filename prefix)."""
    if show_scores is None:
        show_scores = graduation_show_scores_default(student)

    context = build_provisional_results_context(
        student, show_scores=show_scores, printed_by=printed_by, request=request
    )
    html = render_to_string("examinations/provisional_results.html", context)
    from xhtml2pdf import pisa

    pdf_buffer = io.BytesIO()
    base_url = str(Path(settings.BASE_DIR).as_uri()) + "/"
    result = pisa.CreatePDF(html, dest=pdf_buffer, link_callback=lambda *args: base_url)
    if result.err:
        raise RuntimeError("Results document PDF generation failed.")
    pdf_buffer.seek(0)
    meta = get_transcript_document_meta(student)
    return pdf_buffer.read(), meta


# Backward-compatible alias
build_results_document_context = build_provisional_results_context
render_results_document_pdf = render_provisional_results_pdf
