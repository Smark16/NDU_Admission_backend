"""
AR Data Clerk — admissions data entry without admit powers.

Allowed: direct applications, view/edit applications, view admitted students,
view batches/faculties, view application payments.

Denied (hard): admit, add admitted student, revoke/restore admission,
approve/reject applications, verify physical docs, enrollment admin.
"""
from __future__ import annotations

from django.contrib.auth.models import Group, Permission

from accounts.erp_role_setup import get_permission

ROLE_NAME = "AR Data Clerk"

# Exact allow list (re-seed replaces Group.permissions).
AR_DATA_CLERK_ALLOW = (
    ("accounts", "access_admissions"),
    ("accounts", "manage_direct_applications"),
    ("admissions", "add_application"),
    ("admissions", "view_application"),
    ("admissions", "change_application"),
    ("admissions", "view_admittedstudent"),
    ("admissions", "view_batch"),
    ("admissions", "view_faculty"),
    ("admissions", "view_academiclevel"),
    ("payments", "view_applicationpayment"),
    ("accounts", "view_user"),
)

# Explicit Deny so another overlapping allow cannot unlock admit/clearance.
AR_DATA_CLERK_DENY = (
    ("admissions", "admit_applicant"),
    ("admissions", "add_admittedstudent"),
    ("admissions", "change_admittedstudent"),
    ("admissions", "delete_admittedstudent"),
    ("admissions", "revoke_admission"),
    ("admissions", "restore_revoked_admission"),
    ("admissions", "approve_application"),
    ("admissions", "reject_application"),
    ("admissions", "verify_physical_documents"),
    ("admissions", "clear_accounts_registration"),
    ("accounts", "approve_admissions"),
    ("accounts", "manage_academic_enrollment"),
)

LEGACY_GROUP_ALIASES = (
    "AR DATA CLARK",
    "AR DATA CLERK",
    "AR Data Clark",
    "AR data clerk",
)


def _resolve_perms(pairs: tuple[tuple[str, str], ...]) -> list[Permission]:
    found: list[Permission] = []
    for app_label, codename in pairs:
        perm = get_permission(Permission, app_label, codename)
        if perm:
            found.append(perm)
    return found


def seed_ar_data_clerk_role(*, stdout=None, repair_users: bool = True) -> Group:
    """
    Create/refresh AR Data Clerk with allow M2M + Deny capabilities for admit gates.
    Idempotent — safe to re-run on the server.
    """
    from accounts.models import RoleCapability, User
    from accounts.role_capabilities import sync_allows_from_group_m2m

    group, created = Group.objects.get_or_create(name=ROLE_NAME)
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
        # Ensure Deny is not also on the M2M allow list.
        group.permissions.remove(perm)

    # Merge typo / legacy group names into the canonical role.
    for alias in LEGACY_GROUP_ALIASES:
        legacy = Group.objects.filter(name__iexact=alias).exclude(pk=group.pk).first()
        if not legacy:
            continue
        for user in User.objects.filter(groups=legacy).iterator():
            user.groups.remove(legacy)
            user.groups.add(group)
        if stdout:
            stdout.write(f"  merged legacy group '{legacy.name}' → '{ROLE_NAME}'")
        legacy.delete()

    if repair_users:
        clerk_groups = Group.objects.filter(name__icontains="ar data")
        updated = 0
        for user in User.objects.filter(groups__in=clerk_groups).distinct().iterator():
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
            f"  {action} '{ROLE_NAME}': {len(allows)} allow, {len(deny_perms)} deny"
        )
        missing_allow = [
            f"{a}.{c}"
            for a, c in AR_DATA_CLERK_ALLOW
            if not get_permission(Permission, a, c)
        ]
        missing_deny = [
            f"{a}.{c}"
            for a, c in AR_DATA_CLERK_DENY
            if not get_permission(Permission, a, c)
        ]
        if missing_allow:
            stdout.write(f"  WARNING missing allow perms: {', '.join(missing_allow)}")
        if missing_deny:
            stdout.write(f"  WARNING missing deny perms: {', '.join(missing_deny)}")

    return group
