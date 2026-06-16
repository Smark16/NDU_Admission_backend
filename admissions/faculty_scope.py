"""Faculty-scoped access for staff (e.g. Faculty Dean, Faculty Admin).

Users in faculty-scoped roles only see data whose programme belongs to one of
their assigned faculties.
"""
from __future__ import annotations

from django.db.models import Q, QuerySet

from accounts.super_admin import user_is_super_admin

FACULTY_SCOPED_ROLE_NAMES = frozenset({"Faculty Dean", "Faculty Admin"})
ADMISSIONS_VIEW_ONLY_ROLE_NAMES = frozenset({"Faculty Dean", "Faculty Admin"})
FACULTY_ASSIGNED_ROLE_NAMES = frozenset({"Faculty Dean", "Faculty Admin"})


def user_requires_faculty_scope(user) -> bool:
    if not user.is_authenticated or user_is_super_admin(user):
        return False
    role = user.groups.first().name if user.groups.exists() else (user.role or "")
    if role in FACULTY_SCOPED_ROLE_NAMES:
        return True
    return user.faculties.exists()


def user_is_admissions_view_only(user) -> bool:
    """Faculty Dean / Faculty Admin: read admissions data only."""
    if not user.is_authenticated or user_is_super_admin(user):
        return False
    role = user.groups.first().name if user.groups.exists() else (user.role or "")
    return role in ADMISSIONS_VIEW_ONLY_ROLE_NAMES


def assert_admissions_modify_access(user) -> None:
    """Block view-only admissions roles from create/update/delete actions."""
    from rest_framework.exceptions import PermissionDenied

    if user_is_admissions_view_only(user):
        raise PermissionDenied(
            "You have view-only admissions access and cannot change or delete records."
        )


def user_faculty_ids(user) -> list[int] | None:
    """
    Faculty ids the user may access.

    ``None`` = unrestricted (superuser or not faculty-scoped).
    ``[]`` = scoped role but no faculties assigned yet (no access).
    """
    if not user.is_authenticated or user_is_super_admin(user):
        return None
    if not user_requires_faculty_scope(user):
        return None
    return list(user.faculties.filter(is_active=True).values_list("pk", flat=True))


def filter_applications_for_user(queryset: QuerySet, user) -> QuerySet:
    faculty_ids = user_faculty_ids(user)
    if faculty_ids is None:
        return queryset
    if not faculty_ids:
        return queryset.none()
    return queryset.filter(
        program_choices__program__faculty_id__in=faculty_ids
    ).distinct()


def filter_admitted_students_for_user(queryset: QuerySet, user) -> QuerySet:
    faculty_ids = user_faculty_ids(user)
    if faculty_ids is None:
        return queryset
    if not faculty_ids:
        return queryset.none()
    return queryset.filter(admitted_program__faculty_id__in=faculty_ids)


def filter_faculties_for_user(queryset: QuerySet, user) -> QuerySet:
    faculty_ids = user_faculty_ids(user)
    if faculty_ids is None:
        return queryset
    if not faculty_ids:
        return queryset.none()
    return queryset.filter(pk__in=faculty_ids)


def filter_admission_change_requests_for_user(queryset: QuerySet, user) -> QuerySet:
    faculty_ids = user_faculty_ids(user)
    if faculty_ids is None:
        return queryset
    if not faculty_ids:
        return queryset.none()
    return queryset.filter(
        Q(admitted_student__admitted_program__faculty_id__in=faculty_ids)
        | Q(current_program__faculty_id__in=faculty_ids)
        | Q(new_program__faculty_id__in=faculty_ids)
    ).distinct()


def user_can_access_application(user, application) -> bool:
    faculty_ids = user_faculty_ids(user)
    if faculty_ids is None:
        return True
    if not faculty_ids:
        return False
    return application.program_choices.filter(
        program__faculty_id__in=faculty_ids
    ).exists()


def user_can_access_admitted_student(user, admitted) -> bool:
    faculty_ids = user_faculty_ids(user)
    if faculty_ids is None:
        return True
    if not faculty_ids:
        return False
    prog = getattr(admitted, "admitted_program", None)
    if prog is None or not prog.faculty_id:
        return False
    return prog.faculty_id in faculty_ids


