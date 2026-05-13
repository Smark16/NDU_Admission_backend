from ndu_portal.send_grid import send_configurable_email
from django.conf import settings
from django.template.loader import render_to_string

def send_application_email(application, subject="Application Submitted Successfully!"):
    body = (
        f"Dear {application.first_name} {application.last_name},\n\n"
        f"Your application has been successfully submitted to Ndejje University.\n"
        f"Application ID: {application.id}\n"
        f"Submitted on: {application.created_at.strftime('%d %B %Y')}\n\n"
        f"Thank you,\nNdejje University Admissions Team"
    )

    return send_configurable_email(application.email, subject, body)

# admission email
def send_admission_email(
    application,
    admission,
    subject="Congratulations! You have been admitted to Ndejje University"
):
    confirmation_fee = "UGX 150,000"

    body = f"""
Dear {application.first_name} {application.last_name},

CONGRATULATIONS

On behalf of the Admissions Board, we are pleased to inform you that you have been provisionally admitted to Ndejje University to pursue the academic programme indicated below:

Programme of Study: {admission.admitted_program.name}

Registration Number: {admission.reg_no}

Payment Code: {admission.student_id}

Duration of Programme: {getattr(admission.admitted_program, 'duration', 'As per programme structure')}

ADMISSION CONFIRMATION

You are required to confirm your acceptance of this admission by:

i) Paying a non-refundable fee of {confirmation_fee} using your School Pay Code {admission.student_id} not later than the stipulated deadline.

ii) NOTE: This amount shall be credited towards your tuition fees.

iii) Sending the Bank Deposit Slip and payment confirmation receipt to:
confirmation@ndu.ac.ug

iv) Pick your admission letter from any of our campuses or receive it through your portal.

COMMUNICATION

Kindly join the official WhatsApp group using the link below for proper communication and updates:

https://chat.whatsapp.com/LZI1mItko834t6c1Vjwy9b

Congratulations on your admission to Ndejje University! We hope you find your studies both enjoyable and fulfilling.

We look forward to receiving you.

Admissions Office
Ndejje University
"""

    return send_configurable_email(
        to_email=application.email,
        subject=subject,
        body=body
    )

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

def send_student_login_credentials(user, password, subject="Account Created Successfully"):
    login_url = f"{settings.ERP_FRONTEND_URL}"
    html_body = render_to_string('student_login.html', {
        'user': user,
        'login_url': login_url,
        'password': password
    })
    success = send_configurable_email(
        to_email=user.email,
        subject=subject,
        body=html_body,
        is_html=True,                 
    )

    return success

# rejection email
def send_rejection_email(application, msg, subject="Application Update: Admission Decision"):
    body = (
        f"Dear {application.first_name} {application.last_name},\n\n"
        f"We regret to inform you that your application for admission to Ndejje University has been unsuccessful.\n\n"
        f"Application ID: {application.id}\n"
        f"Submitted on: {application.created_at.strftime('%d %B %Y')}\n\n"
        f"Reason for Rejection: {msg}\n\n"
        f"We encourage you to apply again in the future and wish you the best in your academic pursuits.\n\n"
        f"Thank you for considering Ndejje University.\n"
        f"Admissions Team"
    )

    return send_configurable_email(application.email, subject, body)