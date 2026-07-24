"""Admission workflow permissions (DRF + helpers).

Granular codenames (assign via Django Groups):
  admissions.approve_application
  admissions.reject_application
  admissions.admit_applicant
  admissions.manage_admission_change_requests
Existing:
  admissions.revoke_admission
  admissions.verify_physical_documents
ERP bridge (accounts.ErpAccessPolicy):
  accounts.approve_admissions — treated as broad admissions workflow access for approve/reject.
  admissions.edit_application_registration — editing applicant profile / programme choices.
"""
from rest_framework.permissions import BasePermission

from accounts.erp_drf_permissions import user_has_any_erp_perm
from accounts.super_admin import user_is_super_admin


def user_can_approve_application(user) -> bool:
    if not user.is_authenticated:
        return False
    if user_is_super_admin(user):
        return True
    if user.has_perm("admissions.approve_application"):
        return True
    if user_has_any_erp_perm(user, "approve_admissions"):
        return True
    return False


def user_can_reject_application(user) -> bool:
    if not user.is_authenticated:
        return False
    if user_is_super_admin(user):
        return True
    if user.has_perm("admissions.reject_application"):
        return True
    if user_has_any_erp_perm(user, "approve_admissions"):
        return True
    return False


def user_can_admit_applicant(user) -> bool:
    if not user.is_authenticated:
        return False
    if user_is_super_admin(user):
        return True
    if user.has_perm("admissions.admit_applicant"):
        return True
    # Legacy: model «add» permission used before admit_applicant existed
    if user.has_perm("admissions.add_admittedstudent"):
        return True
    return False


def user_can_manage_admission_change_requests(user) -> bool:
    if not user.is_authenticated:
        return False
    if user_is_super_admin(user):
        return True
    if user.has_perm("admissions.manage_admission_change_requests"):
        return True
    if user_has_any_erp_perm(user, "approve_admissions"):
        return True
    return False


def user_can_approve_exemption_requests(user) -> bool:
    if not user.is_authenticated:
        return False
    if user_is_super_admin(user):
        return True
    if user.has_perm("admissions.approve_exemption_requests"):
        return True
    return False


def user_can_edit_application_registration(user) -> bool:
    """Edit demographics / programme choices on an application (admin-side)."""
    if not user.is_authenticated:
        return False
    if user_is_super_admin(user):
        return True
    if user.has_perm("admissions.edit_application_registration"):
        return True
    if user.has_perm("admissions.change_application"):
        return True
    if user_has_any_erp_perm(user, "approve_admissions", "manage_batches"):
        return True
    return False


def user_can_restore_revoked_admission(user) -> bool:
    if not user.is_authenticated:
        return False
    if user_is_super_admin(user):
        return True
    if user.has_perm("admissions.restore_revoked_admission"):
        return True
    if user.has_perm("admissions.change_admittedstudent"):
        return True
    return False


class VerifyPhysicalDocumentsPermission(BasePermission):
    message = "You do not have permission to verify physical admission documents."

    def has_permission(self, request, view):
        u = request.user
        if not u.is_authenticated:
            return False
        if user_is_super_admin(u):
            return True
        return u.has_perm("admissions.verify_physical_documents")


class ClearAccountsRegistrationPermission(BasePermission):
    message = "You do not have permission to clear students for registration after payment."

    def has_permission(self, request, view):
        u = request.user
        if not u.is_authenticated:
            return False
        if user_is_super_admin(u):
            return True
        if u.has_perm("admissions.clear_accounts_registration"):
            return True
        # Finance staff who already manage payments can clear
        if user_has_any_erp_perm(u, "access_finance"):
            return True
        return False


class ExportVerificationRegisterPermission(BasePermission):
    """Export including verification columns — staff with verify perm or reports access."""

    message = "You do not have permission to export this report."

    def has_permission(self, request, view):
        u = request.user
        if not u.is_authenticated:
            return False
        if user_is_super_admin(u):
            return True
        if u.has_perm("admissions.verify_physical_documents"):
            return True
        if user_has_any_erp_perm(u, "access_reports"):
            return True
        return False


class CanApproveApplication(BasePermission):
    message = "You do not have permission to approve applications."

    def has_permission(self, request, view):
        return user_can_approve_application(request.user)


class CanRejectApplication(BasePermission):
    message = "You do not have permission to reject applications."

    def has_permission(self, request, view):
        return user_can_reject_application(request.user)


class CanAdmitApplicant(BasePermission):
    message = "You do not have permission to admit applicants."

    def has_permission(self, request, view):
        return user_can_admit_applicant(request.user)


class CanManageAdmissionChangeRequests(BasePermission):
    message = "You do not have permission to approve or reject admission change requests."

    def has_permission(self, request, view):
        return user_can_manage_admission_change_requests(request.user)


class CanViewAdmissionChangeRequests(BasePermission):
    """List / view admission change requests (including exemption approvers)."""

    message = "You do not have permission to view admission change requests."

    def has_permission(self, request, view):
        u = request.user
        if not u.is_authenticated:
            return False
        if user_is_super_admin(u):
            return True
        if u.has_perm("admissions.view_admissionchangerequest"):
            return True
        if user_can_manage_admission_change_requests(u):
            return True
        if user_can_approve_exemption_requests(u):
            return True
        if user_has_any_erp_perm(u, "approve_admissions", "access_admissions"):
            return True
        return False


class CanApproveExemptionRequests(BasePermission):
    message = "You do not have permission to approve or reject course exemption requests."

    def has_permission(self, request, view):
        return user_can_approve_exemption_requests(request.user)


class EditApplicationRegistrationPermission(BasePermission):
    message = "You do not have permission to edit applicant registration data."

    def has_permission(self, request, view):
        return user_can_edit_application_registration(request.user)


def user_can_manage_id_cards(user) -> bool:
    if not user.is_authenticated:
        return False
    if user_is_super_admin(user):
        return True
    if user.has_perm("admissions.manage_id_cards"):
        return True
    # Legacy / seeded “Student ID Officer”: may not have re-fetched JWT after manage_id_cards was added
    if user.has_perm("admissions.change_admittedstudent") and user.has_perm(
        "admissions.view_admittedstudent"
    ):
        return True
    return False


class ManageIdCardsPermission(BasePermission):
    message = "You do not have permission to manage student ID cards."

    def has_permission(self, request, view):
        return user_can_manage_id_cards(request.user)
