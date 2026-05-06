from admissions.email_templates import render_email_template
from ndu_portal.send_grid import send_configurable_email


def _name_context(first_name, last_name):
    full_name = f"{first_name or ''} {last_name or ''}".strip()
    return {
        "first_name": first_name or "",
        "last_name": last_name or "",
        "full_name": full_name,
        "full_name_upper": full_name.upper(),
    }


def send_application_email(application, subject="Application Submitted Successfully!"):
    context = {
        **_name_context(application.first_name, application.last_name),
        "application_id": application.id,
        "submitted_date": application.created_at.strftime("%d %B %Y"),
    }
    resolved_subject, html_body, plain_body = render_email_template("application_submitted", context)
    return send_configurable_email(
        application.email,
        resolved_subject or subject,
        html_body,
        is_html=True,
        plain_text_fallback=plain_body,
    )


def send_admission_email(application, admission, subject="Congratulations! You have been admitted to Ndejje University"):
    context = {
        **_name_context(application.first_name, application.last_name),
        "program": admission.admitted_program.name if admission.admitted_program_id else "",
        "campus": admission.admitted_campus.name if admission.admitted_campus_id else "",
        "study_mode": admission.study_mode or "",
        "batch_name": admission.admitted_batch.name if admission.admitted_batch_id else "",
        "academic_year": admission.admitted_batch.academic_year if admission.admitted_batch_id else "",
    }
    resolved_subject, html_body, plain_body = render_email_template("admission_accepted", context)
    return send_configurable_email(
        application.email,
        resolved_subject or subject,
        html_body,
        is_html=True,
        plain_text_fallback=plain_body,
    )


def send_admission_update(admission, subject="Admission updated Successfully"):
    context = {
        **_name_context(admission.application.first_name, admission.application.last_name),
        "student_id": admission.student_id or "",
        "reg_no": admission.reg_no or "",
        "program": admission.admitted_program.name if admission.admitted_program_id else "",
        "campus": admission.admitted_campus.name if admission.admitted_campus_id else "",
    }
    resolved_subject, html_body, plain_body = render_email_template("admission_updated", context)
    return send_configurable_email(
        admission.application.email,
        resolved_subject or subject,
        html_body,
        is_html=True,
        plain_text_fallback=plain_body,
    )