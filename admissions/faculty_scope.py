"""Faculty- and department-scoped access for staff (Dean, Faculty Admin, HOD).

Users may hold multiple roles (e.g. AR Data Clerk + Faculty Admin). Admissions
work uses institution-wide access when the user has edit permissions; programme
/timetable/enrollment work stays faculty-scoped when they hold a faculty role.

Heads of Department (HOD group, without Faculty Dean / Faculty Admin) are further
limited to programmes owned by the academic departments they head
(``AcademicDepartment.head_of_department`` â†’ ``Program.department``).
Faculty Dean and Faculty Admin remain faculty-wide.
"""
from __future__ import annotations

from django.db.models import Q, QuerySet

from accounts.super_admin import user_is_super_admin

FACULTY_SCOPED_ROLE_NAMES = frozenset({"Faculty Dean", "Faculty Admin", "HOD"})
ADMISSIONS_VIEW_ONLY_ROLE_NAMES = frozenset({"Faculty Dean", "Faculty Admin", "HOD"})
FACULTY_ASSIGNED_ROLE_NAMES = frozenset({"Faculty Dean", "Faculty Admin", "HOD"})

INSTITUTION_WIDE_ADMISSIONS_PERMS = (
    "admissions.change_application",
    "admissions.add_application",
    "accounts.manage_direct_applications",
    "admissions.change_admittedstudent",
    "admissions.add_admittedstudent",
)


def user_has_group(user, role_name: str) -> bool:
    return user.groups.filter(name__iexact=role_name).exists()


def user_has_institution_wide_admissions_access(user) -> bool:
    if not user.is_authenticated or user_is_super_admin(user):
        return user_is_super_admin(user)
    return any(user.has_perm(perm) for perm in INSTITUTION_WIDE_ADMISSIONS_PERMS)


def user_is_faculty_scoped_staff(user) -> bool:
    if not user.is_authenticated or user_is_super_admin(user):
        return False
    # Case-insensitive so Faculty Admin / Faculty Dean / HOD always stay faculty-scoped.
    return user.groups.filter(
        Q(name__iexact="Faculty Dean") | Q(name__iexact="Faculty Admin") | Q(name__iexact="HOD")
    ).exists()


def user_requires_faculty_scope(user, *, context: str = "programs") -> bool:
    if not user.is_authenticated or user_is_super_admin(user):
        return False
    if context == "admissions" and user_has_institution_wide_admissions_access(user):
        return False
    if user_is_faculty_scoped_staff(user):
        return True
    return context == "programs" and user.faculties.exists()


def user_is_admissions_view_only(user) -> bool:
    """Faculty Dean / Faculty Admin without institution-wide admissions edit access."""
    if not user.is_authenticated or user_is_super_admin(user):
        return False
    if user_has_institution_wide_admissions_access(user):
        return False
    return user.groups.filter(name__in=ADMISSIONS_VIEW_ONLY_ROLE_NAMES).exists()


def assert_admissions_modify_access(user) -> None:
    """Block view-only admissions roles from create/update/delete actions."""
    from rest_framework.exceptions import PermissionDenied

    if user_is_admissions_view_only(user):
        raise PermissionDenied(
            "You have view-only admissions access and cannot change or delete records."
        )


def user_faculty_ids(user, *, context: str = "programs") -> list[int] | None:
    """
    Faculty ids the user may access.

    ``None`` = unrestricted (superuser or not faculty-scoped for this context).
    ``[]`` = scoped role but no faculties assigned yet (no access).
    """
    if not user.is_authenticated or user_is_super_admin(user):
        return None
    if not user_requires_faculty_scope(user, context=context):
        return None
    return list(user.faculties.filter(is_active=True).values_list("pk", flat=True))


def user_is_hod(user) -> bool:
    if not user.is_authenticated or user_is_super_admin(user):
        return False
    return user_has_group(user, "HOD")


def user_is_faculty_dean(user) -> bool:
    if not user.is_authenticated or user_is_super_admin(user):
        return False
    return user_has_group(user, "Faculty Dean")


