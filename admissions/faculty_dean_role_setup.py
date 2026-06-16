"""Faculty Dean role — read-only admissions visibility within assigned faculties."""

FACULTY_DEAN_GROUP = "Faculty Dean"

FACULTY_DEAN_PERMISSIONS = [
    ("accounts", "access_admissions"),
    ("admissions", "view_application"),
    ("admissions", "view_admittedstudent"),
]


def get_permission(Permission, app_label: str, codename: str):
    perm = Permission.objects.filter(
        content_type__app_label=app_label, codename=codename
    ).first()
    if perm:
        return perm
    return Permission.objects.filter(codename=codename).first()


def seed_faculty_dean_role(Group, Permission, *, stdout=None):
    group, created = Group.objects.get_or_create(name=FACULTY_DEAN_GROUP)
    target_perms = []
    for app_label, codename in FACULTY_DEAN_PERMISSIONS:
        perm = get_permission(Permission, app_label, codename)
        if perm:
            target_perms.append(perm)
    group.permissions.set(target_perms)
    if stdout:
        action = "Created" if created else "Updated"
        stdout.write(
            f"{action} group {FACULTY_DEAN_GROUP} ({len(target_perms)} view-only permissions)"
        )
