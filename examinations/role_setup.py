"""Django groups for the examinations module (full + lighter office roles)."""

EXAMINATION_MANAGER_GROUP = "Examination Manager"

# (group_name, list of (app_label, codename))
# Every office role includes accounts.access_examinations so the Exams menu appears.
EXAMINATION_ROLE_MATRIX = {
    EXAMINATION_MANAGER_GROUP: [
        ("accounts", "access_examinations"),
        ("examinations", "enter_marks"),
        ("examinations", "publish_results"),
        ("examinations", "view_all_results"),
        ("examinations", "manage_exam_schedule"),
        ("examinations", "manage_retakes"),
        ("examinations", "approve_result_changes"),
    ],
    "Examination Marks Officer": [
        ("accounts", "access_examinations"),
        ("examinations", "enter_marks"),
        ("examinations", "view_all_results"),
    ],
    "Examination Results Publisher": [
        ("accounts", "access_examinations"),
        ("examinations", "publish_results"),
        ("examinations", "view_all_results"),
    ],
    "Examination Timetable Officer": [
        ("accounts", "access_examinations"),
        ("examinations", "manage_exam_schedule"),
        ("examinations", "view_all_results"),
    ],
    "Examination Retakes Officer": [
        ("accounts", "access_examinations"),
        ("examinations", "manage_retakes"),
        ("examinations", "view_all_results"),
    ],
    "Examination Grade Reviewer": [
        ("accounts", "access_examinations"),
        ("examinations", "approve_result_changes"),
        ("examinations", "view_all_results"),
    ],
}

# Backward-compatible alias
EXAMINATION_MANAGER_PERMISSIONS = EXAMINATION_ROLE_MATRIX[EXAMINATION_MANAGER_GROUP]

# Staff portal roles (set is_staff on user register)
EXAMINATION_STAFF_ROLE_NAMES = frozenset(EXAMINATION_ROLE_MATRIX.keys())


def get_permission(Permission, app_label: str, codename: str):
    perm = Permission.objects.filter(
        content_type__app_label=app_label, codename=codename
    ).first()
    if perm:
        return perm
    return Permission.objects.filter(codename=codename).first()


def seed_examination_role_group(Group, Permission, group_name: str, *, stdout=None):
    """Create/update one examinations group from EXAMINATION_ROLE_MATRIX."""
    perms = EXAMINATION_ROLE_MATRIX.get(group_name)
    if not perms:
        raise ValueError(f"Unknown examinations role: {group_name}")

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
    return group


def seed_all_examination_roles(Group, Permission, *, stdout=None):
    """Create/update all predefined examinations groups."""
    groups = []
    for group_name in EXAMINATION_ROLE_MATRIX:
        groups.append(seed_examination_role_group(Group, Permission, group_name, stdout=stdout))
    return groups


def seed_examination_manager_group(Group, Permission, *, stdout=None):
    """Create/update the Examination Manager group (full permissions)."""
    return seed_examination_role_group(
        Group, Permission, EXAMINATION_MANAGER_GROUP, stdout=stdout
    )
