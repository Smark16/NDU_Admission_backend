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


def _permission_lookup() -> dict[str, Permission]:
    """Map ``app.codename`` → Permission."""
    out: dict[str, Permission] = {}
    for p in Permission.objects.select_related("content_type").iterator():
        out[permission_label(p)] = p
    return out


def build_service_matrix(group: Group) -> dict:
    """AIMS-style Category / Service / View-Add-Edit-Delete payload for a role."""
    from accounts.role_service_catalog import COLUMN_KEYS, ROLE_SERVICE_CATALOG, catalog_permission_labels

    perm_by_label = _permission_lookup()
    caps = {
        rc.permission_id: rc.state
        for rc in RoleCapability.objects.filter(group=group).only(
            "permission_id", "state"
        )
    }
    # Also treat M2M grants as Allow when no explicit capability row exists.
    m2m_ids = set(group.permissions.values_list("id", flat=True))

    def cell_state(perm: Permission | None) -> dict:
        if perm is None:
            return {
                "enabled": False,
                "checked": False,
                "permission_id": None,
                "label": None,
                "denied": False,
            }
        state = caps.get(perm.id)
        if state is None and perm.id in m2m_ids:
            state = RoleCapability.STATE_ALLOW
        denied = state == RoleCapability.STATE_DENY
        allowed = state == RoleCapability.STATE_ALLOW
        return {
            "enabled": True,
            "checked": allowed and not denied,
            "permission_id": perm.id,
            "label": permission_label(perm),
            "denied": denied,
        }

    categories = []
    for cat in ROLE_SERVICE_CATALOG:
        services = []
        for service in cat["services"]:
            row = {
                "key": service["key"],
                "label": service["label"],
            }
            for col in COLUMN_KEYS:
                label = service["columns"].get(col)
                perm = perm_by_label.get(label) if label else None
                # Mapped in catalog but missing from DB → disabled
                if label and perm is None:
                    row[col] = {
                        "enabled": False,
                        "checked": False,
                        "permission_id": None,
                        "label": label,
                        "denied": False,
                        "missing": True,
                    }
                else:
                    row[col] = cell_state(perm)
            services.append(row)
        categories.append({"name": cat["name"], "services": services})

    catalog_labels = catalog_permission_labels()
    deny_rows = []
    advanced_permissions = []
    for label, perm in sorted(perm_by_label.items()):
        state = caps.get(perm.id) or (
            RoleCapability.STATE_ALLOW if perm.id in m2m_ids else "not_set"
        )
        item = {
            "permission_id": perm.id,
            "label": label,
            "name": perm.name,
            "app_label": perm.content_type.app_label,
            "codename": perm.codename,
            "state": state
            if state in (RoleCapability.STATE_ALLOW, RoleCapability.STATE_DENY)
            else "not_set",
            "in_catalog": label in catalog_labels,
        }
        if state == RoleCapability.STATE_DENY:
            deny_rows.append(item)
        # Full list for Advanced Deny autocomplete (filter client-side).
        advanced_permissions.append(item)

    allow_ids = set(m2m_ids)
    for pid, st in caps.items():
        if st == RoleCapability.STATE_ALLOW:
            allow_ids.add(pid)
        elif st == RoleCapability.STATE_DENY:
            allow_ids.discard(pid)

    return {
        "group": {"id": group.id, "name": group.name},
        "categories": categories,
        "advanced": {
            "denies": deny_rows,
            "permissions": advanced_permissions,
        },
        "summary": {
            "allow": len(allow_ids),
            "deny": len(deny_rows),
        },
    }


def _parse_deny_ids(advanced_denies: list[dict] | None) -> set[int] | None:
    """
    Return the authoritative set of permission PKs to Deny, or None if the
    client did not send advanced_denies (preserve existing denies).
    """
    if advanced_denies is None:
        return None
    deny_ids: set[int] = set()
    for raw in advanced_denies:
        if not isinstance(raw, dict):
            continue
        try:
            pid = int(raw.get("permission_id"))
        except (TypeError, ValueError):
            continue
        state = (raw.get("state") or "").strip().lower()
        deny_flag = raw.get("deny")
        if deny_flag is True or state == RoleCapability.STATE_DENY:
            deny_ids.add(pid)
        # state=not_set / deny=false → omit from deny set (clears previous deny)
    return deny_ids


@transaction.atomic
def apply_service_matrix(
    group: Group,
    *,
    services: list[dict] | None = None,
    advanced_denies: list[dict] | None = None,
    deny_permission_ids: list[int] | None = None,
) -> dict:
    """
    Apply AIMS CRUD checkboxes + Advanced Deny list.

    - Catalog permissions follow service checkbox state (Allow / clear).
    - Allow rows for permissions outside the catalog are preserved.
    - When ``advanced_denies`` or ``deny_permission_ids`` is sent, that list is
      the full Deny set for the role (removed IDs are cleared).
    - Deny is applied last so it always wins over Allow on the same role.
      (Across roles, ``denied_permission_strings_for_user`` still Deny-wins.)
    """
    from accounts.role_service_catalog import (
        COLUMN_KEYS,
        catalog_permission_labels,
        service_by_key,
    )

    perm_by_label = _permission_lookup()
    catalog_labels = catalog_permission_labels()
    catalog_perm_ids = {
        perm_by_label[label].id
        for label in catalog_labels
        if label in perm_by_label
    }

    existing = {
        rc.permission_id: rc.state
        for rc in RoleCapability.objects.filter(group=group).only(
            "permission_id", "state"
        )
    }
    for pid in group.permissions.values_list("id", flat=True):
        if pid not in existing:
            existing[pid] = RoleCapability.STATE_ALLOW

    # Non-catalog allows only (denies applied at the end).
    next_state: dict[int, str] = {}
    for pid, st in existing.items():
        if st == RoleCapability.STATE_ALLOW and pid not in catalog_perm_ids:
            next_state[pid] = RoleCapability.STATE_ALLOW

    # Catalog checkboxes → Allow / clear
    grid_allow_ids: set[int] = set()
    for raw in services or []:
        if not isinstance(raw, dict):
            continue
        key = (raw.get("key") or "").strip()
        service = service_by_key(key)
        if not service:
            continue
        for col in COLUMN_KEYS:
            label = service["columns"].get(col)
            if not label:
                continue
            perm = perm_by_label.get(label)
            if perm is None:
                continue
            if bool(raw.get(col)):
                next_state[perm.id] = RoleCapability.STATE_ALLOW
                grid_allow_ids.add(perm.id)
            else:
                next_state.pop(perm.id, None)

    # Authoritative Deny set
    if deny_permission_ids is not None:
        deny_ids = set()
        for raw in deny_permission_ids:
            try:
                deny_ids.add(int(raw))
            except (TypeError, ValueError):
                continue
    else:
        deny_ids = _parse_deny_ids(advanced_denies)

    if deny_ids is None:
        # Preserve existing denies (except those the grid just Allowed — treat
        # an explicit View/Add/Edit/Delete tick as clearing Deny on this role).
        for pid, st in existing.items():
            if st == RoleCapability.STATE_DENY and pid not in grid_allow_ids:
                next_state[pid] = RoleCapability.STATE_DENY
    else:
        # Deny wins on this role for every listed permission.
        valid_deny = set(
            Permission.objects.filter(id__in=deny_ids).values_list("id", flat=True)
        )
        for pid in valid_deny:
            next_state[pid] = RoleCapability.STATE_DENY

    entries = [
        {"permission_id": pid, "state": st} for pid, st in next_state.items()
    ]
    replace_group_capabilities(group, entries)
    return build_service_matrix(group)
