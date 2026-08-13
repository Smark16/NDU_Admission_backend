"""Coarse ERP module checks for DRF (uses auth.Permission on accounts.ErpAccessPolicy).

Superusers bypass checks. Everyone else must have the relevant permission codename(s)
assigned via Django Groups (or user_permissions); being ``is_staff`` alone is not enough.
"""
from rest_framework.permissions import BasePermission


from accounts.super_admin import user_is_super_admin


def user_has_any_erp_perm(user, *codenames: str) -> bool:
    if not user.is_authenticated:
        return False
    if user_is_super_admin(user):
        return True
    return any(user.has_perm(f"accounts.{c}") for c in codenames)


class CanViewAdmissionsAnalytics(BasePermission):
    def has_permission(self, request, view):
        u = request.user
        if not u.is_authenticated:
            return False
        if user_is_super_admin(u):
            return True
        if user_has_any_erp_perm(u, "access_reports", "access_admissions"):
            return True
        if u.has_perm("admissions.view_application"):
            return True
        return False


class FinanceModuleAdminPermission(BasePermission):
    """Ledger, exports, and finance tools — not applicant self-service."""

    message = "You do not have permission to access finance administration."

    def has_permission(self, request, view):
        u = request.user
        if not u.is_authenticated:
            return False
        if user_is_super_admin(u):
            return True
        return user_has_any_erp_perm(
            u,
            "access_finance",
            "manage_payment_reconciliation",
            "configure_fee_plans",
        )


class AccountsClearedReportPermission(BasePermission):
    """Who can view the accounts-cleared-for-registration report."""

    message = "You do not have permission to view accounts clearance reports."

    def has_permission(self, request, view):
        u = request.user
        if not u.is_authenticated:
            return False
        if user_is_super_admin(u):
            return True
        if user_has_any_erp_perm(
            u,
            "access_finance",
            "manage_payment_reconciliation",
            "access_reports",
        ):
            return True
        return bool(u.has_perm("admissions.clear_accounts_registration"))


class IsSuperAdminOnly(BasePermission):
    """Temporary hard gate for sensitive finance ops (e.g. manual bank posting)."""

    message = "Only Super Admin can perform this action for now."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and user_is_super_admin(request.user))


class CanViewAdmissionQueues(BasePermission):
    """
    Application list / queue endpoints (all applications, direct entry, rejected).
    Requires an assigned admissions/report/view permission — not granted solely because the user is staff.
    """

    _ERP_QUEUE = (
        "access_admissions",
        "access_reports",
        "approve_admissions",
        "manage_direct_applications",
        "manage_batches",
    )

    def has_permission(self, request, view):
        u = request.user
        if not u.is_authenticated:
            return False
        if user_is_super_admin(u):
            return True
        if user_has_any_erp_perm(u, *self._ERP_QUEUE):
            return True
        if u.has_perm("admissions.view_application"):
            return True
        return False


class CanVerifyStudentCardPermission(BasePermission):
    """
    Finance card scan desk — assignable via Role Management
    (accounts.verify_student_cards).
    """

    message = "You do not have permission to verify student ID / registration cards."

    def has_permission(self, request, view):
        u = request.user
        if not u.is_authenticated:
            return False
        if user_is_super_admin(u):
            return True
        return user_has_any_erp_perm(u, "verify_student_cards")