def user_is_faculty_admin(user) -> bool:
    if not user.is_authenticated or user_is_super_admin(user):
        return False
    return user_has_group(user, "Faculty Admin")


def user_requires_department_scope(user) -> bool:
    """
    Pure HoDs (HOD group without Faculty Dean / Faculty Admin) are limited to
    the academic departments they head. Deans and Faculty Admins stay faculty-wide.
    """
    if not user.is_authenticated or user_is_super_admin(user):
        return False
    if not user_is_hod(user):
        return False
    if user_is_faculty_dean(user) or user_is_faculty_admin(user):
        return False
    return True


def user_headed_department_ids(user) -> list[int] | None:
    """
    Academic department ids an HOD may access.

    ``None`` = do not apply department narrowing.
    ``[]`` = department-scoped HOD with no head assignment (no access).
    ``[ids]`` = restrict to these departments' programmes.
    """
    if not user_requires_department_scope(user):
        return None
    return list(
        user.headed_academic_departments.filter(is_active=True).values_list("pk", flat=True)
    )


def _apply_department_scope_to_programs(queryset: QuerySet, user, *, program_field: str = "") -> QuerySet:
    """
    Narrow a queryset to programmes owned by departments the user heads.

    ``program_field`` is the ORM path to Program, e.g. ``""`` (queryset is Program),
    ``"admitted_program"``, ``"program"``, ``"program_batch__program"``.
    """
    dept_ids = user_headed_department_ids(user)
    if dept_ids is None:
        return queryset
    if not dept_ids:
        return queryset.none()
    prefix = f"{program_field}__" if program_field else ""
    return queryset.filter(**{f"{prefix}department_id__in": dept_ids})


def filter_applications_for_user(queryset: QuerySet, user) -> QuerySet:
    faculty_ids = user_faculty_ids(user, context="admissions")
    if faculty_ids is None:
        return queryset
    if not faculty_ids:
        return queryset.none()
    queryset = queryset.filter(
        program_choices__program__faculty_id__in=faculty_ids
    ).distinct()
    dept_ids = user_headed_department_ids(user)
    if dept_ids is None:
        return queryset
    if not dept_ids:
        return queryset.none()
    return queryset.filter(
        program_choices__program__department_id__in=dept_ids
    ).distinct()


def filter_admitted_students_for_user(queryset: QuerySet, user) -> QuerySet:
    faculty_ids = user_faculty_ids(user, context="admissions")
    if faculty_ids is not None:
        if not faculty_ids:
            return queryset.none()
        queryset = queryset.filter(admitted_program__faculty_id__in=faculty_ids)

    queryset = _apply_department_scope_to_programs(
        queryset, user, program_field="admitted_program"
    )

    # Campus scope for non-finance staff who have campuses assigned.
    # Bursar / Finance see every campus; faculty-scoped staff may also be
    # limited to their assigned campuses when set.
    from accounts.finance_access import user_is_finance_directory_unscoped
    from accounts.super_admin import user_is_super_admin as _is_sa

    if _is_sa(user) or user_is_finance_directory_unscoped(user):
        return queryset
    if user_has_institution_wide_admissions_access(user):
        return queryset

    try:
        campus_ids = list(user.campuses.values_list("pk", flat=True))
    except Exception:
        campus_ids = []
    if campus_ids:
        queryset = queryset.filter(admitted_campus_id__in=campus_ids)
    return queryset


def filter_faculties_for_user(queryset: QuerySet, user) -> QuerySet:
    faculty_ids = user_faculty_ids(user, context="programs")
    if faculty_ids is None:
        return queryset
    if not faculty_ids:
        return queryset.none()
    return queryset.filter(pk__in=faculty_ids)


