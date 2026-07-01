import logging

from accounts.models import User

logger = logging.getLogger(__name__)

DEFAULT_STUDENT_PASSWORD = "NDU@1234"


def student_portal_username(reg_no: str) -> str:
    """Portal login username derived from registration number (slashes → underscores)."""
    return str(reg_no).strip().replace("/", "_")


def initial_student_password(reg_no: str) -> str:
    """Default first-time portal password (same value emailed to students)."""
    _ = reg_no  # kept for API compatibility; password is not derived from reg_no
    return DEFAULT_STUDENT_PASSWORD


def student_has_post_admission_portal_access(admission) -> bool:
    """
    True when the linked portal user signed in on or after admission.

    Applicant-portal logins before admission do not count as student ERP access.
    """
    user = getattr(admission, "student_user", None)
    if user is None or user.last_login is None:
        return False
    admission_dt = admission.admission_date
    if admission_dt is None:
        # Without an admission timestamp we cannot infer ERP access from last_login alone.
        return False
    last_login = user.last_login
    if last_login.tzinfo is None and admission_dt.tzinfo is not None:
        from django.utils import timezone as tz

        last_login = tz.make_aware(last_login, admission_dt.tzinfo)
    elif last_login.tzinfo is not None and admission_dt.tzinfo is None:
        from django.utils import timezone as tz

        admission_dt = tz.make_aware(admission_dt, last_login.tzinfo)
    return last_login >= admission_dt


def needs_student_portal_password_reset(admission) -> bool:
    """
    Whether an admitted student should receive NDU@1234 via bulk reset.

    Skips students who already signed in to the ERP portal on or after admission.
    Applicant-portal logins before admission do not count.
    """
    if getattr(admission, "student_user", None) is None:
        return True
    return not student_has_post_admission_portal_access(admission)


def ensure_student_portal_account(admission, *, reset_password: bool = False) -> tuple[User | None, bool]:
    """
    Create or link the ERP student login for an admitted student.

    Returns (user, created) where created is True when a new User row was created.
    Idempotent — safe to call from admission views and Celery.
    """
    application = admission.application
    applicant = application.applicant
    username = student_portal_username(admission.reg_no)
    if not username:
        logger.warning("Student account skipped for admission %s: missing reg_no", admission.pk)
        return None, False

    student_user = getattr(admission, "student_user", None)
    if student_user is None:
        student_user = User.objects.filter(username__iexact=username).first()

    was_applicant_account = bool(
        student_user is not None
        and student_user.pk == application.applicant_id
        and student_user.is_applicant
    )
    first_portal_link = not admission.student_user_id

    created = False
    if student_user is None:
        student_user = User.objects.create_user(
            username=username,
            first_name=applicant.first_name or "",
            last_name=applicant.last_name or "",
            email=applicant.email or "",
            password=initial_student_password(admission.reg_no),
            is_staff=False,
            is_applicant=False,
            is_student=True,
            must_change_password=True,
        )
        created = True
    else:
        updates: list[str] = []
        canonical_username = student_portal_username(admission.reg_no)
        if canonical_username and student_user.username != canonical_username:
            conflict = (
                User.objects.filter(username__iexact=canonical_username)
                .exclude(pk=student_user.pk)
                .exists()
            )
            if not conflict:
                student_user.username = canonical_username
                updates.append("username")
        if not student_user.is_student:
            student_user.is_student = True
            updates.append("is_student")
        if student_user.is_applicant:
            student_user.is_applicant = False
            updates.append("is_applicant")
        if student_user.is_staff:
            student_user.is_staff = False
            updates.append("is_staff")
        if not student_user.email and applicant.email:
            student_user.email = applicant.email
            updates.append("email")
        if not student_user.first_name and applicant.first_name:
            student_user.first_name = applicant.first_name
            updates.append("first_name")
        if not student_user.last_name and applicant.last_name:
            student_user.last_name = applicant.last_name
            updates.append("last_name")
        if updates:
            student_user.save(update_fields=updates)

    if created or reset_password or was_applicant_account or first_portal_link:
        student_user.set_password(initial_student_password(admission.reg_no))
        student_user.must_change_password = True
        student_user.save(update_fields=["password", "must_change_password"])

    if admission.student_user_id != student_user.pk:
        admission.student_user = student_user
        admission.save(update_fields=["student_user", "updated_at"])

    return student_user, created
