"""
AR Data Clerk — full Admissions module access.

Can: admit, revoke/restore, generate offer letters, manage applications /
direct admission / intakes / templates / reports.

Kept out (finance / enrollment ops — trim later in Roles UI if needed):
accounts clearance, temporary access passes, SPE enrollment admin.
"""
from __future__ import annotations

from django.contrib.auth.models import Group, Permission
from django.db.models import Q

from accounts.erp_role_setup import get_permission

ROLE_NAME = "AR Data Clerk"

# Broad admissions allow list — re-seed replaces Group.permissions.
AR_DATA_CLERK_ALLOW = (
    # Module gates
    ("accounts", "access_admissions"),
    ("accounts", "manage_direct_applications"),
    ("accounts", "approve_admissions"),
    ("accounts", "manage_batches"),
    ("accounts", "manage_communication_templates"),
    ("accounts", "access_reports"),
    ("accounts", "view_user"),
    # Applications
    ("admissions", "add_application"),
    ("admissions", "view_application"),
    ("admissions", "change_application"),
    ("admissions", "delete_application"),
    ("admissions", "approve_application"),
    ("admissions", "reject_application"),
    ("admissions", "admit_applicant"),
    ("admissions", "edit_application_registration"),
    # Admitted students / offers / revoke
    ("admissions", "add_admittedstudent"),
    ("admissions", "view_admittedstudent"),
    ("admissions", "change_admittedstudent"),
    ("admissions", "delete_admittedstudent"),
    ("admissions", "revoke_admission"),
    ("admissions", "restore_revoked_admission"),
    ("admissions", "verify_physical_documents"),
    # Setup
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
    # Offer letter templates (generate uses admitted-student change/admit)
    ("AdmissionLetter", "view_offerlettertemplate"),
    ("AdmissionLetter", "add_offerlettertemplate"),
    ("AdmissionLetter", "change_offerlettertemplate"),
    ("AdmissionLetter", "delete_offerlettertemplate"),
    # Reports / drafts / payments visibility
    ("AdmissionReports", "view_admissionreports"),
    ("AdmissionReports", "view_setup"),
    ("Drafts", "view_draftapplication"),
    ("Drafts", "change_draftapplication"),
    ("payments", "view_applicationpayment"),
)

# Soft excludes — not core AR admissions ops.
AR_DATA_CLERK_DENY = (
    ("admissions", "clear_accounts_registration"),
    ("admissions", "manage_temporary_access_pass"),
    ("accounts", "manage_academic_enrollment"),
)


def _resolve_perms(pairs: tuple[tuple[str, str], ...]) -> list[Permission]:
    found: list[Permission] = []
    for app_label, codename in pairs:
        perm = get_permission(Permission, app_label, codename)
        if perm:
            found.append(perm)
    return found


def _merge_duplicate_clerk_groups(canonical: Group, *, stdout=None) -> int:
    """
    Fold every AR Data Clerk / Clark variant into the canonical group, then delete extras.
    """
    from accounts.models import User

    duplicates = (
        Group.objects.filter(
            Q(name__icontains="ar data clerk")
            | Q(name__icontains="ar data clark")
            | Q(name__iexact="AR DATA CLERK")
            | Q(name__iexact="AR DATA CLARK")
        )
        .exclude(pk=canonical.pk)
        .distinct()
    )
    merged = 0
    for legacy in duplicates:
        for user in User.objects.filter(groups=legacy).iterator():
            user.groups.remove(legacy)
            user.groups.add(canonical)
        if stdout:
            stdout.write(f"  merged duplicate group '{legacy.name}' → '{ROLE_NAME}'")
        legacy.delete()
        merged += 1
    return merged


def seed_ar_data_clerk_role(*, stdout=None, repair_users: bool = True) -> Group:
    """
    Create/refresh AR Data Clerk with full admissions allows.
    Clears previous Deny matrix for this role, then applies soft finance/enrollment denies.
    Idempotent — safe to re-run on the server.
    """
    from accounts.models import RoleCapability, User
    from accounts.role_capabilities import sync_allows_from_group_m2m

    group, created = Group.objects.get_or_create(name=ROLE_NAME)
    merged = _merge_duplicate_clerk_groups(group, stdout=stdout)

    # Wipe prior Allow/Deny matrix so old "no admit" denies are gone.
    RoleCapability.objects.filter(group=group).delete()
    # Also clear admit-related Deny rows left on any leftover AR Data* groups.
    admit_deny_codes = (
        "admit_applicant",
        "add_admittedstudent",
        "change_admittedstudent",
        "revoke_admission",
        "restore_revoked_admission",
        "approve_application",
        "reject_application",
    )
    RoleCapability.objects.filter(
        group__name__icontains="ar data",
        state=RoleCapability.STATE_DENY,
        permission__codename__in=admit_deny_codes,
    ).delete()

    allows = _resolve_perms(AR_DATA_CLERK_ALLOW)
    group.permissions.set(allows)
    sync_allows_from_group_m2m(group)

    deny_perms = _resolve_perms(AR_DATA_CLERK_DENY)
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
        clerk_users = User.objects.filter(groups=group).distinct()
        updated = 0
        for user in clerk_users.iterator():
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
            stdout.write(f"  repaired portal flags for {updated} clerk user(s)")

    if stdout:
        action = "Created" if created else "Updated"
        stdout.write(
            f"  {action} '{ROLE_NAME}': {len(allows)} allow, {len(deny_perms)} soft-deny"
            + (f", merged {merged} duplicate group(s)" if merged else "")
        )
        missing = [
            f"{a}.{c}"
            for a, c in AR_DATA_CLERK_ALLOW
            if not get_permission(Permission, a, c)
        ]
        if missing:
            stdout.write(f"  WARNING missing allow perms: {', '.join(missing)}")

    return group
