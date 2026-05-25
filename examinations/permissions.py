"""DRF permissions for the examinations module (group-based, not staff-only)."""
from rest_framework.permissions import BasePermission

from Programs.models import CourseUnit

# Codenames on examinations.* models (no app prefix in has_perm).
EXAM_ENTER_MARKS = "examinations.enter_marks"
EXAM_PUBLISH_RESULTS = "examinations.publish_results"
EXAM_VIEW_ALL_RESULTS = "examinations.view_all_results"
EXAM_MANAGE_SCHEDULE = "examinations.manage_exam_schedule"
EXAM_MANAGE_RETAKES = "examinations.manage_retakes"
EXAM_APPROVE_CHANGES = "examinations.approve_result_changes"
EXAM_ACCESS_MODULE = "accounts.access_examinations"

OFFICE_CODENAMES = (
    "enter_marks",
    "publish_results",
    "view_all_results",
    "manage_exam_schedule",
    "manage_retakes",
    "approve_result_changes",
)


def _has(user, perm: str) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.has_perm(perm)


def user_has_any_examination_perm(user, *codenames: str) -> bool:
    """True if user has module access or any listed examinations.* permission."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if _has(user, EXAM_ACCESS_MODULE):
        return True
    return any(_has(user, f"examinations.{c}") for c in codenames)


def user_can_access_examinations_office(user) -> bool:
    return user_has_any_examination_perm(user, *OFFICE_CODENAMES)


def user_can_manage_course_marks(user, course_unit: CourseUnit) -> bool:
    """
    Lecturers: assigned course only.
    Examinations office: any course when they hold office permissions.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if user_can_access_examinations_office(user):
        if user_has_any_examination_perm(
            user, "enter_marks", "publish_results", "view_all_results"
        ):
            return True
    return course_unit.lecturers.filter(pk=user.pk).exists()


# Backward-compatible alias used in views.
def user_teaches_course_unit(user, course_unit) -> bool:
    return user_can_manage_course_marks(user, course_unit)


class CanManageAssessmentPolicies(BasePermission):
    """Senate-style policy configuration (examination managers / publishers)."""

    message = "You do not have permission to manage assessment policies."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        return user_has_any_examination_perm(request.user, "publish_results")


class CanAccessExaminationsOffice(BasePermission):
    message = "You do not have permission to access the examinations module."

    def has_permission(self, request, view):
        return user_can_access_examinations_office(request.user)


class CanEnterMarks(BasePermission):
    message = "You do not have permission to enter examination marks."

    def has_permission(self, request, view):
        return user_has_any_examination_perm(request.user, "enter_marks")


class CanPublishResults(BasePermission):
    message = "You do not have permission to publish examination results."

    def has_permission(self, request, view):
        return user_has_any_examination_perm(request.user, "publish_results")


class CanViewAllResults(BasePermission):
    message = "You do not have permission to view examination results."

    def has_permission(self, request, view):
        return user_has_any_examination_perm(request.user, "view_all_results")


class CanManageExamSchedule(BasePermission):
    message = "You do not have permission to manage the exam timetable."

    def has_permission(self, request, view):
        return user_has_any_examination_perm(request.user, "manage_exam_schedule")


class CanManageRetakes(BasePermission):
    message = "You do not have permission to manage examination retakes."

    def has_permission(self, request, view):
        return user_has_any_examination_perm(request.user, "manage_retakes")


class CanApproveResultChanges(BasePermission):
    message = "You do not have permission to approve result changes."

    def has_permission(self, request, view):
        return user_has_any_examination_perm(request.user, "approve_result_changes")


class CanEnterMarksOrAssignedLecturer(BasePermission):
    """Authenticated users; course-level check is done in the view."""

    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        if user.is_lecturer and user_has_any_examination_perm(user, "enter_marks"):
            return True
        if user_can_access_examinations_office(user) and user_has_any_examination_perm(
            user, "enter_marks", "publish_results", "view_all_results"
        ):
            return True
        if user.is_lecturer:
            return True
        return user_has_any_examination_perm(user, "enter_marks")


class IsLecturerOrStaff(BasePermission):
    """Deprecated: prefer CanEnterMarksOrAssignedLecturer + office permissions."""

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and (user.is_staff or user.is_lecturer or user_can_access_examinations_office(user))
        )


class IsStaffUser(BasePermission):
    """Deprecated: prefer CanAccessExaminationsOffice and granular classes."""

    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        return user.is_staff or user_can_access_examinations_office(user)
