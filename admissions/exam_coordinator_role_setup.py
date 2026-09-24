"""Exam Coordinator role — department-scoped, notification-only.

Historically Exam Coordinators entered results on lecturers' behalf; the AR
office is phasing that out. Going forward their role is stage-1 oversight
only: they're CC'd (alongside the HOD) when a lecturer submits marks for
review, with no marks-entry or approval permissions of their own.

Scope: assign via ``AcademicDepartment.assign_exam_coordinator`` (Academic
Departments UI). That grants this group and the department's faculty.
"""

from admissions.faculty_dean_role_setup import get_permission

EXAM_COORDINATOR_GROUP = "Exam Coordinator"

EXAM_COORDINATOR_PERMISSIONS = [
    ("accounts", "access_examinations"),
    ("examinations", "view_all_results"),
]


def seed_exam_coordinator_role(Group, Permission, *, stdout=None):
    group, created = Group.objects.get_or_create(name=EXAM_COORDINATOR_GROUP)
    target_perms = []
    for app_label, codename in EXAM_COORDINATOR_PERMISSIONS:
        perm = get_permission(Permission, app_label, codename)
        if perm:
            target_perms.append(perm)
    group.permissions.set(target_perms)
    if stdout:
        action = "Created" if created else "Updated"
        stdout.write(
            f"{action} group {EXAM_COORDINATOR_GROUP} ({len(target_perms)} view-only permissions)"
        )
    return group
