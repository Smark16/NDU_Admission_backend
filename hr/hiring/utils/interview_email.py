from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone


def send_interview_email(interview, application):
    interview_datetime = timezone.localtime(interview.interview_date)
    formatted_date = interview_datetime.strftime("%A, %d %B %Y at %I:%M %p")

    online_section = ""
    if interview.interview_type == "PERSONALITY":
        online_section = (
            "Online Assessment Instructions:\n"
            "--------------------------------\n"
            "This stage will be conducted online.\n"
            "Please click the link below to begin your personality assessment "
            "at the scheduled time:\n\n"
            f"{interview.meeting_link or 'Assessment link will be shared separately'}\n\n"
        )

    send_mail(
        subject="Interview Invitation – Job Application",
        message=(
            f"Dear {application.first_name} {application.last_name},\n\n"
            f"Thank you for your interest in joining our organization.\n\n"
            f"We are pleased to inform you that you have been scheduled for the "
            f"{interview.interview_type} stage of the interview process.\n\n"
            f"Interview Details:\n"
            f"-------------------\n"
            f"Date & Time: {formatted_date}\n"
            f"Duration: {interview.duration_minutes or 'Not specified'} minutes\n"
            f"Location: {interview.location or 'Online / As communicated'}\n\n"
            f"{online_section}"
            f"Additional Information / Notes:\n"
            f"--------------------------------\n"
            f"{interview.feedback}\n\n"
            f"If you have any questions or require clarification, feel free to contact us.\n\n"
            f"We wish you the very best and look forward to your participation.\n\n"
            f"Kind regards,\n"
            f"Recruitment Team\n"
            f"{settings.DEFAULT_FROM_EMAIL}\n\n"
            f"---\n"
            f"This is an automated message. Please do not reply directly to this email."
        ),
        from_email=settings.EMAIL_HOST_USER,
        recipient_list=[application.email],
        fail_silently=False,
    )