def filter_admission_change_requests_for_user(queryset: QuerySet, user) -> QuerySet:
    # Finance bills exemptions across all faculties/campuses.
    from accounts.finance_access import user_is_finance_directory_unscoped

    if user_is_super_admin(user) or user_is_finance_directory_unscoped(user):
        return queryset

    faculty_ids = user_faculty_ids(user, context="admissions")
    if faculty_ids is None:
        return queryset
    if not faculty_ids:
        return queryset.none()
    queryset = queryset.filter(
        Q(admitted_student__admitted_program__faculty_id__in=faculty_ids)
        | Q(current_program__faculty_id__in=faculty_ids)
        | Q(new_program__faculty_id__in=faculty_ids)
    ).distinct()

    dept_ids = user_headed_department_ids(user)
    if dept_ids is None:
        return queryset
    if not dept_ids:
        return queryset.none()
    # HoD sees exemptions / change requests for programmes in their department only.
    return queryset.filter(
        Q(admitted_student__admitted_program__department_id__in=dept_ids)
        | Q(current_program__department_id__in=dept_ids)
        | Q(new_program__department_id__in=dept_ids)
    ).distinct()


def user_can_access_application(user, application) -> bool:
    faculty_ids = user_faculty_ids(user, context="admissions")
    if faculty_ids is None:
        return True
    if not faculty_ids:
        return False
    choices = application.program_choices.filter(program__faculty_id__in=faculty_ids)
    dept_ids = user_headed_department_ids(user)
    if dept_ids is not None:
        if not dept_ids:
            return False
        choices = choices.filter(program__department_id__in=dept_ids)
    return choices.exists()


def user_can_access_admitted_student(user, admitted) -> bool:
    faculty_ids = user_faculty_ids(user, context="admissions")
    if faculty_ids is not None:
        if not faculty_ids:
            return False
        prog = getattr(admitted, "admitted_program", None)
        if prog is None or not prog.faculty_id:
            return False
        if prog.faculty_id not in faculty_ids:
            return False

    dept_ids = user_headed_department_ids(user)
    if dept_ids is not None:
        if not dept_ids:
            return False
        prog = getattr(admitted, "admitted_program", None)
        if prog is None or prog.department_id not in dept_ids:
            return False

    from accounts.finance_access import user_is_finance_directory_unscoped
    from accounts.super_admin import user_is_super_admin as _is_sa

    if _is_sa(user) or user_is_finance_directory_unscoped(user):
        return True
    if user_has_institution_wide_admissions_access(user):
        return True

    try:
        campus_ids = list(user.campuses.values_list("pk", flat=True))
    except Exception:
        campus_ids = []
    if campus_ids:
        campus_id = getattr(admitted, "admitted_campus_id", None)
        if campus_id not in campus_ids:
            return False
    return True


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
            "You can only access admitted students in your assigned faculty, department, or campus."
        )


def filter_programs_for_user(queryset: QuerySet, user) -> QuerySet:
    faculty_ids = user_faculty_ids(user, context="programs")
    if faculty_ids is None:
        return queryset
    if not faculty_ids:
        return queryset.none()
    queryset = queryset.filter(faculty_id__in=faculty_ids)
    return _apply_department_scope_to_programs(queryset, user)


def filter_programme_enrollments_for_user(queryset: QuerySet, user) -> QuerySet:
    faculty_ids = user_faculty_ids(user, context="programs")
    if faculty_ids is None:
        return queryset
    if not faculty_ids:
        return queryset.none()
    queryset = queryset.filter(program__faculty_id__in=faculty_ids)
    return _apply_department_scope_to_programs(queryset, user, program_field="program")


def assert_program_in_user_faculties(user, program) -> None:
    from rest_framework.exceptions import PermissionDenied

    faculty_ids = user_faculty_ids(user, context="programs")
    if faculty_ids is None:
        return
    if not faculty_ids:
        raise PermissionDenied("No faculty assigned to your account.")
    faculty_id = getattr(program, "faculty_id", None)
    if faculty_id not in faculty_ids:
        raise PermissionDenied(
            "You can only access programmes in your assigned faculty."
        )
    dept_ids = user_headed_department_ids(user)
    if dept_ids is not None:
        if not dept_ids:
            raise PermissionDenied(
                "No academic department is assigned to you as Head of Department."
            )
        if getattr(program, "department_id", None) not in dept_ids:
            raise PermissionDenied(
                "You can only access programmes in your assigned department."
            )


