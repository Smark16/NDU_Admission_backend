"""Provision / link Zimbra university emails for admitted students."""
from __future__ import annotations

import logging
import re

from admissions.models import AdmittedStudent, PortalNotification
from ndu_portal.send_grid import send_configurable_email

from . import zimbra_client
from .models import ZimbraIntegrationConfig

logger = logging.getLogger(__name__)


def slugify_local(text: str) -> str:
    text = re.sub(r"[^a-zA-Z\s'-]", "", text or "").strip().lower()
    text = re.sub(r"\s+", ".", text)
    return text or "student"


def dl_slug(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "").strip().lower())
    return re.sub(r"-+", "-", text).strip("-") or "unknown"


def student_display_name(student: AdmittedStudent) -> str:
    user = student.student_user
    if user:
        name = f"{(user.first_name or '').strip()} {(user.last_name or '').strip()}".strip()
        if name:
            return name
    app = student.application
    if app:
        full = (getattr(app, "full_name", None) or "").strip()
        if full:
            return full
        return f"{(app.first_name or '').strip()} {(app.last_name or '').strip()}".strip() or student.reg_no
    return student.reg_no


def suggest_university_email(student: AdmittedStudent, domain: str) -> str:
    """Build first.last@domain; append trailing reg digits on collision in DB."""
    name = student_display_name(student)
    parts = name.split()
    first = parts[0] if parts else "student"
    last = parts[-1] if len(parts) > 1 else "ndu"
    local = f"{slugify_local(first)}.{slugify_local(last)}"
    email = f"{local}@{domain}".lower()

    conflict = (
        AdmittedStudent.objects.filter(university_email__iexact=email)
        .exclude(pk=student.pk)
        .exists()
    )
    if conflict:
        digits = re.sub(r"[^0-9]", "", student.reg_no or "")[-3:] or "x"
        email = f"{local}{digits}@{domain}".lower()
    return email


def batch_dl_email(student: AdmittedStudent, domain: str) -> str | None:
    batch = student.intended_program_batch or None
    batch_code = ""
    if batch is not None:
        batch_code = (getattr(batch, "name", None) or getattr(batch, "code", None) or "").strip()
    if not batch_code and student.admitted_batch_id:
        batch_code = (getattr(student.admitted_batch, "name", None) or "").strip()
    program = student.admitted_program
    program_name = (getattr(program, "name", None) or "").strip() if program else ""
    if not batch_code or not program_name:
        return None
    return f"batch-{dl_slug(batch_code)}-{dl_slug(program_name)}@{domain}"


def personal_email(student: AdmittedStudent) -> str:
    user = student.student_user
    if user and (user.email or "").strip():
        return user.email.strip()
    if student.application_id and (student.application.email or "").strip():
        return student.application.email.strip()
    return ""


def _notify_student(
    student: AdmittedStudent,
    *,
    channel: str,
    title: str,
    message: str,
) -> dict:
    from admissions.student_notify_views import _personalise_student

    channel = (channel or "both").strip().lower()
    if channel not in ("portal", "email", "both"):
        channel = "both"
    ttl = _personalise_student(title, student)[:200]
    msg = _personalise_student(message, student)
    email = personal_email(student)
    portal_created = 0
    emailed = 0
    email_failed = 0
    skipped_no_email = 0

    if channel in ("portal", "both") and student.student_user_id:
        PortalNotification.objects.create(
            recipient=student.student_user,
            title=ttl,
            message=msg,
        )
        portal_created = 1

    if channel in ("email", "both"):
        if not email:
            skipped_no_email = 1
        elif send_configurable_email(email, ttl, msg):
            emailed = 1
        else:
            email_failed = 1

    return {
        "portal_created": portal_created,
        "emailed": emailed,
        "email_failed": email_failed,
        "skipped_no_email": skipped_no_email,
        "personal_email": email or None,
    }


def _guide_url() -> str:
    from accounts.portal_branding import get_erp_frontend_url

    return f"{get_erp_frontend_url()}/guides/student-email-eduroam-guide.html"


DEFAULT_NOTIFY_TITLE = "Your Ndejje University email is ready"
DEFAULT_NOTIFY_MESSAGE = (
    "Dear {first_name},\n\n"
    "Your university email account is ready.\n\n"
    "Email: {university_email}\n"
    "Temporary password: NduStudent#2026\n"
    "Webmail: https://ndejjemail.ndu.ac.ug\n\n"
    "1) Log in and change the password when prompted.\n"
    "2) Install geteduroam from the Google Play Store.\n"
    "3) Search \"renu\" and choose RENU Managed IdP (not RENU - GT Tests).\n"
    "4) Log in with your university email and your new password.\n\n"
    "Full step-by-step guide with screenshots: {guide_url}\n\n"
    "Reg no: {reg_no}\n"
)


