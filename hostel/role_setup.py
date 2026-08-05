"""Predefined hostel Django groups."""

DEAN_OF_STUDENTS_GROUP = "Dean of Students"
HOSTEL_MANAGER_GROUP = "Hostel Manager"
HOSTEL_VIEWER_GROUP = "Hostel Viewer"

# Day-to-day hostel operations (inventory, assign/end, reports).
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
    ("admissions", "view_admittedstudent"),
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
        ("admissions", "view_admittedstudent"),
    ],
}


def get_permission(Permission, app_label: str, codename: str):
    perm = Permission.objects.filter(
        content_type__app_label=app_label, codename=codename
    ).first()
    if perm:
        return perm
    return Permission.objects.filter(codename=codename).first()


def seed_all_hostel_roles(Group, Permission, *, stdout=None):
    for group_name, perms in HOSTEL_ROLE_MATRIX.items():
        group, created = Group.objects.get_or_create(name=group_name)
        added = 0
        for app_label, codename in perms:
            perm = get_permission(Permission, app_label, codename)
            if perm and not group.permissions.filter(pk=perm.pk).exists():
                group.permissions.add(perm)
                added += 1
        if stdout:
            verb = "Created" if created else "Updated"
            stdout.write(f"{verb} group: {group_name} (+{added} permissions)")