def assert_program_batch_access(user, program_batch) -> None:
    assert_program_in_user_faculties(user, program_batch.program)


def assert_semester_access(user, semester) -> None:
    assert_program_batch_access(user, semester.program_batch)


def assert_course_unit_access(user, course_unit) -> None:
    program_batch = getattr(course_unit, "program_batch", None)
    if program_batch is None:
        semester = getattr(course_unit, "semester", None)
        program_batch = getattr(semester, "program_batch", None) if semester is not None else None
    if program_batch is None:
        from rest_framework.exceptions import PermissionDenied

        raise PermissionDenied("Course unit is not linked to a programme batch.")
    assert_program_batch_access(user, program_batch)


def filter_course_units_for_user(queryset: QuerySet, user) -> QuerySet:
    """Limit course units to the user's assigned faculties (and HOD department)."""
    faculty_ids = user_faculty_ids(user, context="programs")
    if faculty_ids is None:
        return queryset
    if not faculty_ids:
        return queryset.none()
    queryset = queryset.filter(
        Q(program_batch__program__faculty_id__in=faculty_ids)
        | Q(semester__program_batch__program__faculty_id__in=faculty_ids)
    ).distinct()
    dept_ids = user_headed_department_ids(user)
    if dept_ids is None:
        return queryset
    if not dept_ids:
        return queryset.none()
    return queryset.filter(
        Q(program_batch__program__department_id__in=dept_ids)
        | Q(semester__program_batch__program__department_id__in=dept_ids)
    ).distinct()


def filter_lecture_attendance_sessions_for_user(queryset: QuerySet, user) -> QuerySet:
    faculty_ids = user_faculty_ids(user, context="programs")
    if faculty_ids is None:
        return queryset
    if not faculty_ids:
        return queryset.none()
    queryset = queryset.filter(
        Q(course_unit__program_batch__program__faculty_id__in=faculty_ids)
        | Q(course_unit__semester__program_batch__program__faculty_id__in=faculty_ids)
    ).distinct()
    dept_ids = user_headed_department_ids(user)
    if dept_ids is None:
        return queryset
    if not dept_ids:
        return queryset.none()
    return queryset.filter(
        Q(course_unit__program_batch__program__department_id__in=dept_ids)
        | Q(course_unit__semester__program_batch__program__department_id__in=dept_ids)
    ).distinct()


def assert_timetable_session_access(user, session) -> None:
    assert_course_unit_access(user, session.course_unit)


def assert_student_programme_enrollment_access(user, enrollment) -> None:
    assert_program_in_user_faculties(user, enrollment.program)


def assert_course_unit_enrollment_access(user, enrollment) -> None:
    assert_course_unit_access(user, enrollment.course_unit)


def assert_admitted_student_program_access(user, student) -> None:
    from rest_framework.exceptions import PermissionDenied

    faculty_ids = user_faculty_ids(user, context="programs")
    if faculty_ids is None:
        return
    if not faculty_ids:
        raise PermissionDenied("No faculty assigned to your account.")
    program = getattr(student, "admitted_program", None)
    if program is None or program.faculty_id not in faculty_ids:
        raise PermissionDenied(
            "You can only manage students in programmes for your assigned faculty."
        )
    dept_ids = user_headed_department_ids(user)
    if dept_ids is not None:
        if not dept_ids:
            raise PermissionDenied(
                "No academic department is assigned to you as Head of Department."
            )
        if program.department_id not in dept_ids:
            raise PermissionDenied(
                "You can only manage students in programmes for your assigned department."
            )


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
    faculty_ids = user_faculty_ids(user, context="programs")
    if faculty_ids is None:
        return queryset
    if not faculty_ids:
        return queryset.none()
    queryset = queryset.filter(program__faculty_id__in=faculty_ids)
    return _apply_department_scope_to_programs(queryset, user, program_field="program")


