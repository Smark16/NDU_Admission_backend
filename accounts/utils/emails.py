from ndu_portal.send_grid import send_configurable_email
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.contrib.auth.tokens import default_token_generator

def send_account_email(user, password, subject="Account Created Successfully"):
    login_link = settings.LOGIN_URL

    body = (
        f"Hello {user.first_name or user.email},\n\n"
        f"Your account has been created successfully.\n\n"
        f"Email: {user.email}\n"
        f"Password: {password}\n\n"
        f"Use this link to login: {login_link}\n"
    )

    return send_configurable_email(user.email, subject, body)

def send_reset_password_link(user, subject="Password Reset Request"):
    uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    reset_url = f"{settings.BACKEND_URL}/api/accounts/reset_password/{uidb64}/{token}/"
    html_body = render_to_string('password_reset_email.html', {
        'user': user,
        'reset_url': reset_url,
    })
    success = send_configurable_email(
        to_email=user.email,
        subject=subject,
        body=html_body,
        is_html=True,                 
    )

    return success
