import re
from typing import Dict, Tuple

from django.utils.html import strip_tags

from admissions.models import EmailTemplate

_BRANDING_PLACEHOLDERS = ["university_name", "portal_name", "system_name"]

EMAIL_TEMPLATE_DEFINITIONS: Dict[str, Dict[str, object]] = {
    EmailTemplate.KEY_APPLICATION_SUBMITTED: {
        "name": "Application Submitted",
        "description": "Sent immediately after a successful application submission.",
        "subject_template": "Application Submitted Successfully!",
        "body_template_html": (
            "Dear {{full_name}},<br/><br/>"
            "Your application has been successfully submitted to {{university_name}}.<br/>"
            "Application ID: {{application_id}}<br/>"
            "Submitted on: {{submitted_date}}<br/><br/>"
            "Thank you,<br/>{{university_name}} Admissions Team"
        ),
        "placeholders": [
            *_BRANDING_PLACEHOLDERS,
            "first_name",
            "last_name",
            "full_name",
            "application_id",
            "submitted_date",
        ],
    },
    EmailTemplate.KEY_ADMISSION_ACCEPTED: {
        "name": "Admission Accepted",
        "description": "Sent when a student is admitted.",
        "subject_template": "Congratulations! You have been admitted to {{university_name}}",
        "body_template_html": (
            "Dear {{full_name}},<br/><br/>"
            "<strong>CONGRATULATIONS!</strong><br/><br/>"
            "We are delighted to inform you that your application has been successfully reviewed and ACCEPTED.<br/><br/>"
            "You have been offered admission to study:<br/>"
            "- Program: {{program}}<br/>"
            "- Campus: {{campus}}<br/>"
            "- Study Mode: {{study_mode}}<br/>"
            "- Batch: {{batch_name}} ({{academic_year}})<br/><br/>"
            "Your provisional admission letter will be sent shortly.<br/><br/>"
            "We look forward to welcoming you!<br/><br/>"
            "Admissions Office<br/>{{university_name}}"
        ),
        "placeholders": [
            *_BRANDING_PLACEHOLDERS,
            "first_name",
            "last_name",
            "full_name",
            "program",
            "campus",
            "study_mode",
            "batch_name",
            "academic_year",
        ],
    },
    EmailTemplate.KEY_ADMISSION_UPDATED: {
        "name": "Admission Updated",
        "description": "Sent when an admitted student record is updated.",
        "subject_template": "Admission updated Successfully",
        "body_template_html": (
            "Dear {{full_name}},<br/><br/>"
            "Your admission has been updated.<br/><br/>"
            "Student Number: {{student_id}}<br/>"
            "Registration Number: {{reg_no}}<br/>"
            "Program: {{program}}<br/>"
            "Campus: {{campus}}<br/><br/>"
            "If you did not expect this email, please ignore it."
        ),
        "placeholders": [
            *_BRANDING_PLACEHOLDERS,
            "first_name",
            "last_name",
            "full_name",
            "student_id",
            "reg_no",
            "program",
            "campus",
        ],
    },
    EmailTemplate.KEY_OFFER_LETTER_SENT: {
        "name": "Offer Letter Sent",
        "description": "Sent when an offer/admission letter is made available in portal.",
        "subject_template": "Admission letter sent successfully",
        "body_template_html": (
            "Dear {{full_name_upper}},<br/><br/>"
            "<strong>CONGRATULATIONS!</strong><br/><br/>"
            "We are delighted to inform you that your admission letter has been successfully sent to your portal.<br/><br/>"
            "Next Steps:<br/>"
            "1. Log in to {{portal_name}} to download your official admission letter<br/>"
            "2. Confirm everything is ok and sign where necessary<br/>"
            "3. Complete registration before the deadline<br/><br/>"
            "We look forward to welcoming you!<br/><br/>"
            "Warm regards,<br/>Admissions Office<br/>{{university_name}}<br/>"
            "Email: admissions@ndejjeuniversity.ac.ug<br/>"
            "Website: www.ndejjeuniversity.ac.ug"
        ),
        "placeholders": [
            *_BRANDING_PLACEHOLDERS,
            "first_name",
            "last_name",
            "full_name",
            "full_name_upper",
            "portal_url",
        ],
    },
    EmailTemplate.KEY_WEEKLY_ADMISSIONS_DIGEST: {
        "name": "Weekly Admissions Digest",
        "description": "Project-health style summary emailed weekly to configured staff recipients.",
        "subject_template": "{{portal_name}} — Weekly Admissions Report ({{week_start}} to {{week_end}})",
        "body_template_html": (
            "<p>Hello,</p>"
            "<p>Here is your <strong>weekly admissions health report</strong> from "
            "<strong>{{portal_name}}</strong> for <strong>{{week_start}}</strong> to "
            "<strong>{{week_end}}</strong>.</p>"
            "<table cellpadding=\"8\" cellspacing=\"0\" border=\"1\" "
            "style=\"border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px;\">"
            "<tr style=\"background:#000080;color:#fff;\"><th align=\"left\">Metric</th><th align=\"right\">This week</th></tr>"
            "<tr><td>Applications received</td><td align=\"right\"><strong>{{applications_received}}</strong> ({{applications_received_delta}} vs prior week)</td></tr>"
            "<tr><td>Submitted</td><td align=\"right\">{{submitted}}</td></tr>"
            "<tr><td>Under review</td><td align=\"right\">{{under_review}}</td></tr>"
            "<tr><td>Admitted / accepted</td><td align=\"right\">{{admitted}}</td></tr>"
            "<tr><td>Rejected</td><td align=\"right\">{{rejected}}</td></tr>"
            "<tr><td>Direct entry</td><td align=\"right\">{{direct_entry}}</td></tr>"
            "<tr><td>Online</td><td align=\"right\">{{online}}</td></tr>"
            "</table>"
            "<p style=\"margin-top:16px;\"><strong>All-time pipeline (non-draft)</strong></p>"
            "<ul>"
            "<li>Total applications: {{total_pipeline}}</li>"
            "<li>Pending / in review: {{total_pending}}</li>"
            "<li>Admitted / accepted: {{total_admitted}}</li>"
            "<li>Rejected: {{total_rejected}}</li>"
            "</ul>"
            "<p><a href=\"{{report_url}}\">Open All Applicants report in {{portal_name}}</a></p>"
            "<p style=\"color:#666;font-size:12px;\">Generated {{generated_at}}</p>"
        ),
        "placeholders": [
            *_BRANDING_PLACEHOLDERS,
            "week_start",
            "week_end",
            "applications_received",
            "applications_received_delta",
            "submitted",
            "under_review",
            "admitted",
            "rejected",
            "direct_entry",
            "online",
            "total_pipeline",
            "total_pending",
            "total_admitted",
            "total_rejected",
            "report_url",
            "generated_at",
        ],
    },
}

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def get_template_definition(key: str) -> Dict[str, object]:
    return EMAIL_TEMPLATE_DEFINITIONS.get(key, {})


def render_template_string(template: str, context: Dict[str, object]) -> str:
    def _replace(match: re.Match) -> str:
        field = match.group(1)
        value = context.get(field, "")
        return str(value if value is not None else "")

    return _PLACEHOLDER_RE.sub(_replace, template or "")


def _merge_email_context(context: Dict[str, object] | None) -> Dict[str, object]:
    from accounts.portal_branding import email_branding_context

    merged = email_branding_context()
    if context:
        merged.update(context)
    return merged


def render_email_template(key: str, context: Dict[str, object]) -> Tuple[str, str, str]:
    merged = _merge_email_context(context)
    definition = get_template_definition(key)
    default_subject = str(definition.get("subject_template", ""))
    default_body = str(definition.get("body_template_html", ""))

    template = EmailTemplate.objects.filter(key=key, is_active=True).first()
    subject_template = template.subject_template if template else default_subject
    body_template = template.body_template_html if template else default_body

    subject = render_template_string(subject_template, merged).strip() or default_subject
    html_body = render_template_string(body_template, merged).strip() or default_body
    plain_text = strip_tags(html_body)
    return subject, html_body, plain_text