def user_can_access_program_batch(user, program_batch) -> bool:
    """Non-raising counterpart to ``assert_program_batch_access``."""
    faculty_ids = user_faculty_ids(user, context="programs")
    if faculty_ids is None:
        return True
    if not faculty_ids:
        return False
    if getattr(program_batch, "program_id", None) is None:
        return False
    if program_batch.program.faculty_id not in faculty_ids:
        return False
    dept_ids = user_headed_department_ids(user)
    if dept_ids is not None:
        if not dept_ids:
            return False
        return program_batch.program.department_id in dept_ids
    return True


def user_can_access_course_unit(user, course_unit) -> bool:
    """Non-raising counterpart to ``assert_course_unit_access``."""
    faculty_ids = user_faculty_ids(user, context="programs")
    if faculty_ids is None:
        return True
    if not faculty_ids:
        return False
    program_batch = getattr(course_unit, "program_batch", None)
    if program_batch is None:
        semester = getattr(course_unit, "semester", None)
        program_batch = getattr(semester, "program_batch", None) if semester is not None else None
    if program_batch is None:
        return False
    return user_can_access_program_batch(user, program_batch)


# â”€â”€ Examinations faculty scoping (exam sessions, results, retakes) â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Exam data hangs off Programs.CourseUnit, so it follows the same dual
# program_batch / semester->program_batch path as filter_course_units_for_user.

def filter_exam_sessions_for_user(queryset: QuerySet, user) -> QuerySet:
    faculty_ids = user_faculty_ids(user, context="programs")
    if faculty_ids is None:
        return queryset
    if not faculty_ids:
        return queryset.none()
    queryset = queryset.filter(
        Q(course_unit__program_batch__program__faculty_id__in=faculty_ids)
        | Q(course_unit__semester__program_batch__program__faculty_id__in=faculty_ids)
    ).distinct()
    dept_ids = user_headed_department_ids(user)
    if dept_ids is None:
        return queryset
    if not dept_ids:
        return queryset.none()
    return queryset.filter(
        Q(course_unit__program_batch__program__department_id__in=dept_ids)
        | Q(course_unit__semester__program_batch__program__department_id__in=dept_ids)
    ).distinct()


def filter_course_unit_results_for_user(queryset: QuerySet, user) -> QuerySet:
    faculty_ids = user_faculty_ids(user, context="programs")
    if faculty_ids is None:
        return queryset
    if not faculty_ids:
        return queryset.none()
    queryset = queryset.filter(
        Q(enrollment__course_unit__program_batch__program__faculty_id__in=faculty_ids)
        | Q(enrollment__course_unit__semester__program_batch__program__faculty_id__in=faculty_ids)
    ).distinct()
    dept_ids = user_headed_department_ids(user)
    if dept_ids is None:
        return queryset
    if not dept_ids:
        return queryset.none()
    return queryset.filter(
        Q(enrollment__course_unit__program_batch__program__department_id__in=dept_ids)
        | Q(enrollment__course_unit__semester__program_batch__program__department_id__in=dept_ids)
    ).distinct()


def filter_retake_registrations_for_user(queryset: QuerySet, user) -> QuerySet:
    faculty_ids = user_faculty_ids(user, context="programs")
    if faculty_ids is None:
        return queryset
    if not faculty_ids:
        return queryset.none()
    queryset = queryset.filter(
        Q(enrollment__course_unit__program_batch__program__faculty_id__in=faculty_ids)
        | Q(enrollment__course_unit__semester__program_batch__program__faculty_id__in=faculty_ids)
    ).distinct()
    dept_ids = user_headed_department_ids(user)
    if dept_ids is None:
        return queryset
    if not dept_ids:
        return queryset.none()
    return queryset.filter(
        Q(enrollment__course_unit__program_batch__program__department_id__in=dept_ids)
        | Q(enrollment__course_unit__semester__program_batch__program__department_id__in=dept_ids)
    ).distinct()


def filter_marks_entry_windows_for_user(queryset: QuerySet, user) -> QuerySet:
    faculty_ids = user_faculty_ids(user, context="programs")
    if faculty_ids is None:
        return queryset
    if not faculty_ids:
        return queryset.none()
    queryset = queryset.filter(program_batch__program__faculty_id__in=faculty_ids)
    return _apply_department_scope_to_programs(
        queryset, user, program_field="program_batch__program"
    )
