from admissions.email_templates import render_email_template
from admissions.models import AdmittedStudent
from admissions.student_accounts import DEFAULT_STUDENT_PASSWORD
from ndu_portal.send_grid import send_configurable_email


def build_offer_letter_email_context(application) -> dict:
    """Context for the offer_letter_sent configurable email template."""
    full_name = f"{application.first_name or ''} {application.last_name or ''}".strip()
    admission = (
        AdmittedStudent.objects.filter(application=application, is_admitted=True)
        .select_related("admitted_program")
        .first()
    )

    reg_no = (admission.reg_no or "").strip() if admission else ""
    program = ""
    student_id = ""
    if admission:
        student_id = (admission.student_id or "").strip()
        if admission.admitted_program_id:
            program = admission.admitted_program.name

    return {
        "first_name": application.first_name or "",
        "last_name": application.last_name or "",
        "full_name": full_name,
        "full_name_upper": full_name.upper(),
        "default_password": DEFAULT_STUDENT_PASSWORD,
        "reg_no": reg_no or "Contact admissions for your registration number",
        "student_id": student_id or "—",
        "program": program or "—",
    }


def offerletter_email(applicant_local, subject="Your admission letter is ready"):
    context = build_offer_letter_email_context(applicant_local)
    resolved_subject, html_body, plain_body = render_email_template("offer_letter_sent", context)
    return send_configurable_email(
        applicant_local.email,
        resolved_subject or subject,
        html_body,
        is_html=True,
        plain_text_fallback=plain_body,
    )
