# import re
# from datetime import datetime

# from django.db import transaction
# from django.db.models import Max

# from admissions.models import AdmittedStudent

# def _is_hec_program(program) -> bool:
#     name = (program.name or "").lower()
#     return "higher education certificate" in name or "hec" in name

# def resolve_intake_month_from_batch(batch, default: str = "APR") -> str:
#     if not batch:
#         return default

#     # If batch is a ProgramBatch instance
#     if hasattr(batch, 'name') and hasattr(batch, 'start_date'):
#         haystack = f"{batch.name or ''} {getattr(batch, 'academic_year', '')}".upper()
        
#         # Try to get month from start_date first (most reliable)
#         if hasattr(batch, 'start_date') and batch.start_date:
#             month = batch.start_date.strftime("%b").upper()  
#             return month[:3]

#     # Fallback: search in name/code
#     haystack = f"{getattr(batch, 'code', '')} {getattr(batch, 'name', '')} {getattr(batch, 'academic_year', '')}".upper()

#     month_map = {
#         "JANUARY": "JAN", "JAN": "JAN",
#         "FEBRUARY": "FEB", "FEB": "FEB",
#         "MARCH": "MAR", "MAR": "MAR",
#         "APRIL": "APR", "APR": "APR",
#         "MAY": "MAY",
#         "JUNE": "JUN", "JUN": "JUN",
#         "JULY": "JUL", "JUL": "JUL",
#         "AUGUST": "AUG", "AUG": "AUG",
#         "SEPTEMBER": "SEP", "SEP": "SEP",
#         "OCTOBER": "OCT", "OCT": "OCT",
#         "NOVEMBER": "NOV", "NOV": "NOV",
#         "DECEMBER": "DEC", "DEC": "DEC",
#     }

#     for token, month in month_map.items():
#         if token in haystack:
#             return month

#     return default

# def _reg_no_prefix(year: str, campus_number: str, program_code: str, study_mode: str, *, is_hec: bool, intake_month: str) -> str:
#     if is_hec:
#         return f"{year}/{campus_number}/{program_code}/{intake_month}/{study_mode}/"
#     return f"{year}/{campus_number}/{program_code}/{study_mode}/"

# @transaction.atomic
# def generate_reg_no(campus, program, study_mode, batch=None, intake_month: str = 'APR'):
#     year = str(datetime.now().year)[-2:]
#     campus_number = "2" if "kampala" in (campus.name or "").lower() else "1"

#     program_code_match = re.search(r"\d+", program.code or "")
#     program_code = program_code_match.group() if program_code_match else "000"

#     is_hec = _is_hec_program(program)

#      # === Get Intake Month from Batch ===
#     # intake_month = resolve_intake_month_from_batch(batch, default="APR")
    
#     # === Your Original Prefix Logic ===
#     prefix = _reg_no_prefix(
#         year, campus_number, program_code, study_mode,
#         is_hec=is_hec, intake_month=intake_month
#     )

#     # === NEW: Find the GLOBAL highest number across ALL reg_nos ===
#     last_student = (
#         AdmittedStudent.objects
#         .exclude(reg_no__isnull=True)
#         .exclude(reg_no="")
#         .order_by('-created_at')
#         .first()
#     )

#     if not last_student or not last_student.reg_no:
#         return f"{prefix}0001"

#     # Extract last 4 digits from the most recent reg_no in the system
#     match = re.search(r'(\d{4})$', last_student.reg_no.strip())

#     if match:
#         next_number = int(match.group(1)) + 1
#         if next_number > 9999:
#             next_number = 9999
#         formatted_number = str(next_number).zfill(4)
#     else:
#         formatted_number = "0001"

#     return f"{prefix}{formatted_number}"

import re
from datetime import datetime

from django.db import transaction
from django.db.models import Max

from admissions.models import AdmittedStudent

# get hec program
def _is_hec_program(program):
    return program.is_hec

# get intake letter
def resolve_hec_intake_letter(batch=None):
    if not batch:
        return "A"

    batch_name = (batch.name or "").upper()

    if "AUG" in batch_name or "AUGUST" in batch_name:
        return "B"

    return "A"

# prefix format: YY/CAMPUS/PROGCODE/INTAKE/SMODE/
def _reg_no_prefix(year,campus_number, program_code, study_mode, *, is_hec, intake_letter=None):
    if is_hec:
        return (
            f"{year}/"
            f"{campus_number}/"
            f"{intake_letter}/"
            f"{program_code}/"
            f"{study_mode}/"
        )

    return (
        f"{year}/"
        f"{campus_number}/"
        f"{program_code}/"
        f"{study_mode}/"
    )

# generate reg no
@transaction.atomic
def generate_reg_no(campus,program,study_mode,batch=None):
    year = str(datetime.now().year)[-2:]

    campus_number = (
        "2"
        if "kampala" in (campus.name or "").lower()
        else "1"
    )

    program_code_match = re.search(
        r"\d+",
        program.code or ""
    )

    program_code = (
        program_code_match.group()
        if program_code_match
        else "000"
    )

    is_hec = _is_hec_program(program)

    intake_letter = None

    if is_hec:
        intake_letter = resolve_hec_intake_letter(batch)

    prefix = _reg_no_prefix(
        year=year,
        campus_number=campus_number,
        program_code=program_code,
        study_mode=study_mode,
        is_hec=is_hec,
        intake_letter=intake_letter,
    )

    last_student = (
        AdmittedStudent.objects
        .select_for_update()
        .exclude(reg_no__isnull=True)
        .exclude(reg_no="")
        .order_by("-id")
        .first()
    )

    if not last_student:
        serial = 1

    else:
        match = re.search(
            r"(\d+)$",
            last_student.reg_no
        )

        serial = (
            int(match.group(1)) + 1
            if match
            else 1
        )

    return f"{prefix}{serial:03d}"