"""Bulk import admitted students into a programme batch (academic cohort)."""
from __future__ import annotations

import csv
import io
import logging
import re
from datetime import date, datetime, timedelta
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError as DRFValidationError

from accounts.models import Campus, User
from admissions.models import AcademicLevel, AdmittedStudent, Application, Batch
from admissions.serializers import AdmittedStudentSerializer
from admissions.utils.program_choices import sync_application_program_choices
from admissions.utils.reference import generate_reference
from admissions.utils.trigger_background_tasks import trigger_background_tasks
from payments.utils.school_pay_code import _schoolpay_phone
from Programs.models import Program, ProgramBatch
from Programs.specialization_rules import resolve_specialization_for_program

logger = logging.getLogger(__name__)

STUDENT_IMPORT_HEADERS = [
    "first_name",
    "last_name",
    "middle_name",
    "email",
    "phone",
    "date_of_birth",
    "gender",
    "nationality",
    "reg_no",
    "study_mode",
    "student_id",
    "specialization",
    "address",
]

STUDY_MODES = frozenset({"W", "D", "DL", "DJ", "WJ"})


def _normalize_header(name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", (name or "").strip().lower())


def _cell_to_import_value(val) -> str:
    """Normalize Excel/CSV cell values; dates from Excel often arrive as datetime or serial numbers."""
    if val is None:
        return ""
    if isinstance(val, datetime):
        return val.date().isoformat()
    if isinstance(val, date):
        return val.isoformat()
    text = str(val).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text


def _parse_date_of_birth(raw) -> date:
    """Accept YYYY-MM-DD, DD/MM/YYYY (common in Uganda), Excel serials, and datetime strings."""
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw

    text = str(raw or "").strip()
    if not text:
        raise ValueError("date_of_birth is required.")

    if text.endswith(".0") and text[:-2].replace(".", "", 1).isdigit():
        text = text[:-2]

    if re.fullmatch(r"\d+(\.\d+)?", text):
        try:
            serial = float(text)
            if 1 <= serial <= 120000:
                excel_epoch = date(1899, 12, 30)
                return excel_epoch + timedelta(days=int(serial))
        except (ValueError, OverflowError):
            pass

    if "T" in text:
        try:
            return datetime.fromisoformat(text[:19]).date()
        except ValueError:
            pass

    date_part = text.split()[0] if " " in text else text

    for fmt in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d/%m/%Y",
        "%d/%m/%y",
        "%d-%m-%Y",
        "%d-%m-%y",
        "%m/%d/%Y",
        "%m/%d/%y",
    ):
        try:
            return datetime.strptime(date_part, fmt).date()
        except ValueError:
            continue

    raise ValueError(
        f"date_of_birth '{text}' is not recognized. Use YYYY-MM-DD, DD/MM/YYYY, or a valid Excel date."
    )


def _parse_upload_file(uploaded_file) -> tuple[list[str], list[dict]]:
    raw = uploaded_file.read()
    if not raw:
        raise ValueError("Uploaded file is empty.")

    name = (getattr(uploaded_file, "name", "") or "").lower()
    if name.endswith(".xlsx") or name.endswith(".xls"):
        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            raise ValueError("Excel support requires openpyxl on the server.") from exc
        wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
        try:
            header_row = next(rows_iter)
        except StopIteration:
            raise ValueError("Excel sheet is empty.")
        headers = [_normalize_header(str(c or "")) for c in header_row]
        rows = []
        for idx, cells in enumerate(rows_iter, start=2):
            if not any(c is not None and str(c).strip() for c in cells):
                continue
            row = {}
            for col_idx, key in enumerate(headers):
                if not key:
                    continue
                val = cells[col_idx] if col_idx < len(cells) else None
                row[key] = _cell_to_import_value(val)
            rows.append({"__row__": idx, **row})
        return headers, rows

    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row.")
    headers = [_normalize_header(h) for h in reader.fieldnames]
    rows = []
    for idx, raw_row in enumerate(reader, start=2):
        if not any(str(v or "").strip() for v in raw_row.values()):
            continue
        row = {"__row__": idx}
        for orig, norm in zip(reader.fieldnames, headers):
            if norm:
                row[norm] = (raw_row.get(orig) or "").strip()
        rows.append(row)
    return headers, rows


