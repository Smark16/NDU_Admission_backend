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
        return u.has_perm("admissions.view_application")
