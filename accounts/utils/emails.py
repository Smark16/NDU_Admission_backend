from ndu_portal.send_grid import send_configurable_email
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.contrib.auth.tokens import default_token_generator
from accounts.portal_branding import (
    DEFAULT_ERP_FRONTEND_URL,
    get_erp_frontend_url,
    get_university_display_name,
)


def _uni() -> str:
    return get_university_display_name()


def _email_template_context(**extra):
    name = _uni()
    ctx = {"university_name": name, "portal_name": name, "system_name": name}
    ctx.update(extra)
    return ctx


def _account_login_link(user, *, use_erp_portal=None) -> str:
    """
    Staff / ERP users → https://erp.ndejje.ndu.ac.ug
    Applicants only → admissions LOGIN_URL.
    """
    if use_erp_portal is None:
        is_applicant_only = bool(getattr(user, "is_applicant", False)) and not bool(
            getattr(user, "is_staff", False)
        )
        use_erp_portal = not is_applicant_only
    if use_erp_portal:
        # Canonical staff ERP (do not use admissions LOGIN_URL).
        return (DEFAULT_ERP_FRONTEND_URL or get_erp_frontend_url()).rstrip("/")
    return (getattr(settings, "LOGIN_URL", "") or "").rstrip("/")


def send_account_email(
    user,
    password,
    subject="Account Created Successfully",
    *,
    use_erp_portal=None,
):
    if use_erp_portal is None:
        is_applicant_only = bool(getattr(user, "is_applicant", False)) and not bool(
            getattr(user, "is_staff", False)
        )
        use_erp_portal = not is_applicant_only

    login_link = _account_login_link(user, use_erp_portal=use_erp_portal)
    portal_label = "ERP portal" if use_erp_portal else "admissions portal"

    body = (
        f"Hello {user.first_name or user.email},\n\n"
        f"Your account has been created successfully.\n\n"
        f"Email: {user.email}\n"
        f"Password: {password}\n\n"
        f"Log in to the {portal_label}:\n{login_link}\n"
    )

    return send_configurable_email(user.email, subject, body)

def send_application_reminder(user, subject=None):
    uni = _uni()
    if subject is None:
        subject = f"Complete Your Application — {uni}"
    login_link = settings.LOGIN_URL
    body = (
        f"Dear {user.first_name or user.email},\n\n"
        f"We noticed that you created an account on the {uni} admissions portal "
        f"but have not yet submitted your application.\n\n"
        f"The admission window is still open. Log in now to complete and submit your application:\n"
        f"{login_link}\n\n"
        f"If you need any assistance, please contact the admissions office.\n\n"
        f"Best regards,\n"
        f"{uni} Admissions Team"
    )
    return send_configurable_email(user.email, subject, body)

def send_reset_password_link(user, subject="Password Reset Request"):
    uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    reset_url = f"{settings.BACKEND_URL}/api/accounts/reset_password/{uidb64}/{token}/"
    html_body = render_to_string('password_reset_email.html', _email_template_context(
        user=user,
        reset_url=reset_url,
    ))
    success = send_configurable_email(
        to_email=user.email,
        subject=subject,
        body=html_body,
        is_html=True,                 
    )

    return success

def send_horizon_reset_password_link(user, subject="Password Reset Request"):
    uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    reset_url = f"{settings.BACKEND_URL}/api/accounts/horizon_reset_password/{uidb64}/{token}/"
    html_body = render_to_string('erp_password_reset.html', _email_template_context(
        user=user,
        reset_url=reset_url,
    ))
    success = send_configurable_email(
        to_email=user.email,
        subject=subject,
        body=html_body,
        is_html=True,                 
    )

    return success