def _resolve_admission_intake_batch(admission_batch_id: int | None) -> Batch:
    """
    Admissions intake (``admissions.Batch``) is still stored on each student for legacy
    fields and SchoolPay, but import targets the **academic** ``ProgramBatch``. When the
    client does not send an intake id, use the current active admission intake.
    """
    if admission_batch_id is not None:
        try:
            return Batch.objects.get(pk=admission_batch_id)
        except Batch.DoesNotExist as exc:
            raise ValueError("Admission intake batch not found.") from exc

    from admissions.utils.batch_offer_filters import batch_offer_window_q

    now = timezone.now().date()
    batch = (
        Batch.objects.filter(is_active=True)
        .filter(batch_offer_window_q())
        .filter(
            Q(application_start_date__lte=now, application_end_date__gte=now)
            | Q(admission_start_date__lte=now, admission_end_date__gte=now)
        )
        .order_by("-created_at")
        .first()
    )
    if batch is None:
        batch = (
            Batch.objects.filter(is_active=True)
            .order_by("-created_at")
            .first()
        )
    if batch is None:
        raise ValueError(
            "No active admission intake batch. Configure one under Admissions → Admission Intakes."
        )
    return batch


def _require_columns(headers: list[str]) -> list[str]:
    missing = []
    for col in (
        "first_name",
        "last_name",
        "email",
        "phone",
        "date_of_birth",
        "gender",
        "nationality",
        "reg_no",
        "study_mode",
    ):
        if col not in headers:
            missing.append(col)
    return missing


def _link_legacy_schoolpay_code(admitted: AdmittedStudent, paycode: str) -> None:
    """Preserve an existing SchoolPay payment code from the legacy system."""
    code = paycode.strip()
    if not code:
        raise ValueError("Legacy student_id (SchoolPay payment code) cannot be empty.")
    if (
        AdmittedStudent.objects.filter(student_id=code)
        .exclude(pk=admitted.pk)
        .exists()
    ):
        raise ValueError(f"SchoolPay payment code '{code}' is already linked to another student.")
    if (
        AdmittedStudent.objects.filter(schoolpay_code=code)
        .exclude(pk=admitted.pk)
        .exists()
    ):
        raise ValueError(f"SchoolPay payment code '{code}' is already in use.")

    admitted.student_id = code
    admitted.schoolpay_code = code
    admitted.is_registered_with_schoolpay = True
    admitted.save(
        update_fields=[
            "student_id",
            "schoolpay_code",
            "is_registered_with_schoolpay",
            "updated_at",
        ]
    )


def _ensure_schoolpay_protection(
    admitted: AdmittedStudent,
    row: dict,
    *,
    register_schoolpay: bool,
) -> str:
    """
    Every imported student must have a SchoolPay payment code (student_id) so tuition
    is tied to the correct wallet. Legacy rows supply student_id in the file; new rows
    are registered via the SchoolPay API (same as direct admission).
    """
    legacy_paycode = row.get("student_id", "").strip()
    if legacy_paycode:
        _link_legacy_schoolpay_code(admitted, legacy_paycode)
        return legacy_paycode

    if not register_schoolpay:
        raise ValueError(
            "SchoolPay registration is required when student_id is not provided. "
            "Add the legacy payment code in the student_id column, or allow SchoolPay registration."
        )

    if admitted.is_registered_with_schoolpay and (admitted.student_id or "").strip():
        return admitted.student_id.strip()

    from payments.utils.school_pay_code import register_student_with_schoolpay

    result = register_student_with_schoolpay(admitted)
    if not result.get("success"):
        raise ValueError(
            f"SchoolPay registration failed: {result.get('error') or 'unknown error'}"
        )
    admitted.refresh_from_db()
    paycode = (admitted.student_id or "").strip()
    if not paycode:
        raise ValueError("SchoolPay registration succeeded but no payment code was stored.")
    return paycode