def import_university_email_mapping(rows: list[dict]) -> dict:
    """Save university_email on admissions from [{reg_no, university_email}, ...]."""
    updated = 0
    missing = 0
    skipped = 0
    errors: list[str] = []

    for raw in rows:
        reg_no = (raw.get("reg_no") or "").strip()
        uni = (raw.get("university_email") or "").strip().lower()
        if not reg_no or not uni:
            skipped += 1
            continue
        student = AdmittedStudent.objects.filter(reg_no__iexact=reg_no).first()
        if not student:
            missing += 1
            errors.append(f"No admission for reg_no={reg_no}")
            continue
        clash = (
            AdmittedStudent.objects.filter(university_email__iexact=uni)
            .exclude(pk=student.pk)
            .first()
        )
        if clash:
            skipped += 1
            errors.append(f"{uni} already on {clash.reg_no}")
            continue
        student.university_email = uni
        student.save(update_fields=["university_email", "updated_at"])
        updated += 1

    return {
        "updated": updated,
        "missing": missing,
        "skipped": skipped,
        "errors": errors[:50],
        "error_count": len(errors),
    }


def provision_student(
    student: AdmittedStudent,
    *,
    notify: bool = False,
    channel: str = "both",
    title: str | None = None,
    message: str | None = None,
) -> dict:
    """
    Create Zimbra mailbox if missing, or link existing; save university_email.
    Optionally send portal + personal-email notification.
    """
    cfg = zimbra_client.require_enabled_config()
    domain = (cfg.domain or "educ.ndu.ac.ug").strip().lower()
    password = (cfg.default_password or "NduStudent#2026").strip()
    display = student_display_name(student)

    email = (student.university_email or "").strip().lower()
    if not email:
        email = suggest_university_email(student, domain)

    token = zimbra_client.authenticate(cfg)
    existing = zimbra_client.get_account(email, auth_token=token, cfg=cfg)
    created = False
    linked_existing = False

    if existing:
        linked_existing = True
    else:
        # If suggested address taken on Zimbra but not in our DB, append digits.
        try:
            zimbra_client.create_account(
                email,
                password,
                display_name=display,
                auth_token=token,
                cfg=cfg,
            )
            created = True
        except zimbra_client.ZimbraRequestError as exc:
            code = (exc.code or "").upper()
            msg = str(exc).lower()
            if "ACCOUNT_EXISTS" in code or "already exists" in msg:
                linked_existing = True
            else:
                # Retry once with reg digits
                digits = re.sub(r"[^0-9]", "", student.reg_no or "")[-3:] or "x"
                local = email.split("@", 1)[0]
                if not local.endswith(digits):
                    email = f"{local}{digits}@{domain}"
                    existing2 = zimbra_client.get_account(email, auth_token=token, cfg=cfg)
                    if existing2:
                        linked_existing = True
                    else:
                        zimbra_client.create_account(
                            email,
                            password,
                            display_name=display,
                            auth_token=token,
                            cfg=cfg,
                        )
                        created = True
                else:
                    raise

    dl = batch_dl_email(student, domain)
    dl_added = False
    dl_error = None
    if dl:
        try:
            zimbra_client.add_distribution_list_member(
                dl, email, auth_token=token, cfg=cfg
            )
            dl_added = True
        except zimbra_client.ZimbraRequestError as exc:
            dl_error = str(exc)[:300]
            logger.warning("Could not add %s to DL %s: %s", email, dl, dl_error)

    student.university_email = email
    student.save(update_fields=["university_email", "updated_at"])

    notify_result = None
    if notify:
        notify_result = _notify_student(
            student,
            channel=channel,
            title=title or DEFAULT_NOTIFY_TITLE,
            message=message or DEFAULT_NOTIFY_MESSAGE,
        )

    return {
        "reg_no": student.reg_no,
        "university_email": email,
        "created": created,
        "linked_existing": linked_existing,
        "display_name": display,
        "distribution_list": dl,
        "dl_added": dl_added,
        "dl_error": dl_error,
        "notify": notify_result,
    }


def resolve_student(*, reg_no: str | None = None, admission_id: int | None = None) -> AdmittedStudent:
    qs = AdmittedStudent.objects.select_related(
        "student_user",
        "application",
        "admitted_program",
        "admitted_batch",
        "intended_program_batch",
    )
    if admission_id is not None:
        student = qs.filter(pk=admission_id).first()
        if not student:
            raise ValueError("Admission not found.")
        return student
    if reg_no:
        student = qs.filter(reg_no__iexact=reg_no.strip()).first()
        if not student:
            raise ValueError("No admitted student with that reg_no.")
        return student
    raise ValueError("Provide reg_no or admission_id.")
