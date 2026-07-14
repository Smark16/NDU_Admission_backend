from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Content, MimeType
from django.conf import settings
from django.utils.html import strip_tags
import logging

logger = logging.getLogger(__name__)


def send_configurable_email(
    to_email: str,
    subject: str,
    body: str,
    is_html: bool = False,
    plain_text_fallback: str | None = None,
) -> bool:
    to_email = (to_email or "").strip()
    if not to_email:
        logger.warning("send_configurable_email: empty recipient")
        return False
    try:
        sg = SendGridAPIClient(api_key=settings.SENDGRID_API_KEY)

        from accounts.portal_branding import get_university_display_name

        from_email = Email("no-reply@ndu.ac.ug", get_university_display_name())

        message = Mail(
            from_email=from_email,
            to_emails=To(to_email),
            subject=subject,
        )

        if is_html:
            message.add_content(Content(MimeType.html, body))
            if plain_text_fallback is None:
                plain_text_fallback = strip_tags(body)
            message.add_content(Content(MimeType.text, plain_text_fallback))
        else:
            message.add_content(Content(MimeType.text, body))

        response = sg.client.mail.send.post(request_body=message.get())
        ok = response.status_code in (200, 202, 204)
        if not ok:
            logger.error(
                "SendGrid non-success for %s: status=%s body=%s",
                to_email,
                response.status_code,
                getattr(response, "body", ""),
            )
        return ok

    except Exception as e:
        logger.exception("SendGrid error sending to %s: %s", to_email, e)
        return False