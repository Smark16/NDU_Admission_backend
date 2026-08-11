"""
Admissions Team — Admissions-focused staff role.

Can: applications, direct entry / direct admission, approve/reject, admit/revoke,
offer letters, intakes, subjects/templates, academic levels/years, admission reports.

Sidebar follows Role Management ticks (no hard module hide). Soft-deny blocks
Finance / Academics / User Management / Fees. Student directory View is kept
for admit/offer APIs and will show Students menus that use that permission.
"""
from __future__ import annotations

from django.contrib.auth.models import Group, Permission

from accounts.erp_role_setup import get_permission

ROLE_NAME = "Admissions Team"

# Avoid granting perms that open unrelated modules unless intended:
# - accounts.view_user           -> User Management + Prospective Students
# - accounts.access_reports      -> broad Reports
# - payments.view_applicationpayment -> Fees & tuition
# view_admittedstudent is required for admit/offer APIs (also unlocks Students menus).
ADMISSIONS_TEAM_ALLOW = (
    ("accounts", "access_admissions"),
    ("accounts", "manage_direct_applications"),
    ("accounts", "approve_admissions"),
    ("accounts", "manage_batches"),
    ("accounts", "manage_communication_templates"),
    # Applications
    ("admissions", "add_application"),
    ("admissions", "view_application"),
    ("admissions", "change_application"),
    ("admissions", "delete_application"),
    ("admissions", "approve_application"),
    ("admissions", "reject_application"),
    ("admissions", "admit_applicant"),
    ("admissions", "edit_application_registration"),
    # Admitted students (API for admit / offers / revoke — not for other modules)
    ("admissions", "add_admittedstudent"),
    ("admissions", "view_admittedstudent"),
    ("admissions", "change_admittedstudent"),
    ("admissions", "delete_admittedstudent"),
    ("admissions", "revoke_admission"),
    ("admissions", "restore_revoked_admission"),
    ("admissions", "verify_physical_documents"),
    # Intakes & admissions setup
    ("admissions", "view_batch"),
    ("admissions", "add_batch"),
    ("admissions", "change_batch"),
    ("admissions", "delete_batch"),
    ("admissions", "view_faculty"),
    ("admissions", "view_academiclevel"),
    ("admissions", "add_academiclevel"),
    ("admissions", "change_academiclevel"),
    ("admissions", "view_academicyear"),
    ("admissions", "add_academicyear"),
    ("admissions", "change_academicyear"),
    ("admissions", "view_olevelsubject"),
    ("admissions", "add_olevelsubject"),
    ("admissions", "change_olevelsubject"),
    ("admissions", "view_alevelsubject"),
    ("admissions", "add_alevelsubject"),
    ("admissions", "change_alevelsubject"),
    ("admissions", "view_emailtemplate"),
    ("admissions", "add_emailtemplate"),
    ("admissions", "change_emailtemplate"),
    ("admissions", "view_applicationdocument"),
    ("admissions", "change_applicationdocument"),
    # Offer letters
    ("AdmissionLetter", "view_offerlettertemplate"),
    ("AdmissionLetter", "add_offerlettertemplate"),
    ("AdmissionLetter", "change_offerlettertemplate"),
    ("AdmissionLetter", "delete_offerlettertemplate"),
    # Reports category: Admission reports (+ setup). access_reports stays denied.
    ("AdmissionReports", "view_admissionreports"),
    ("AdmissionReports", "view_setup"),
    ("Drafts", "view_draftapplication"),
    ("Drafts", "change_draftapplication"),
)

ADMISSIONS_TEAM_DENY = (
    ("accounts", "access_finance"),
    ("accounts", "access_academics"),
    ("accounts", "access_reports"),
    ("accounts", "access_user_management"),
    ("accounts", "configure_fee_plans"),
    ("accounts", "manage_payment_reconciliation"),
    ("accounts", "manage_academic_enrollment"),
    ("accounts", "manage_curriculum"),
    ("accounts", "manage_course_catalog"),
    ("accounts", "manage_program_scheduling"),
    ("admissions", "clear_accounts_registration"),
    ("admissions", "manage_temporary_access_pass"),
    ("admissions", "manage_id_cards"),
    ("payments", "view_applicationfee"),
    ("payments", "view_applicationpayment"),
    ("payments", "view_feehead"),
    ("payments", "view_feeplan"),
    ("payments", "view_feeplanrule"),
    ("payments", "view_studenttuitionpayment"),
    ("payments", "view_tuitionledger"),
)


def _resolve_perms(pairs: tuple[tuple[str, str], ...]) -> list[Permission]:
    found: list[Permission] = []
    for app_label, codename in pairs:
        perm = get_permission(Permission, app_label, codename)
        if perm:
            found.append(perm)
    return found


def seed_admissions_team_role(*, stdout=None, repair_users: bool = True) -> Group:
    """Create/refresh Admissions Team role. Idempotent."""
    from accounts.models import RoleCapability, User
    from accounts.role_capabilities import sync_allows_from_group_m2m

    group, created = Group.objects.get_or_create(name=ROLE_NAME)
    RoleCapability.objects.filter(group=group).delete()

    allows = _resolve_perms(ADMISSIONS_TEAM_ALLOW)
    group.permissions.set(allows)
    sync_allows_from_group_m2m(group)

    deny_perms = _resolve_perms(ADMISSIONS_TEAM_DENY)
    allow_ids = {p.id for p in allows}
    for perm in deny_perms:
        if perm.id in allow_ids:
            continue
        RoleCapability.objects.update_or_create(
            group=group,
            permission=perm,
            defaults={"state": RoleCapability.STATE_DENY},
        )
        group.permissions.remove(perm)

    if repair_users:
        updated = 0
        for user in User.objects.filter(groups=group).distinct().iterator():
            dirty = False
            if not user.is_staff:
                user.is_staff = True
                dirty = True
            if user.is_student:
                user.is_student = False
                dirty = True
            if user.is_applicant:
                user.is_applicant = False
                dirty = True
            if getattr(user, "portal_mode", None) != "admin":
                user.portal_mode = "admin"
                dirty = True
            if dirty:
                user.save(
                    update_fields=["is_staff", "is_student", "is_applicant", "portal_mode"]
                )
                updated += 1
        if stdout:
            stdout.write(f"  repaired portal flags for {updated} user(s)")

    if stdout:
        action = "Created" if created else "Updated"
        stdout.write(
            f"  {action} '{ROLE_NAME}': {len(allows)} allow, {len(deny_perms)} deny (other modules)"
        )
        missing = [
            f"{a}.{c}"
            for a, c in ADMISSIONS_TEAM_ALLOW
            if not get_permission(Permission, a, c)
        ]
        if missing:
            stdout.write(f"  WARNING missing allow perms: {', '.join(missing)}")

    return group
