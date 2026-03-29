from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Content, MimeType
from django.conf import settings
from django.utils.html import strip_tags  

def send_configurable_email(
    to_email: str,
    subject: str,
    body: str,
    is_html: bool = False,
    plain_text_fallback: str | None = None,
) -> bool:
    try:
        sg = SendGridAPIClient(api_key=settings.SENDGRID_API_KEY)

        from_email = Email('no-reply@ndu.ac.ug', "NDU Admissions Portal")

        message = Mail(
            from_email=from_email,
            to_emails=To(to_email),
            subject=subject,
        )

        if is_html:
            # HTML version
            message.add_content(Content(MimeType.html, body))

            # Generate plain-text fallback automatically if not provided
            if plain_text_fallback is None:
                plain_text_fallback = strip_tags(body)  # removes HTML tags
            message.add_content(Content(MimeType.text, plain_text_fallback))
        else:
            # Plain text only (your original behavior)
            message.add_content(Content(MimeType.text, body))

        response = sg.client.mail.send.post(request_body=message.get())
        return response.status_code in (200, 202, 204)

    except Exception as e:
        print(f"SendGrid error: {e}")
        return False

# def send_configurable_email(to_email: str, subject: str, body: str):
#     try:  
#         sg = SendGridAPIClient(api_key=settings.SENDGRID_API_KEY)

#         from_email = Email('no-reply@ndu.ac.ug')
#         to = To(to_email)  
#         subject=subject
#         content = Content("text/plain", body)  
#         message = Mail(from_email, to, subject, content)

#         response = sg.client.mail.send.post(request_body=message.get())

#         return response.status_code in (200, 202)

#     except Exception as e:
#         print(f"SendGrid error: {e}")
#         return False