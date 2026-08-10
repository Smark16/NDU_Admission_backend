"""Predefined hostel Django groups — hostel module only."""

DEAN_OF_STUDENTS_GROUP = "Dean of Students"
HOSTEL_MANAGER_GROUP = "Hostel Manager"
HOSTEL_VIEWER_GROUP = "Hostel Viewer"

# Day-to-day hostel operations only. Do NOT include admissions.view_admittedstudent
# (that unlocks the Students module in the admin sidebar).
_HOSTEL_OPS_PERMS = [
    ("accounts", "access_hostel"),
    ("hostel", "manage_hostel_inventory"),
    ("hostel", "assign_hostel"),
    ("hostel", "end_hostel_allocation"),
    ("hostel", "view_hostel_reports"),
    ("hostel", "view_hostel"),
    ("hostel", "view_building"),
    ("hostel", "view_floor"),
    ("hostel", "view_room"),
    ("hostel", "view_bed"),
    ("hostel", "view_hostelallocation"),
]

HOSTEL_ROLE_MATRIX = {
    # Senior / office role — same hostel ops as Hostel Manager.
    DEAN_OF_STUDENTS_GROUP: list(_HOSTEL_OPS_PERMS),
    # Operational role for staff who run halls of residence day to day.
    HOSTEL_MANAGER_GROUP: list(_HOSTEL_OPS_PERMS),
    HOSTEL_VIEWER_GROUP: [
        ("accounts", "access_hostel"),
        ("hostel", "view_hostel_reports"),
        ("hostel", "view_hostel"),
        ("hostel", "view_building"),
        ("hostel", "view_floor"),
        ("hostel", "view_room"),
        ("hostel", "view_bed"),
        ("hostel", "view_hostelallocation"),
    ],
}


def get_permission(Permission, app_label: str, codename: str):
    perm = Permission.objects.filter(
        content_type__app_label=app_label, codename=codename
    ).first()
    if perm:
        return perm
    return Permission.objects.filter(codename=codename).first()


def seed_all_hostel_roles(Group, Permission, *, stdout=None, sync=True):
    """
    Create/update hostel groups.

    sync=True (default): set each group's permissions exactly to the matrix
    (removes extras such as admissions.view_admittedstudent).
    sync=False: only add missing permissions (legacy additive behaviour).
    """
    for group_name, perms in HOSTEL_ROLE_MATRIX.items():
        group, created = Group.objects.get_or_create(name=group_name)
        desired = []
        for app_label, codename in perms:
            perm = get_permission(Permission, app_label, codename)
            if perm:
                desired.append(perm)
            elif stdout:
                stdout.write(f"  WARN missing permission: {app_label}.{codename}")

        if sync:
            before = set(group.permissions.values_list("id", flat=True))
            group.permissions.set(desired)
            after = {p.id for p in desired}
            added = len(after - before)
            removed = len(before - after)
            if stdout:
                verb = "Created" if created else "Synced"
                stdout.write(
                    f"{verb} group: {group_name} "
                    f"(+{added} / -{removed} permissions, total={len(desired)})"
                )
        else:
            added = 0
            for perm in desired:
                if not group.permissions.filter(pk=perm.pk).exists():
                    group.permissions.add(perm)
                    added += 1
            if stdout:
                verb = "Created" if created else "Updated"
                stdout.write(f"{verb} group: {group_name} (+{added} permissions)")
        try:
            from accounts.role_capabilities import sync_allows_from_group_m2m

            sync_allows_from_group_m2m(group)
        except Exception:
            pass