def _import_one_row(
    *,
    row: dict,
    program: Program,
    program_batch: ProgramBatch,
    admission_batch: Batch,
    campus: Campus,
    academic_level: AcademicLevel,
    admitted_by,
    register_schoolpay: bool,
) -> AdmittedStudent:
    first_name = row.get("first_name", "").strip()
    last_name = row.get("last_name", "").strip()
    email = row.get("email", "").strip().lower()
    phone_raw = row.get("phone", "").strip()
    phone = _schoolpay_phone(phone_raw)
    if not phone or len(re.sub(r"\D", "", phone)) != 10:
        raise ValueError(
            "phone must be a valid Ugandan mobile number (10 digits, e.g. 0701234567)."
        )
    reg_no = row.get("reg_no", "").strip()
    study_mode = row.get("study_mode", "").strip().upper()

    if not first_name or not last_name:
        raise ValueError("first_name and last_name are required.")
    if not email:
        raise ValueError("email is required.")
    if not phone:
        raise ValueError("phone is required.")
    if not reg_no:
        raise ValueError("reg_no is required.")
    if study_mode not in STUDY_MODES:
        raise ValueError(f"study_mode must be one of: {', '.join(sorted(STUDY_MODES))}.")
    if AdmittedStudent.objects.filter(reg_no=reg_no).exists():
        raise ValueError(f"reg_no '{reg_no}' is already in use.")

    try:
        dob_date = _parse_date_of_birth(row.get("date_of_birth", ""))
    except ValueError as exc:
        raise ValueError(str(exc)) from exc

    specialization = None
    spec_raw = row.get("specialization", "").strip()
    if spec_raw:
        matched, spec_err = resolve_specialization_for_program(program, spec_raw)
        if spec_err:
            raise ValueError(spec_err)
        specialization = matched

    applicant_user = User.objects.filter(email=email, is_applicant=True).first()
    if not applicant_user:
        base_username = email.split("@")[0]
        username = base_username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}_{counter}"
            counter += 1
        applicant_user = User.objects.create_user(
            username=username,
            first_name=first_name,
            last_name=last_name,
            email=email,
            password="NDU@1234",
            is_applicant=True,
            allow_multi_campus_per_day=False,
            primary_campus=campus,
        )

    application = Application.objects.create(
        applicant=applicant_user,
        batch=admission_batch,
        campus=campus,
        academic_level=academic_level,
        source=Application.SOURCE_LEGACY,
        status="Admitted",
        application_reference=generate_reference(),
        first_name=first_name,
        last_name=last_name,
        middle_name=row.get("middle_name", "").strip(),
        date_of_birth=dob_date,
        gender=row.get("gender", "").strip(),
        nationality=row.get("nationality", "").strip(),
        phone=phone,
        email=email,
        address=row.get("address", "").strip(),
    )
    sync_application_program_choices(application, [program.id])

    payload = {
        "application": application.pk,
        "reg_no": reg_no,
        "admitted_program": program.pk,
        "admitted_batch": admission_batch.pk,
        "admitted_campus": campus.pk,
        "study_mode": study_mode,
        "is_admitted": True,
        "admission_date": timezone.now(),
        "admitted_by": admitted_by.pk if admitted_by else None,
        "intended_program_batch": program_batch.pk,
        "admission_notes": f"Bulk import into academic batch: {program_batch.name}.",
    }
    serializer = AdmittedStudentSerializer(data=payload)
    serializer.is_valid(raise_exception=True)
    admitted = serializer.save()

    if specialization and hasattr(admitted, "programme_enrollment"):
        try:
            spe = admitted.programme_enrollment
            spe.specialization = specialization
            spe.save(update_fields=["specialization", "updated_at"])
        except Exception:
            pass

    paycode = _ensure_schoolpay_protection(
        admitted,
        row,
        register_schoolpay=register_schoolpay,
    )

    transaction.on_commit(
        lambda aid=admitted.id, app_id=application.id: trigger_background_tasks(aid, app_id)
    )
    admitted._import_paycode = paycode  # noqa: SLF001
    return admitted


