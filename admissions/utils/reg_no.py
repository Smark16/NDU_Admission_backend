# import re
# from admissions.models import AdmittedStudent
# from datetime import datetime
# from django.db import transaction

# @transaction.atomic
# def generate_reg_no(campus, program, study_mode):
#     year = str(datetime.now().year)[-2:]

#     campus_number = "2" if "kampala" in campus.name.lower() else "1"

#     program_code_match = re.search(r'\d+', program.code or "")
#     program_code = program_code_match.group() if program_code_match else "000"

#     # 🔥 LOCK rows to prevent duplicates
#     last_student = (
#         AdmittedStudent.objects
#         .select_for_update()
#         .order_by('-created_at')
#         .first()
#     )

#     if last_student and last_student.reg_no:
#         last_number = int(last_student.reg_no.split('/')[-1])
#         next_number = last_number + 1
#     else:
#         next_number = 1

#     formatted_number = str(next_number).zfill(4)

#     return f"{year}/{campus_number}/{program_code}/{study_mode}/{formatted_number}"

import re
from admissions.models import AdmittedStudent
from datetime import datetime
from django.db import transaction


@transaction.atomic
def generate_reg_no(campus, program, study_mode):
    year = str(datetime.now().year)[-2:]

    campus_number = "2" if "kampala" in campus.name.lower() else "1"

    program_code_match = re.search(r'\d+', program.code or "")
    program_code = program_code_match.group() if program_code_match else "000"

    # ✅ Detect HEC (Certificate students)
    is_hec = False

    if program.name:
        if "higher education certificate" in program.name.lower():
            is_hec = True

    # 🔥 LOCK rows to prevent duplicates
    last_student = (
        AdmittedStudent.objects
        .select_for_update()
        .order_by('-created_at')
        .first()
    )

    if last_student and last_student.reg_no:
        last_number = int(last_student.reg_no.split('/')[-1])
        next_number = last_number + 1
    else:
        next_number = 1

    formatted_number = str(next_number).zfill(4)

    # ✅ HEC format (with intake month)
    if is_hec:
        intake_month = "APR"  # 🔥 temporary manual value
        return f"{year}/{campus_number}/{program_code}/{intake_month}/{study_mode}/{formatted_number}"

    # ✅ Normal format
    return f"{year}/{campus_number}/{program_code}/{study_mode}/{formatted_number}"