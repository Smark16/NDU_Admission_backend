"""Coarse ERP module checks for DRF (uses auth.Permission on accounts.ErpAccessPolicy).

Superusers bypass checks. Everyone else must have the relevant permission codename(s)
assigned via Django Groups (or user_permissions); being ``is_staff`` alone is not enough.
"""
from rest_framework.permissions import BasePermission


def user_has_any_erp_perm(user, *codenames: str) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return any(user.has_perm(f"accounts.{c}") for c in codenames)


class CanViewAdmissionsAnalytics(BasePermission):
    def has_permission(self, request, view):
        u = request.user
        if not u.is_authenticated:
            return False
        if u.is_superuser:
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
        if u.is_superuser:
            return True
        return user_has_any_erp_perm(
            u,
            "access_finance",
            "manage_payment_reconciliation",
            "configure_fee_plans",
        )


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
        if u.is_superuser:
            return True
        if user_has_any_erp_perm(u, *self._ERP_QUEUE):
            return True
        if u.has_perm("admissions.view_application"):
            return True
        return False
