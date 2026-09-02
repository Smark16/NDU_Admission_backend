"""Access helpers for portal messaging."""
from __future__ import annotations

from django.db.models import Q, QuerySet

from django.conf import settings

from accounts.super_admin import user_is_super_admin

# Groups students may contact as "Faculty / Registry" inbox (override via settings).
DEFAULT_FACULTY_INBOX_GROUPS = (
    "Admissions Team",
    "Admissions Approver",
    "Enrollment Officer",
    "Document Verification Officer",
    "AR Data Clerk",
    "Faculty Admin",
    "Faculty Dean",
    "Super Admin",
)


def faculty_inbox_group_names() -> tuple[str, ...]:
    configured = getattr(settings, "MESSAGING_FACULTY_INBOX_GROUPS", None)
    if configured:
        return tuple(str(n).strip() for n in configured if str(n).strip())
    return DEFAULT_FACULTY_INBOX_GROUPS


def user_is_student_portal(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if getattr(user, "is_student", False):
        return True
    return hasattr(user, "student_admission") and user.student_admission_id is not None


def user_is_lecturer_portal(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user_is_super_admin(user):
        return False
    if getattr(user, "is_lecturer", False):
        return True
    try:
        return user.groups.filter(name__iexact="Lecturer").exists()
    except Exception:
        return False


def user_can_use_staff_inbox(user) -> bool:
    """Admin / registry / any staff (non-student) who may message any student."""
    if not user or not user.is_authenticated:
        return False
    if user_is_super_admin(user):
        return True
    if user_is_student_portal(user) and not getattr(user, "is_staff", False):
        return False
    if user_is_lecturer_portal(user) and not getattr(user, "is_staff", False):
        return False
    if getattr(user, "is_staff", False):
        return True
    if user.has_perm("messaging.use_staff_inbox"):
        return True
    return False


def admitted_student_for_user(user):
    from admissions.models import AdmittedStudent

    if not user or not user.is_authenticated:
        return None
    try:
        linked = getattr(user, "student_admission", None)
        if linked is not None:
            return linked
    except Exception:
        pass
    return (
        AdmittedStudent.objects.filter(
            Q(student_user=user)
            | Q(application__applicant=user)
            | Q(reg_no=getattr(user, "username", "") or "")
        )
        .select_related("application", "admitted_program")
        .first()
    )


def lecturer_can_message_student(lecturer, admitted_student) -> bool:
    from Programs.models import StudentCourseUnitEnrollment

    if not lecturer or not admitted_student:
        return False
    return StudentCourseUnitEnrollment.objects.filter(
        student=admitted_student,
        status="enrolled",
        course_unit__is_active=True,
        course_unit__lecturers=lecturer,
    ).exists()


def student_can_message_lecturer(student_user, lecturer) -> bool:
    admitted = admitted_student_for_user(student_user)
    if admitted is None:
        return False
    return lecturer_can_message_student(lecturer, admitted)


def ensure_student_user(admitted_student):
    """Return portal User for the student, creating one if needed."""
    if admitted_student.student_user_id:
        return admitted_student.student_user
    try:
        from admissions.student_accounts import ensure_student_portal_account

        ensure_student_portal_account(admitted_student)
        admitted_student.refresh_from_db(fields=["student_user"])
    except Exception:
        pass
    return admitted_student.student_user


def conversations_for_user(user) -> QuerySet:
    from messaging.models import Conversation

    qs = Conversation.objects.select_related(
        "student",
        "student__application",
        "student__admitted_program",
        "created_by",
    ).prefetch_related("participants")

    if user_can_use_staff_inbox(user):
        return qs.filter(participants__user=user).distinct()

    if user_is_lecturer_portal(user):
        return qs.filter(participants__user=user).distinct()

    admitted = admitted_student_for_user(user)
    if admitted is not None:
        return qs.filter(student=admitted).distinct()

    return qs.none()


def user_can_access_conversation(user, conversation) -> bool:
    if not user or not conversation:
        return False
    if conversation.participants.filter(user=user).exists():
        return True
    if user_can_use_staff_inbox(user):
        # Staff may open any student thread they are on; joining is via create/start.
        return conversation.participants.filter(user=user).exists()
    return False


def search_admitted_students(query: str, *, limit: int = 25):
    from admissions.models import AdmittedStudent

    q = (query or "").strip()
    qs = AdmittedStudent.objects.filter(is_admitted=True).select_related(
        "application", "admitted_program", "student_user"
    )
    if not q:
        return qs.none()
    if q.isdigit():
        by_pk = qs.filter(pk=int(q)).first()
        if by_pk:
            return [by_pk]
    tokens = q.split()
    filt = (
        Q(student_id__icontains=q)
        | Q(reg_no__icontains=q)
        | Q(schoolpay_code__icontains=q)
        | Q(application__first_name__icontains=q)
        | Q(application__last_name__icontains=q)
        | Q(application__full_name__icontains=q)
    )
    if q.isdigit():
        filt |= Q(pk=int(q))
    if len(tokens) >= 2:
        filt |= Q(application__first_name__icontains=tokens[0]) & Q(
            application__last_name__icontains=tokens[-1]
        )
    return qs.filter(filt).order_by("application__full_name")[:limit]


def lecturers_for_student(admitted_student):
    """Distinct lecturer Users teaching courses the student is enrolled on."""
    from accounts.models import User
    from Programs.models import StudentCourseUnitEnrollment

    lecturer_ids = (
        StudentCourseUnitEnrollment.objects.filter(
            student=admitted_student,
            status="enrolled",
            course_unit__is_active=True,
        )
        .values_list("course_unit__lecturers", flat=True)
        .distinct()
    )
    return User.objects.filter(pk__in=[i for i in lecturer_ids if i]).order_by(
        "first_name", "last_name", "username"
    )


def faculty_inbox_contacts(*, limit: int = 40):
    """Active staff users students may message as Faculty / Registry."""
    from accounts.models import User

    groups = faculty_inbox_group_names()
    qs = (
        User.objects.filter(is_active=True)
        .filter(
            Q(groups__name__in=groups)
            | Q(user_permissions__codename="use_staff_inbox", user_permissions__content_type__app_label="messaging")
            | Q(groups__permissions__codename="use_staff_inbox", groups__permissions__content_type__app_label="messaging")
        )
        .exclude(is_student=True)
        .distinct()
        .order_by("first_name", "last_name", "username")
    )
    return qs[:limit]


def student_can_message_faculty_staff(student_user, staff_user) -> bool:
    if not student_user or not staff_user:
        return False
    if admitted_student_for_user(student_user) is None:
        return False
    from accounts.models import User

    groups = faculty_inbox_group_names()
    return (
        User.objects.filter(pk=staff_user.pk, is_active=True)
        .exclude(is_student=True)
        .filter(
            Q(groups__name__in=groups)
            | Q(
                user_permissions__codename="use_staff_inbox",
                user_permissions__content_type__app_label="messaging",
            )
            | Q(
                groups__permissions__codename="use_staff_inbox",
                groups__permissions__content_type__app_label="messaging",
            )
        )
        .exists()
    )
