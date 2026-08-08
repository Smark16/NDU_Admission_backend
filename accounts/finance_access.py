"""Finance / Bursar access helpers.

Sensitive clearances (Accounts registration, temporary pass clear, bank credit approval)
are reserved for Bursar and Finance Manager — not every user with bare ``access_finance``.
"""
from __future__ import annotations

from accounts.erp_drf_permissions import user_has_any_erp_perm
from accounts.super_admin import user_is_super_admin

BURSAR_CLEARANCE_GROUP_NAMES = frozenset({"Bursar", "Finance Manager"})


def user_in_bursar_clearance_groups(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    try:
        return user.groups.filter(name__in=BURSAR_CLEARANCE_GROUP_NAMES).exists()
    except Exception:
        return False


def user_can_view_student_finance(user) -> bool:
    """See balances, payment history, fee lines on student lists / profiles."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if user_is_super_admin(user):
        return True
    if user_in_bursar_clearance_groups(user):
        return True
    if user_has_any_erp_perm(
        user,
        "access_finance",
        "access_reports",
        "manage_payment_reconciliation",
        "configure_fee_plans",
        "manage_scholarships",
        "view_scholarships",
        "manage_scholarship_programmes",
        "manage_scholarship_students",
    ):
        return True
    if user.has_perm("payments.view_tuitionledger"):
        return True
    if user.has_perm("admissions.clear_accounts_registration"):
        return True
    return False


def user_can_clear_accounts_registration(user) -> bool:
    """Mark / revoke Accounts registration clearance — Bursar-sensitive."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if user_is_super_admin(user):
        return True
    if user.has_perm("admissions.clear_accounts_registration"):
        return True
    if user_in_bursar_clearance_groups(user):
        return True
    return False


def user_can_issue_temporary_access_pass(user) -> bool:
    """Request/issue a temp pass (may still need Bursar approval)."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if user_is_super_admin(user):
        return True
    if user_in_bursar_clearance_groups(user):
        return True
    if user.has_perm("admissions.manage_temporary_access_pass"):
        return True
    if user.has_perm("admissions.clear_accounts_registration"):
        return True
    if user_has_any_erp_perm(
        user,
        "manage_scholarships",
        "manage_scholarship_students",
    ):
        return True
    return False


def user_can_approve_temporary_access_pass(user) -> bool:
    """Activate a pending temporary pass — Bursar / Finance Manager only."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if user_is_super_admin(user):
        return True
    if user_in_bursar_clearance_groups(user):
        return True
    if user.has_perm("admissions.clear_accounts_registration"):
        return True
    return False


def user_can_clear_temporary_access_pass(user) -> bool:
    """Revoke / clear an active temporary pass — Bursar-sensitive only."""
    return user_can_approve_temporary_access_pass(user)


def user_is_finance_directory_unscoped(user) -> bool:
    """Finance staff see students across all campuses (not campus-limited)."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if user_is_super_admin(user):
        return True
    if user_in_bursar_clearance_groups(user):
        return True
    if user_has_any_erp_perm(user, "access_finance", "manage_payment_reconciliation"):
        return True
    return False
