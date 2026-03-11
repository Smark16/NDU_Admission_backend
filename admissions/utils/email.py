from django.core.mail import send_mail
from django.conf import settings

def send_admission_update(admission):
    send_mail(
        subject="Admission updated Successfully",
        message=(
            f"Dear {admission.application.first_name} {admission.application.last_name},\n\n"
            f"Your Admission has be updated.\n\n"
            f"Student Number: {admission.student_id}. \n\n"
            f"Registration Number: {admission.reg_no}.\n\n"
            f"Program: {admission.admitted_program.name}:\n\n"
            f"Campus: {admission.admitted_campus.name}\n\n"
            f"If you did not expect this email, please ignore it."
        ),
        from_email=settings.EMAIL_HOST_USER,
        recipient_list=[admission.application.email],
        fail_silently=False,
    )
