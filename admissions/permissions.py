from rest_framework.permissions import BasePermission

from accounts.erp_drf_permissions import user_has_any_erp_perm


class VerifyPhysicalDocumentsPermission(BasePermission):
    message = "You do not have permission to verify physical admission documents."

    def has_permission(self, request, view):
        u = request.user
        if not u.is_authenticated:
            return False
        if u.is_superuser:
            return True
        return u.has_perm("admissions.verify_physical_documents")


class ExportVerificationRegisterPermission(BasePermission):
    """Export including verification columns — staff with verify perm or reports access."""

    message = "You do not have permission to export this report."

    def has_permission(self, request, view):
        u = request.user
        if not u.is_authenticated:
            return False
        if u.is_superuser:
            return True
        if u.has_perm("admissions.verify_physical_documents"):
            return True
        if user_has_any_erp_perm(u, "access_reports"):
            return True
        return False
