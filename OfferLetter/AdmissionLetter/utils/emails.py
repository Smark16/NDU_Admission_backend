from ndu_portal.send_grid import send_configurable_email
from admissions.email_templates import render_email_template

def offerletter_email(applicant_local, subject = "Admission letter sent successfully" ):
    full_name = f"{applicant_local.first_name or ''} {applicant_local.last_name or ''}".strip()
    context = {
        "first_name": applicant_local.first_name or "",
        "last_name": applicant_local.last_name or "",
        "full_name": full_name,
        "full_name_upper": full_name.upper(),
    }
    resolved_subject, html_body, plain_body = render_email_template("offer_letter_sent", context)
    return send_configurable_email(
        applicant_local.email,
        resolved_subject or subject,
        html_body,
        is_html=True,
        plain_text_fallback=plain_body,
    )