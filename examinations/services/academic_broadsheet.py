"""Programme academic broadsheet: one row per student, Score / Grade / GP per course."""
from __future__ import annotations

from decimal import Decimal
from io import BytesIO

from django.db.models import Q
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from Programs.models import CourseUnit, StudentCourseUnitEnrollment
from admissions.faculty_scope import filter_course_units_for_user

from ..models import CourseUnitResult


def _plain_number(value):
    if value is None:
        return None
    number = Decimal(str(value))
    if number == number.to_integral():
        return int(number)
    return float(number)


def _student_label(student) -> str:
    name = (getattr(student, "full_name", None) or "").strip()
    application = getattr(student, "application", None)
    title = (getattr(application, "title", None) or "").strip()
    if title and name and not name.lower().startswith(title.lower()):
        return f"{title} {name}"
    return name or "—"


def build_academic_broadsheet(
    user,
    *,
    program_id=None,
    program_batch_id=None,
    semester_id=None,
    first_sitting_only=False,
    include_semester_one=False,
) -> dict:
    """Scoped to the caller's faculty. Reachable only via AcademicBroadsheetView,
    which requires CanViewAllResults (super admin / HOD / exam coordinator), so
    every caller here is already privileged to see pre-publish marks — each mark
    is tagged with its status (draft/verified/published) rather than hidden."""
    if not program_id and not program_batch_id:
        raise ValueError("Select a programme or a programme batch.")

    course_units = filter_course_units_for_user(
        CourseUnit.objects.filter(is_active=True),
        user,
    ).select_related("program_batch", "program_batch__program", "semester")
    if program_id:
        course_units = course_units.filter(
            Q(program_batch__program_id=program_id)
            | Q(semester__program_batch__program_id=program_id)
        )
    if program_batch_id:
        course_units = course_units.filter(
            Q(program_batch_id=program_batch_id)
            | Q(semester__program_batch_id=program_batch_id)
        )
    if semester_id or include_semester_one:
        semester_ids = [semester_id] if semester_id else []
        if include_semester_one and semester_id:
            from Programs.models import Semester

            selected = Semester.objects.filter(pk=semester_id).first()
            if (
                selected is not None
                and selected.term_number == 2
                and selected.year_of_study
            ):
                earlier = Semester.objects.filter(
                    program_batch_id=selected.program_batch_id,
                    year_of_study=selected.year_of_study,
                    term_number=1,
                ).values_list("id", flat=True)
                semester_ids.extend(earlier)
        semester_ids = [sid for sid in semester_ids if sid]
        if semester_ids:
            course_units = course_units.filter(semester_id__in=semester_ids)
    course_units = list(course_units.distinct().order_by("code", "id"))
    if not course_units:
        return {
            "program_name": "",
            "batch_name": "",
            "semester_name": "",
            "published_only": True,
            "first_sitting_only": first_sitting_only,
            "include_semester_one": include_semester_one,
            "courses": [],
            "students": [],
        }

    program_name = ""
    batch_name = ""
    semester_name = ""
    for unit in course_units:
        batch = unit.program_batch or (unit.semester.program_batch if unit.semester_id else None)
        if batch is not None and not batch_name:
            batch_name = batch.name or ""
            program_name = batch.program.name if batch.program_id else ""
        if unit.semester_id and not semester_name:
            semester_name = unit.semester.name or ""
        if program_name and semester_name:
            break

    courses: list[dict] = []
    seen_codes: set[str] = set()
    for unit in course_units:
        code = (unit.code or "").strip()
        if not code or code.upper() in seen_codes:
            continue
        seen_codes.add(code.upper())
        courses.append({"code": code, "name": unit.name or ""})
    courses.sort(key=lambda row: row["code"])

    enrollments = (
        StudentCourseUnitEnrollment.objects.filter(
            course_unit_id__in=[unit.id for unit in course_units],
            status__in=("enrolled", "completed"),
        )
        .select_related(
            "student",
            "student__application",
            "course_unit",
            "course_result",
        )
        .order_by("student__reg_no", "course_unit__code")
    )
    if first_sitting_only:
        enrollments = enrollments.filter(
            registration_kind=StudentCourseUnitEnrollment.KIND_NORMAL,
        )

    students: dict[int, dict] = {}
    for enrollment in enrollments:
        student = enrollment.student
        row = students.get(student.id)
        if row is None:
            row = {
                "student_id": student.id,
                "reg_no": student.reg_no or "",
                "name": _student_label(student),
                "marks": {},
            }
            students[student.id] = row
        code = (enrollment.course_unit.code or "").strip()
        if not code:
            continue
        existing = row["marks"].get(code)
        if existing and existing.get("score") is not None:
            continue
        try:
            result = enrollment.course_result
        except CourseUnitResult.DoesNotExist:
            result = None
        if result is None:
            row["marks"].setdefault(code, {"score": None, "grade": "", "gp": None, "status": ""})
            continue
        row["marks"][code] = {
            "score": _plain_number(result.final_mark),
            "grade": result.grade_letter or "",
            "gp": _plain_number(result.grade_point),
            "status": result.status,
        }

    return {
        "program_name": program_name,
        "batch_name": batch_name,
        "semester_name": semester_name,
        "published_only": False,
        "first_sitting_only": first_sitting_only,
        "include_semester_one": include_semester_one,
        "courses": courses,
        "students": sorted(students.values(), key=lambda row: (row["reg_no"], row["name"])),
    }


