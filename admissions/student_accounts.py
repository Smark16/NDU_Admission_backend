import logging

from accounts.models import User

logger = logging.getLogger(__name__)

DEFAULT_STUDENT_PASSWORD = "NDU@1234"


def student_portal_username(reg_no: str) -> str:
    return str(reg_no).strip().replace("/", "_")


def initial_student_password(reg_no: str) -> str:
    cleaned = str(reg_no).strip()
    return cleaned or DEFAULT_STUDENT_PASSWORD


def ensure_student_portal_account(admission, *, reset_password: bool = False) -> User | None:
    """Create or link the ERP student login for an admitted student."""
    application = admission.application
    applicant = application.applicant
    username = student_portal_username(admission.reg_no)
    if not username:
        logger.warning("Student account skipped for admission %s: missing reg_no", admission.pk)
        return None

    student_user = getattr(admission, "student_user", None)
    if student_user is None:
        student_user = User.objects.filter(username__iexact=username).first()

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

    if created or reset_password:
        student_user.set_password(initial_student_password(admission.reg_no))
        student_user.must_change_password = True
        student_user.save(update_fields=["password", "must_change_password"])

    if admission.student_user_id != student_user.pk:
        admission.student_user = student_user
        admission.save(update_fields=["student_user", "updated_at"])

    return student_user