def assert_application_access(user, application) -> None:
    from rest_framework.exceptions import PermissionDenied

    if not user_can_access_application(user, application):
        raise PermissionDenied(
            "You can only access applications for programmes in your assigned faculty."
        )


def assert_admitted_student_access(user, admitted) -> None:
    from rest_framework.exceptions import PermissionDenied

    if not user_can_access_admitted_student(user, admitted):
        raise PermissionDenied(
            "You can only access admitted students in your assigned faculty."
        )


def filter_programs_for_user(queryset: QuerySet, user) -> QuerySet:
    faculty_ids = user_faculty_ids(user)
    if faculty_ids is None:
        return queryset
    if not faculty_ids:
        return queryset.none()
    return queryset.filter(faculty_id__in=faculty_ids)


def filter_programme_enrollments_for_user(queryset: QuerySet, user) -> QuerySet:
    faculty_ids = user_faculty_ids(user)
    if faculty_ids is None:
        return queryset
    if not faculty_ids:
        return queryset.none()
    return queryset.filter(program__faculty_id__in=faculty_ids)


def assert_program_in_user_faculties(user, program) -> None:
    from rest_framework.exceptions import PermissionDenied

    faculty_ids = user_faculty_ids(user)
    if faculty_ids is None:
        return
    if not faculty_ids:
        raise PermissionDenied("No faculty assigned to your account.")
    faculty_id = getattr(program, "faculty_id", None)
    if faculty_id not in faculty_ids:
        raise PermissionDenied(
            "You can only access programmes in your assigned faculty."
        )


def assert_program_batch_access(user, program_batch) -> None:
    assert_program_in_user_faculties(user, program_batch.program)


def assert_semester_access(user, semester) -> None:
    assert_program_batch_access(user, semester.program_batch)


def assert_course_unit_access(user, course_unit) -> None:
    program_batch = getattr(course_unit, "program_batch", None)
    if program_batch is None:
        from rest_framework.exceptions import PermissionDenied

        raise PermissionDenied("Course unit is not linked to a programme batch.")
    assert_program_batch_access(user, program_batch)


def assert_timetable_session_access(user, session) -> None:
    assert_course_unit_access(user, session.course_unit)


def assert_student_programme_enrollment_access(user, enrollment) -> None:
    assert_program_in_user_faculties(user, enrollment.program)


def assert_course_unit_enrollment_access(user, enrollment) -> None:
    assert_course_unit_access(user, enrollment.course_unit)


def assert_admitted_student_program_access(user, student) -> None:
    from rest_framework.exceptions import PermissionDenied

    faculty_ids = user_faculty_ids(user)
    if faculty_ids is None:
        return
    if not faculty_ids:
        raise PermissionDenied("No faculty assigned to your account.")
    program = getattr(student, "admitted_program", None)
    if program is None or program.faculty_id not in faculty_ids:
        raise PermissionDenied(
            "You can only manage students in programmes for your assigned faculty."
        )


def user_is_faculty_dean(user) -> bool:
    if not user.is_authenticated or user_is_super_admin(user):
        return False
    role = user.groups.first().name if user.groups.exists() else (user.role or "")
    return role == "Faculty Dean"


def user_is_faculty_admin(user) -> bool:
    if not user.is_authenticated or user_is_super_admin(user):
        return False
    role = user.groups.first().name if user.groups.exists() else (user.role or "")
    return role == "Faculty Admin"


def assert_program_structure_modify_access(user) -> None:
    """Faculty Dean cannot modify programme structure; Faculty Admin may within assigned faculty."""
    from rest_framework.exceptions import PermissionDenied

    if user_is_faculty_dean(user):
        raise PermissionDenied(
            "You have view-only access and cannot create or modify programme structure."
        )


def assert_can_modify_program_structure(user, program) -> None:
    assert_program_structure_modify_access(user)
    assert_program_in_user_faculties(user, program)


def assert_can_modify_program_batch_structure(user, program_batch) -> None:
    assert_program_structure_modify_access(user)
    assert_program_batch_access(user, program_batch)


def filter_program_batches_for_user(queryset: QuerySet, user) -> QuerySet:
    faculty_ids = user_faculty_ids(user)
    if faculty_ids is None:
        return queryset
    if not faculty_ids:
        return queryset.none()
    return queryset.filter(program__faculty_id__in=faculty_ids)
