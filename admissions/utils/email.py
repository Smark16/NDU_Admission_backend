from ndu_portal.send_grid import send_configurable_email
from django.conf import settings
from django.template.loader import render_to_string

def send_application_email(application, subject="Application Submitted Successfully!"):
    body = (
        f"Dear {application.first_name} {application.last_name},\n\n"
        f"Your application has been successfully submitted to Ndejje University.\n"
        f"Application ID: {application.id}\n"
        f"Submitted on: {application.created_at.strftime('%d %B %Y')}\n\n"
        f"Please note that all subsequent communication regarding your application, "
        f"including updates, admission decisions, and further instructions, will be sent "
        f"to your email address. You are therefore not required to come to the university "
        f"campus physically unless officially advised otherwise.\n\n"
        f"Kindly keep checking your email regularly for updates from the Admissions Office.\n\n"
        f"Thank you for choosing Ndejje University.\n\n"
        f"Admissions Team\n"
        f"Ndejje University"
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

THESE ARE THE PAYMENT GUIDE LINES
 => FOR MTN MOBILE MONEY
   1. Dial *165#
   2.Go to payments(4)
   3.select school fees(3)
   4.select school pay(2)
   5.select pay fees(1)
   Enter student No
   Verify your student details
   Enter amount to pay
   Confim with MTN mobile money pin

 => FOR AIRTEL MONEY
    1.Dial *185#
    2.Go to school fees (6)
    3.select school pay(2)
    4.select pay fees (1)
    Enter student No
    Enter amount to pay
    Verify your student details
    Confim with Airtel mobile money pin

ii) NOTE: This amount shall be credited towards your tuition fees.

iii) Sending the Bank Deposit Slip and payment confirmation receipt to:
confirmation@ndu.ac.ug

iv)NOTE: PLEASE LOG IN TO YOUR HORIZON PORTAL TO DOWNLOAD AND PRINT YOUR ADMISSION LETTER THERE WILL BE NO NEED TO COME PYHSICALLY FOR THE LETTER.

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