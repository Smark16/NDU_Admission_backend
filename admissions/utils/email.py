from ndu_portal.send_grid import send_configurable_email

def send_application_email(application, subject="Application Submitted Successfully!"):
    body = (
        f"Dear {application.first_name} {application.last_name},\n\n"
        f"Your application has been successfully submitted to Ndejje University.\n"
        f"Application ID: {application.id}\n"
        f"Submitted on: {application.created_at.strftime('%d %B %Y')}\n\n"
        f"Thank you,\nNdejje University Admissions Team"
    )

    return send_configurable_email(application.email, subject, body)

def send_admission_email(application, admission,
                         subject="Congratulations! You have been admitted to Ndejje University"):
    body = (
        f"Dear {application.first_name} {application.last_name},\n\n"
        f"CONGRATULATIONS!\n\n"
        f"We are delighted to inform you that your application has been successfully reviewed and ACCEPTED.\n\n"
        f"You have been offered admission to study:\n"
        f"• Program: {admission.admitted_program.name}\n"
        f"• Campus: {admission.admitted_campus.name}\n"
        f"• Study Mode: {admission.study_mode}\n"
        f"• Batch: {admission.admitted_batch.name} ({admission.admitted_batch.academic_year})\n\n"
        f"Your provisional admission letter will be sent shortly.\n\n"
        f"We look forward to welcoming you!\n\n"
        f"Admissions Office\nNdejje University"
    )

    return send_configurable_email(application.email, subject, body)

def send_admission_update(admission, subject="Admission updated Successfully"):
    body = (
            f"Dear {admission.application.first_name} {admission.application.last_name},\n\n"
            f"Your Admission has be updated.\n\n"
            f"Student Number: {admission.student_id}. \n\n"
            f"Registration Number: {admission.reg_no}.\n\n"
            f"Program: {admission.admitted_program.name}:\n\n"
            f"Campus: {admission.admitted_campus.name}\n\n"
            f"If you did not expect this email, please ignore it."
        )
    return send_configurable_email(admission.application.email, subject, body)