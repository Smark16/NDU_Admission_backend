"""Assignable Super Admin role — full system access without Django is_superuser."""
from __future__ import annotations

SUPER_ADMIN_GROUP_NAME = "Super Admin"


def user_is_super_admin(user) -> bool:
    """True for Django superusers or members of the Super Admin group."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    try:
        return user.groups.filter(name__iexact=SUPER_ADMIN_GROUP_NAME).exists()
    except Exception:
        return False


def seed_super_admin_role(Group, Permission, *, stdout=None):
    """Create/update Super Admin group with every permission in the database."""
    group, created = Group.objects.get_or_create(name=SUPER_ADMIN_GROUP_NAME)
    all_perms = list(Permission.objects.all())
    group.permissions.set(all_perms)
    if stdout:
        verb = "Created" if created else "Updated"
        stdout.write(f"  {verb} {SUPER_ADMIN_GROUP_NAME} ({len(all_perms)} permissions)")
    return group
