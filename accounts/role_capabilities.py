"""Role capability matrix helpers (Allow / Deny). Deny wins across roles."""

from __future__ import annotations

from django.contrib.auth.models import Group, Permission
from django.db import transaction

from accounts.models import RoleCapability
from accounts.super_admin import user_is_super_admin


def permission_label(perm: Permission) -> str:
    return f"{perm.content_type.app_label}.{perm.codename}"


def denied_permission_strings_for_user(user) -> set[str]:
    """Permission strings denied by any of the user's roles."""
    if not user or not getattr(user, "is_authenticated", False):
        return set()
    if user_is_super_admin(user) or getattr(user, "is_superuser", False):
        return set()
    group_ids = list(user.groups.values_list("id", flat=True))
    if not group_ids:
        return set()
    rows = (
        RoleCapability.objects.filter(
            group_id__in=group_ids,
            state=RoleCapability.STATE_DENY,
        )
        .select_related("permission", "permission__content_type")
        .iterator()
    )
    return {permission_label(rc.permission) for rc in rows}


def effective_permission_strings(user) -> list[str]:
    """Allows from Django, minus any role Deny. Super Admin → all permissions."""
    from django.contrib.auth.models import Permission as PermModel

    if not user or not getattr(user, "is_authenticated", False):
        return []
    if user_is_super_admin(user) or getattr(user, "is_superuser", False):
        return [
            f"{p.content_type.app_label}.{p.codename}"
            for p in PermModel.objects.select_related("content_type").iterator()
        ]
    # Bypass auth-backend cache quirks: compute from groups + user_permissions,
    # then subtract denies.
    allowed: set[str] = set()
    for p in user.user_permissions.select_related("content_type").all():
        allowed.add(permission_label(p))
    for group in user.groups.prefetch_related("permissions__content_type").all():
        for p in group.permissions.all():
            allowed.add(permission_label(p))
    # Also honour RoleCapability Allow rows that may not yet be mirrored on M2M.
    group_ids = list(user.groups.values_list("id", flat=True))
    if group_ids:
        for rc in (
            RoleCapability.objects.filter(
                group_id__in=group_ids,
                state=RoleCapability.STATE_ALLOW,
            )
            .select_related("permission", "permission__content_type")
            .iterator()
        ):
            allowed.add(permission_label(rc.permission))
    denied = denied_permission_strings_for_user(user)
    return sorted(allowed - denied)


def sync_group_m2m_from_allows(group: Group) -> None:
    """Set Group.permissions M2M to RoleCapability Allow rows only."""
    allow_ids = list(
        RoleCapability.objects.filter(
            group=group,
            state=RoleCapability.STATE_ALLOW,
        ).values_list("permission_id", flat=True)
    )
    group.permissions.set(allow_ids)


def sync_allows_from_group_m2m(group: Group) -> None:
    """
    Mirror current Group.permissions as Allow rows.
    Existing Deny rows are kept (even if that perm is not on the M2M).
    Allow rows for perms no longer on the M2M are removed.
    """
    m2m_ids = set(group.permissions.values_list("id", flat=True))
    with transaction.atomic():
        RoleCapability.objects.filter(
            group=group,
            state=RoleCapability.STATE_ALLOW,
        ).exclude(permission_id__in=m2m_ids).delete()
        existing_allow = set(
            RoleCapability.objects.filter(
                group=group,
                state=RoleCapability.STATE_ALLOW,
            ).values_list("permission_id", flat=True)
        )
        to_create = []
        for pid in m2m_ids - existing_allow:
            # If a Deny exists for this perm, leave it (explicit deny wins on matrix).
            if RoleCapability.objects.filter(
                group=group, permission_id=pid, state=RoleCapability.STATE_DENY
            ).exists():
                continue
            to_create.append(
                RoleCapability(
                    group=group,
                    permission_id=pid,
                    state=RoleCapability.STATE_ALLOW,
                )
            )
        if to_create:
            RoleCapability.objects.bulk_create(to_create, ignore_conflicts=True)


def replace_group_capabilities(
    group: Group,
    entries: list[dict],
) -> list[RoleCapability]:
    """
    Replace the group's capability matrix.
    entries: [{"permission_id": int, "state": "allow"|"deny"}, ...]
    Not-set = omit from entries.
    """
    cleaned: dict[int, str] = {}
    for raw in entries:
        try:
            pid = int(raw.get("permission_id"))
        except (TypeError, ValueError, AttributeError):
            continue
        state = (raw.get("state") or "").strip().lower()
        if state not in (RoleCapability.STATE_ALLOW, RoleCapability.STATE_DENY):
            continue
        cleaned[pid] = state

    valid_ids = set(
        Permission.objects.filter(id__in=cleaned.keys()).values_list("id", flat=True)
    )
    cleaned = {pid: st for pid, st in cleaned.items() if pid in valid_ids}

    with transaction.atomic():
        RoleCapability.objects.filter(group=group).delete()
        rows = [
            RoleCapability(group=group, permission_id=pid, state=st)
            for pid, st in cleaned.items()
        ]
        if rows:
            RoleCapability.objects.bulk_create(rows)
        sync_group_m2m_from_allows(group)

    return list(
        RoleCapability.objects.filter(group=group)
        .select_related("permission", "permission__content_type")
        .order_by("permission__content_type__app_label", "permission__codename")
    )


def backfill_all_group_allows(*, stdout=None) -> int:
    """Create Allow RoleCapability rows from every Group.permissions M2M."""
    count = 0
    for group in Group.objects.all().iterator():
        before = RoleCapability.objects.filter(group=group).count()
        sync_allows_from_group_m2m(group)
        after = RoleCapability.objects.filter(group=group).count()
        count += max(0, after - before)
        if stdout:
            stdout.write(f"  synced {group.name}: +{max(0, after - before)} allow rows")
    return count


def user_can_manage_role_capabilities(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user_is_super_admin(user) or getattr(user, "is_superuser", False):
        return True
    # Direct check (avoid auth-backend recursion during edge cases).
    if user.groups.filter(
        permissions__content_type__app_label="accounts",
        permissions__codename="manage_role_capabilities",
    ).exists():
        return True
    return user.user_permissions.filter(
        content_type__app_label="accounts",
        codename="manage_role_capabilities",
    ).exists()
