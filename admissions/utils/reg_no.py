import re
from datetime import datetime

from django.db import transaction

from admissions.models import AdmittedStudent


def _is_hec_program(program) -> bool:
    name = (program.name or "").lower()
    return "higher education certificate" in name


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


def _max_sequence_for_prefix(prefix: str) -> int:
    """Highest numeric suffix among reg nos that match this exact prefix."""
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    max_num = 0
    for reg_no in (
        AdmittedStudent.objects.select_for_update()
        .filter(reg_no__startswith=prefix)
        .values_list("reg_no", flat=True)
    ):
        match = pattern.match((reg_no or "").strip())
        if match:
            max_num = max(max_num, int(match.group(1)))
    return max_num


@transaction.atomic
def generate_reg_no(campus, program, study_mode, intake_month: str = "APR"):
    """
  Assign the next registration number for this cohort.

  Sequence restarts at 0001 per prefix:
    {YY}/{campus}/{program}/{study_mode}/{####}
    {YY}/{campus}/{program}/{intake}/{study_mode}/{####}  (HEC)
    """
    year = str(datetime.now().year)[-2:]
    campus_number = "2" if "kampala" in (campus.name or "").lower() else "1"

    program_code_match = re.search(r"\d+", program.code or "")
    program_code = program_code_match.group() if program_code_match else "000"

    is_hec = _is_hec_program(program)
    prefix = _reg_no_prefix(
        year,
        campus_number,
        program_code,
        study_mode,
        is_hec=is_hec,
        intake_month=intake_month,
    )

    next_number = _max_sequence_for_prefix(prefix) + 1
    formatted_number = str(next_number).zfill(4)
    return f"{prefix}{formatted_number}"
