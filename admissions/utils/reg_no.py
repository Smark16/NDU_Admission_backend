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

    # 🔥 LOCK rows to prevent duplicates
    last_student = (
        AdmittedStudent.objects
        .select_for_update()
        .filter(admitted_campus=campus, admitted_program=program)
        .order_by('-id')
        .first()
    )

    if last_student and last_student.reg_no:
        last_number = int(last_student.reg_no.split('/')[-1])
        next_number = last_number + 1
    else:
        next_number = 1

    formatted_number = str(next_number).zfill(4)

    return f"{year}/{campus_number}/{program_code}/{study_mode}/{formatted_number}"