def academic_broadsheet_xlsx(payload: dict) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Academic report"

    courses = payload.get("courses") or []
    students = payload.get("students") or []
    title_bits = [
        payload.get("program_name") or "Programme",
        payload.get("batch_name") or "",
        payload.get("semester_name") or "",
    ]
    title = " — ".join(bit for bit in title_bits if bit)
    last_col = 2 + (len(courses) * 3)
    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(last_col, 2))
    sheet["A1"] = title or "Academic report"
    sheet["A1"].font = Font(bold=True, size=14, color="2D2960")
    sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=max(last_col, 2))
    sheet["A2"] = "Italic marks are not yet published (draft/verified) — figures may still change. Blank cells mean the student is not registered for that course."
    sheet["A2"].font = Font(italic=True, size=9, color="555555")

    header_fill = PatternFill("solid", fgColor="3E397B")
    header_font = Font(bold=True, color="FFFFFF", size=10)
    thin = Border(
        left=Side(style="thin", color="D0D0D0"),
        right=Side(style="thin", color="D0D0D0"),
        top=Side(style="thin", color="D0D0D0"),
        bottom=Side(style="thin", color="D0D0D0"),
    )
    alt_fill = PatternFill("solid", fgColor="F6F5FB")
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left = Alignment(horizontal="left", vertical="center")

    header_row = 4
    headers = ["Registration Number", "Name"]
    for course in courses:
        code = course["code"]
        headers.extend([f"{code} Score", f"{code} Grade", f"{code} GP"])
    for col, label in enumerate(headers, start=1):
        cell = sheet.cell(header_row, col, label)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = center
        cell.border = thin

    for index, student in enumerate(students):
        excel_row = header_row + 1 + index
        fill = alt_fill if index % 2 else None
        values = [student.get("reg_no") or "", student.get("name") or ""]
        pending_cols: set[int] = set()
        marks = student.get("marks") or {}
        col_cursor = 3
        for course in courses:
            mark = marks.get(course["code"]) or {}
            is_pending = bool(mark.get("status")) and mark.get("status") != CourseUnitResult.STATUS_PUBLISHED
            if is_pending:
                pending_cols.update((col_cursor, col_cursor + 1, col_cursor + 2))
            values.extend([
                mark.get("score") if mark.get("score") is not None else "",
                mark.get("grade") or "",
                mark.get("gp") if mark.get("gp") is not None else "",
            ])
            col_cursor += 3
        for col, value in enumerate(values, start=1):
            cell = sheet.cell(excel_row, col, value)
            cell.border = thin
            cell.alignment = left if col <= 2 else center
            if col in pending_cols:
                cell.font = Font(italic=True, color="7A6F9B")
            if fill is not None:
                cell.fill = fill

    sheet.freeze_panes = "C5"
    sheet.auto_filter.ref = f"A{header_row}:{get_column_letter(max(len(headers), 1))}{header_row + max(len(students), 1)}"
    sheet.column_dimensions["A"].width = 24
    sheet.column_dimensions["B"].width = 32
    for col in range(3, len(headers) + 1):
        sheet.column_dimensions[get_column_letter(col)].width = 14
    sheet.row_dimensions[header_row].height = 32
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.fitToPage = True
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.oddHeader.left.text = title
    sheet.print_title_rows = "4:4"

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
