"""Faculty Admin role — faculty-scoped admissions view plus timetables and enrollment."""

from admissions.faculty_dean_role_setup import get_permission

FACULTY_ADMIN_GROUP = "Faculty Admin"

FACULTY_ADMIN_PERMISSIONS = [
    # Same admissions visibility as Faculty Dean
    ("accounts", "access_admissions"),
    ("admissions", "view_application"),
    ("admissions", "view_admittedstudent"),
    # Timetables, batches, semesters, and course units within assigned faculty
    ("accounts", "manage_program_scheduling"),
    ("Programs", "view_program"),
    ("Programs", "view_programbatch"),
    ("Programs", "add_programbatch"),
    ("Programs", "change_programbatch"),
    ("Programs", "delete_programbatch"),
    ("Programs", "view_semester"),
    ("Programs", "add_semester"),
    ("Programs", "change_semester"),
    ("Programs", "view_courseunit"),
    ("Programs", "add_courseunit"),
    ("Programs", "change_courseunit"),
    # Manual programme / course enrollment and unenrollment
    ("accounts", "manage_academic_enrollment"),
    ("Programs", "view_studentprogrammeenrollment"),
    ("Programs", "change_studentprogrammeenrollment"),
    ("Programs", "add_studentprogrammeenrollment"),
    ("Programs", "delete_studentprogrammeenrollment"),
    ("Programs", "view_studentcourseunitenrollment"),
    ("Programs", "change_studentcourseunitenrollment"),
    ("Programs", "add_studentcourseunitenrollment"),
    ("Programs", "delete_studentcourseunitenrollment"),
]


def seed_faculty_admin_role(Group, Permission, *, stdout=None):
    group, created = Group.objects.get_or_create(name=FACULTY_ADMIN_GROUP)
    target_perms = []
    for app_label, codename in FACULTY_ADMIN_PERMISSIONS:
        perm = get_permission(Permission, app_label, codename)
        if perm:
            target_perms.append(perm)
    group.permissions.set(target_perms)
    if stdout:
        action = "Created" if created else "Updated"
        stdout.write(
            f"{action} group {FACULTY_ADMIN_GROUP} ({len(target_perms)} permissions)"
        )
