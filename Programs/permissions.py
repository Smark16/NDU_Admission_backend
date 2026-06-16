"""DRF permissions for programmes, catalog, scheduling, and enrollment (ERP-backed).

Access requires assigned Django permissions (typically via Groups). Classes below test
``accounts.<codename>`` ERP permissions and/or model permissions — there is no implicit
access based on ``User.is_staff`` alone.
"""
from __future__ import annotations

from rest_framework.permissions import BasePermission, SAFE_METHODS

from accounts.super_admin import user_is_super_admin
from accounts.erp_drf_permissions import user_has_any_erp_perm


def _superuser(user) -> bool:
    return user.is_authenticated and user_is_super_admin(user)


def user_can_configure_fee_plans(user) -> bool:
    """Finance configuration — fee heads, matrices, schedules (matches FeePlanConfigurationPermission)."""
    if not user.is_authenticated:
        return False
    if _superuser(user):
        return True
    from admissions.faculty_scope import user_is_faculty_admin, user_is_faculty_dean

    if user_is_faculty_dean(user) or user_is_faculty_admin(user):
        return False
    return user_has_any_erp_perm(
        user,
        "configure_fee_plans",
        "access_finance",
        "manage_payment_reconciliation",
    )


class CurriculumAPIPermission(BasePermission):
    """Curriculum blueprint APIs: read for academics/scheduling; write for curriculum managers."""

    message = "You do not have permission to access programme curriculum."

    def has_permission(self, request, view):
        u = request.user
        if not u.is_authenticated:
            return False
        if _superuser(u):
            return True
        if request.method in SAFE_METHODS:
            return user_has_any_erp_perm(
                u,
                "access_academics",
                "manage_curriculum",
                "manage_program_scheduling",
                "access_reports",
            )
        return user_has_any_erp_perm(u, "manage_curriculum", "access_academics")


class CatalogAPIPermission(BasePermission):
    """Shared course catalog (catalog CRUD + search)."""

    message = "You do not have permission to access the course catalog."

    def has_permission(self, request, view):
        u = request.user
        if not u.is_authenticated:
            return False
        if _superuser(u):
            return True
        if request.method in SAFE_METHODS:
            return user_has_any_erp_perm(
                u,
                "access_academics",
                "manage_course_catalog",
                "manage_curriculum",
            )
        return user_has_any_erp_perm(u, "manage_course_catalog", "access_academics")


class ProgramSchedulingAPIPermission(BasePermission):
    """Cohort batches, semesters, timetable-linked course units, programme structure."""

    message = "You do not have permission to manage programme scheduling."

    def has_permission(self, request, view):
        u = request.user
        if not u.is_authenticated:
            return False
        if _superuser(u):
            return True
        if request.method in SAFE_METHODS:
            return user_has_any_erp_perm(
                u,
                "access_academics",
                "manage_program_scheduling",
                "manage_curriculum",
                "access_reports",
            )
        return user_has_any_erp_perm(u, "manage_program_scheduling", "access_academics")


class AcademicEnrollmentAdminPermission(BasePermission):
    """Student programme enrollment (SPE), admin enrollment APIs — not student self-service."""

    message = "You do not have permission to manage academic enrollment."

    def has_permission(self, request, view):
        u = request.user
        if not u.is_authenticated:
            return False
        if _superuser(u):
            return True
        return user_has_any_erp_perm(u, "manage_academic_enrollment", "access_academics")


class CurriculumOverrideAPIPermission(BasePermission):
    """Student-specific curriculum overrides (faculty decisions)."""

    message = "You do not have permission to manage curriculum overrides."

    def has_permission(self, request, view):
        u = request.user
        if not u.is_authenticated:
            return False
        if _superuser(u):
            return True
        return user_has_any_erp_perm(u, "manage_academic_enrollment", "access_academics")


class FeePlanConfigurationPermission(BasePermission):
    """Tuition matrices, fee schedules, billing rules — finance configuration."""

    message = "You do not have permission to configure fee plans."

    def has_permission(self, request, view):
        return user_can_configure_fee_plans(request.user)


class CommunicationTemplatesPermission(BasePermission):
    """Transactional email templates (admissions, system)."""

    message = "You do not have permission to manage communication templates."

    def has_permission(self, request, view):
        u = request.user
        if not u.is_authenticated:
            return False
        if _superuser(u):
            return True
        return user_has_any_erp_perm(
            u,
            "manage_communication_templates",
            "access_system_settings",
            "approve_admissions",
        )
