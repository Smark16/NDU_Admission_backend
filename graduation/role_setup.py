"""Predefined graduation Django groups."""

GRADUATION_OFFICER_GROUP = "Graduation Officer"

GRADUATION_ROLE_MATRIX = {
    GRADUATION_OFFICER_GROUP: [
        ("accounts", "access_graduation"),
        ("graduation", "view_qualified_lists"),
        ("graduation", "manage_ceremonies"),
        ("graduation", "assign_students"),
        ("graduation", "view_graduation_lists"),
    ],
    "Graduation Viewer": [
        ("accounts", "access_graduation"),
        ("graduation", "view_qualified_lists"),
        ("graduation", "view_graduation_lists"),
    ],
}


def get_permission(Permission, app_label: str, codename: str):
    perm = Permission.objects.filter(
        content_type__app_label=app_label, codename=codename
    ).first()
    if perm:
        return perm
    return Permission.objects.filter(codename=codename).first()


def seed_all_graduation_roles(Group, Permission, *, stdout=None):
    for group_name, perms in GRADUATION_ROLE_MATRIX.items():
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
