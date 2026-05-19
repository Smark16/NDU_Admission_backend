import re
from datetime import datetime

from django.db import transaction
from django.db.models import Max

from admissions.models import AdmittedStudent

def _is_hec_program(program) -> bool:
    """Check if this is a Higher Education Certificate program."""
    name = (program.name or "").lower()
    return "higher education certificate" in name or "hec" in name


def resolve_intake_month_from_batch(batch, default: str = "APR") -> str:
    """Map an admissions intake name/code to a 3-letter month token for HEC reg nos."""
    if batch is None:
        return default
    haystack = f"{batch.code or ''} {batch.name or ''}".upper()
    for token, month in (
        ("JANUARY", "JAN"), ("JAN", "JAN"),
        ("FEBRUARY", "FEB"), ("FEB", "FEB"),
        ("MARCH", "MAR"), ("MAR", "MAR"),
        ("APRIL", "APR"), ("APR", "APR"),
        ("MAY", "MAY"),
        ("JUNE", "JUN"), ("JUN", "JUN"),
        ("JULY", "JUL"), ("JUL", "JUL"),
        ("AUGUST", "AUG"), ("AUG", "AUG"),
        ("SEPTEMBER", "SEP"), ("SEP", "SEP"),
        ("OCTOBER", "OCT"), ("OCT", "OCT"),
        ("NOVEMBER", "NOV"), ("NOV", "NOV"),
        ("DECEMBER", "DEC"), ("DEC", "DEC"),
    ):
        if token in haystack:
            return month
    return default


def _reg_no_prefix(year: str, campus_number: str, program_code: str, study_mode: str, *, is_hec: bool, intake_month: str) -> str:
    if is_hec:
        return f"{year}/{campus_number}/{program_code}/{intake_month}/{study_mode}/"
    return f"{year}/{campus_number}/{program_code}/{study_mode}/"

@transaction.atomic
def generate_reg_no(campus, program, study_mode, intake_month: str = "APR"):
    """
    Keeps your original prefix logic but uses global latest number for sequencing.
    """
    year = str(datetime.now().year)[-2:]
    campus_number = "2" if "kampala" in (campus.name or "").lower() else "1"

    program_code_match = re.search(r"\d+", program.code or "")
    program_code = program_code_match.group() if program_code_match else "000"

    is_hec = _is_hec_program(program)
    
    # === Your Original Prefix Logic ===
    prefix = _reg_no_prefix(
        year, campus_number, program_code, study_mode,
        is_hec=is_hec, intake_month=intake_month
    )

    # === NEW: Find the GLOBAL highest number across ALL reg_nos ===
    last_student = (
        AdmittedStudent.objects
        .exclude(reg_no__isnull=True)
        .exclude(reg_no="")
        .order_by('-created_at')
        .first()
    )

    if not last_student or not last_student.reg_no:
        return f"{prefix}0001"

    # Extract last 4 digits from the most recent reg_no in the system
    match = re.search(r'(\d{4})$', last_student.reg_no.strip())

    if match:
        next_number = int(match.group(1)) + 1
        if next_number > 9999:
            next_number = 9999
        formatted_number = str(next_number).zfill(4)
    else:
        formatted_number = "0001"

    return f"{prefix}{formatted_number}"