def process_student_batch_import(
    *,
    uploaded_file,
    program_batch_id: int,
    campus_id: int,
    admitted_by,
    admission_batch_id: int | None = None,
    register_schoolpay: bool = True,
    skip_existing_reg_no: bool = False,
) -> dict:
    try:
        program_batch = ProgramBatch.objects.select_related("program").get(pk=program_batch_id)
    except ProgramBatch.DoesNotExist:
        raise ValueError("Academic programme batch not found.")

    admission_batch = _resolve_admission_intake_batch(admission_batch_id)

    try:
        campus = Campus.objects.get(pk=campus_id)
    except Campus.DoesNotExist:
        raise ValueError("Campus not found.")

    program = program_batch.program
    if program_batch.program_id != program.id:
        raise ValueError("Programme batch does not match programme.")

    academic_level = program.academic_level
    if academic_level is None:
        raise ValueError("Programme has no academic level configured.")

    headers, rows = _parse_upload_file(uploaded_file)
    missing = _require_columns(headers)
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")
    if not rows:
        raise ValueError("No data rows found in file.")

    created = 0
    skipped = 0
    failed = 0
    errors: list[str] = []
    created_students: list[dict] = []
    skipped_students: list[dict] = []

    for row in rows:
        row_num = row.get("__row__", "?")
        reg_no = row.get("reg_no", "").strip()
        try:
            if skip_existing_reg_no and reg_no:
                existing = (
                    AdmittedStudent.objects.filter(reg_no=reg_no)
                    .select_related("application")
                    .first()
                )
                if existing is not None:
                    if existing.intended_program_batch_id != program_batch.id:
                        existing.intended_program_batch = program_batch
                        existing.save(
                            update_fields=["intended_program_batch", "updated_at"]
                        )
                        AdmittedStudentSerializer._sync_programme_enrollment_batch(existing)
                    skipped += 1
                    skipped_students.append(
                        {
                            "id": existing.id,
                            "reg_no": existing.reg_no,
                            "student_id": existing.student_id,
                            "name": existing.full_name,
                            "note": "Already in system — batch updated if needed.",
                        }
                    )
                    continue

            with transaction.atomic():
                admitted = _import_one_row(
                    row=row,
                    program=program,
                    program_batch=program_batch,
                    admission_batch=admission_batch,
                    campus=campus,
                    academic_level=academic_level,
                    admitted_by=admitted_by,
                    register_schoolpay=register_schoolpay,
                )
            created += 1
            paycode = getattr(admitted, "_import_paycode", None) or admitted.student_id
            created_students.append(
                {
                    "id": admitted.id,
                    "reg_no": admitted.reg_no,
                    "student_id": paycode,
                    "schoolpay_registered": bool(admitted.is_registered_with_schoolpay),
                    "name": f"{row.get('first_name', '')} {row.get('last_name', '')}".strip(),
                }
            )
        except (ValueError, DRFValidationError) as exc:
            failed += 1
            if isinstance(exc, DRFValidationError):
                detail = exc.detail
                msg = str(detail) if not isinstance(detail, dict) else "; ".join(
                    f"{k}: {v}" for k, v in detail.items()
                )
            else:
                msg = str(exc)
            errors.append(f"Row {row_num}: {msg}")
        except Exception as exc:
            failed += 1
            logger.exception("Bulk import row %s failed", row_num)
            errors.append(f"Row {row_num}: {exc}")

    return {
        "program_batch_id": program_batch.id,
        "program_batch_name": program_batch.name,
        "program_name": program.name,
        "created": created,
        "skipped": skipped,
        "failed": failed,
        "errors": errors[:100],
        "created_students": created_students[:50],
        "skipped_students": skipped_students[:50],
    }


def build_student_import_template_csv() -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(STUDENT_IMPORT_HEADERS)
    writer.writerow(
        [
            "Jane",
            "Doe",
            "",
            "jane.doe@example.com",
            "0701234567",
            "2000-05-15",
            "Female",
            "Ugandan",
            "26/1/100/D/0001",
            "D",
            "1701234567",
            "",
            "Kampala",
        ]
    )
    return buf.getvalue()
