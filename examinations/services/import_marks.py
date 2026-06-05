"""Import CA and exam marks from Excel (reg_no, ca_mark, exam_mark)."""
from decimal import Decimal, InvalidOperation
from io import BytesIO

from django.core.exceptions import ValidationError
from openpyxl import load_workbook

from Programs.models import StudentCourseUnitEnrollment

from ..models import CourseUnitResult, GradeScale
from .policy_resolver import resolve_assessment_policy


def _cell_value(cell):
    if cell is None:
        return None
    v = cell.value
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    return v


def _decimal_or_none(raw):
    if raw is None:
        return None
    try:
        return Decimal(str(raw).strip())
    except (InvalidOperation, ValueError):
        raise ValidationError(f"Invalid number: {raw!r}")


def parse_marks_workbook(file_bytes: bytes) -> list[dict]:
    """Return rows: {reg_no, ca_mark, exam_mark} from first sheet."""
    wb = load_workbook(BytesIO(file_bytes), read_only=True, data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(min_row=1, values_only=False)
    header_cells = next(rows_iter, None)
    if not header_cells:
        raise ValidationError("Empty spreadsheet.")

    headers = [str(_cell_value(c) or "").strip().lower().replace(" ", "_") for c in header_cells]
    col_map = {}
    for idx, h in enumerate(headers):
        if h in ("reg_no", "regno", "registration", "registration_number"):
            col_map["reg_no"] = idx
        elif h in ("ca", "ca_mark", "continuous_assessment", "coursework"):
            col_map["ca_mark"] = idx
        elif h in ("exam", "exam_mark", "examination"):
            col_map["exam_mark"] = idx

    if "reg_no" not in col_map:
        raise ValidationError("Sheet must have a reg_no (or regno) column.")

    out = []
    for cells in rows_iter:
        reg = _cell_value(cells[col_map["reg_no"]] if col_map["reg_no"] < len(cells) else None)
        if not reg:
            continue
        row = {"reg_no": str(reg).strip()}
        if "ca_mark" in col_map and col_map["ca_mark"] < len(cells):
            row["ca_mark"] = _decimal_or_none(_cell_value(cells[col_map["ca_mark"]]))
        else:
            row["ca_mark"] = None
        if "exam_mark" in col_map and col_map["exam_mark"] < len(cells):
            row["exam_mark"] = _decimal_or_none(_cell_value(cells[col_map["exam_mark"]]))
        else:
            row["exam_mark"] = None
        out.append(row)
    wb.close()
    return out


def import_marks_for_course(course_unit, rows: list[dict], *, user) -> dict:
    """Apply import rows; returns {saved, errors}."""
    if not resolve_assessment_policy(course_unit=course_unit):
        raise ValidationError("No assessment policy configured.")

    saved = []
    errors = []

    for row in rows:
        reg = row.get("reg_no", "")
        try:
            enrollment = StudentCourseUnitEnrollment.objects.select_related(
                "student",
                "student__application",
                "course_result",
                "course_unit",
                "course_unit__program_batch__program__academic_level",
            ).get(
                course_unit=course_unit,
                status="enrolled",
                student__reg_no__iexact=reg,
            )
        except StudentCourseUnitEnrollment.DoesNotExist:
            errors.append({"reg_no": reg, "detail": "Student not enrolled on this course."})
            continue

        if enrollment.student.application and enrollment.student.application.is_revoked:
            errors.append({"reg_no": reg, "detail": "Admission revoked."})
            continue

        policy = resolve_assessment_policy(enrollment=enrollment)
        if not policy:
            errors.append({"reg_no": reg, "detail": "No assessment policy configured."})
            continue

        result, _ = CourseUnitResult.objects.get_or_create(
            enrollment=enrollment,
            defaults={"policy": policy, "entered_by": user},
        )

        if result.status == CourseUnitResult.STATUS_PUBLISHED and not result.edit_unlocked:
            errors.append(
                {"reg_no": reg, "detail": "Published — request a grade change or unlock first."}
            )
            continue

        result.policy = policy
        if row.get("ca_mark") is not None:
            result.ca_mark = row["ca_mark"]
        if row.get("exam_mark") is not None:
            result.exam_mark = row["exam_mark"]
        result.entered_by = user
        if result.status == CourseUnitResult.STATUS_PUBLISHED:
            result.status = CourseUnitResult.STATUS_VERIFIED

        try:
            result.recompute()
            result.full_clean()
            result.save()
            saved.append(reg)
        except Exception as exc:
            errors.append({"reg_no": reg, "detail": str(exc)})

    return {"saved_count": len(saved), "saved": saved, "errors": errors}
