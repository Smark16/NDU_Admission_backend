"""HOD (Head of Department) role — faculty-scoped technical lead.

Combines: exemption request approval, exam publishing/scheduling/retakes,
and programme timetabling/enrollment — all scoped to the HOD's assigned
faculty (faculties assigned the same way as Faculty Dean / Faculty Admin).
"""

from admissions.faculty_dean_role_setup import get_permission

HOD_GROUP = "HOD"

HOD_PERMISSIONS = [
    # Same admissions visibility as Faculty Dean / Faculty Admin
    ("accounts", "access_admissions"),
    ("admissions", "view_application"),
    ("admissions", "view_admittedstudent"),
    # Exemption request review (Exemption Approver parity)
    ("accounts", "access_academics"),
    ("admissions", "view_admissionchangerequest"),
    ("admissions", "approve_exemption_requests"),
    ("Programs", "view_program"),
    # Timetables, batches, semesters, and course units within assigned faculty
    ("accounts", "manage_program_scheduling"),
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
    # Exam publishing, exam timetabling, and retakes
    ("accounts", "access_examinations"),
    ("examinations", "publish_results"),
    ("examinations", "view_all_results"),
    ("examinations", "manage_exam_schedule"),
    ("examinations", "manage_retakes"),
]


def seed_hod_role(Group, Permission, *, stdout=None):
    group, created = Group.objects.get_or_create(name=HOD_GROUP)
    target_perms = []
    for app_label, codename in HOD_PERMISSIONS:
        perm = get_permission(Permission, app_label, codename)
        if perm:
            target_perms.append(perm)
    group.permissions.set(target_perms)
    if stdout:
        action = "Created" if created else "Updated"
        stdout.write(f"{action} group {HOD_GROUP} ({len(target_perms)} permissions)")
    return group
