"""Coarse ERP module checks for DRF (uses auth.Permission on accounts.ErpAccessPolicy)."""
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
        if getattr(u, "is_staff", False) and not getattr(u, "is_applicant", False):
            return True
        return False


class CanViewAdmissionQueues(BasePermission):
    """
    Application list / queue endpoints (all applications, direct entry, rejected).
    Broader than DjangoModelPermissions: any ERP admissions workflow role, model view,
    or non-applicant staff (covers legacy accounts where groups were not fully synced).
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
        if getattr(u, "is_staff", False) and not getattr(u, "is_applicant", False):
            return True
        return False
