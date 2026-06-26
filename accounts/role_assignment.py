"""Shared logic for assigning Django Groups (roles) to staff users."""
from __future__ import annotations

from django.contrib.auth.models import Group
from rest_framework import serializers

FACULTY_ASSIGNED_ROLE_NAMES = frozenset({"Faculty Dean", "Faculty Admin"})
LECTURER_ROLE_NAME = "Lecturer"
PORTAL_MODE_ADMIN = "admin"
PORTAL_MODE_LECTURER = "lecturer"
PORTAL_MODE_STUDENT = "student"
PORTAL_MODES = (PORTAL_MODE_ADMIN, PORTAL_MODE_LECTURER, PORTAL_MODE_STUDENT)


def role_requires_faculty_assignment(role_name: str) -> bool:
    return (role_name or "").strip().lower() in {
        name.lower() for name in FACULTY_ASSIGNED_ROLE_NAMES
    }


ADMISSIONS_STAFF_ROLE_NAMES = frozenset(
    {
        "Admissions Reviewer",
        "Admissions Approver",
        "Direct Admission Officer",
        "Document Verification Officer",
        "Admissions Reports Officer",
        "Student ID Officer",
        "AR Data Clerk",
        "Faculty Dean",
        "Faculty Admin",
    }
)


def get_staff_role_names() -> set[str]:
    names: set[str] = set(ADMISSIONS_STAFF_ROLE_NAMES)
    try:
        from accounts.erp_role_setup import ERP_STAFF_ROLE_NAMES

        names |= set(ERP_STAFF_ROLE_NAMES)
    except ImportError:
        pass
    try:
        from examinations.role_setup import EXAMINATION_STAFF_ROLE_NAMES

        names |= set(EXAMINATION_STAFF_ROLE_NAMES)
    except ImportError:
        pass
    try:
        from graduation.role_setup import GRADUATION_ROLE_MATRIX

        names |= set(GRADUATION_ROLE_MATRIX.keys())
    except ImportError:
        pass
    names.add(LECTURER_ROLE_NAME)
    names.add("Super Admin")
    return names


def _normalized_role_names(role_names: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in role_names:
        name = (raw or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(name)
    return cleaned


def user_has_non_lecturer_staff_group(user) -> bool:
    """True when the user belongs to any staff group other than Lecturer."""
    return user.groups.exclude(name__iexact=LECTURER_ROLE_NAME).exists()


def user_has_lecturer_group(user) -> bool:
    return user.groups.filter(name__iexact=LECTURER_ROLE_NAME).exists()


def user_has_admin_portal_access(user) -> bool:
    return user.groups.exclude(name__iexact=LECTURER_ROLE_NAME).exists()


def user_has_lecturer_portal_access(user) -> bool:
    if user_has_lecturer_group(user):
        return True
    if getattr(user, "is_lecturer", False):
        return True
    try:
        return user.course_units.exists()
    except Exception:
        return False


def user_has_student_portal_access(user) -> bool:
    return bool(getattr(user, "is_student", False))


def user_portal_modes(user) -> list[str]:
    modes: list[str] = []
    if user_has_admin_portal_access(user) and getattr(user, "is_staff", False):
        modes.append(PORTAL_MODE_ADMIN)
    if user_has_lecturer_portal_access(user):
        modes.append(PORTAL_MODE_LECTURER)
    if user_has_student_portal_access(user):
        modes.append(PORTAL_MODE_STUDENT)
    return modes


def resolve_portal_mode(user) -> str | None:
    modes = user_portal_modes(user)
    if not modes:
        return None
    stored = (getattr(user, "portal_mode", None) or "").strip().lower()
    if stored in modes:
        return stored
    if len(modes) == 1:
        return modes[0]
    for preferred in (PORTAL_MODE_ADMIN, PORTAL_MODE_LECTURER, PORTAL_MODE_STUDENT):
        if preferred in modes:
            return preferred
    return modes[0]


def primary_staff_role(user) -> str:
    name = (
        user.groups.exclude(name__iexact=LECTURER_ROLE_NAME)
        .order_by("name")
        .values_list("name", flat=True)
        .first()
    )
    return name or (user.role or "")


def active_role_label(user, portal_mode: str | None) -> str:
    if portal_mode == PORTAL_MODE_LECTURER:
        return LECTURER_ROLE_NAME
    if portal_mode == PORTAL_MODE_STUDENT:
        return "Student"
    label = primary_staff_role(user)
    return label or LECTURER_ROLE_NAME


def sync_user_role_flags(user, *, save: bool = True) -> list[str]:
    """Recalculate is_staff / is_lecturer from assigned groups and teaching assignments."""
    staff_names = {name.lower() for name in get_staff_role_names()}
    assigned = [g.lower() for g in user.groups.values_list("name", flat=True)]
    has_staff_role = any(name in staff_names for name in assigned)
    in_lecturer_group = user_has_lecturer_group(user)
    has_non_lecturer_group = user_has_non_lecturer_staff_group(user)

    has_course_units = False
    try:
        has_course_units = user.course_units.exists()
    except Exception:
        has_course_units = False

    is_lecturer = in_lecturer_group or has_course_units
    # Any non-Lecturer Django group is staff (covers custom roles such as AR Data Clerk).
    is_staff = has_staff_role or in_lecturer_group or has_non_lecturer_group

    update_fields: list[str] = []
    if user.is_staff != is_staff:
        user.is_staff = is_staff
        update_fields.append("is_staff")
    if user.is_lecturer != is_lecturer:
        user.is_lecturer = is_lecturer
        update_fields.append("is_lecturer")

    primary = primary_staff_role(user)
    if primary and user.role != primary:
        user.role = primary
        update_fields.append("role")

    if save and update_fields:
        user.save(update_fields=update_fields)
    return update_fields


def _promote_staff_portal_identity(user) -> list[str]:
    """
    Staff clerks/officers should land in the admin portal, not student/applicant.

    Lecturer-only accounts may keep is_student for dual student + lecturer portals.
    """
    update_fields: list[str] = []
    lecturer_only = user_has_lecturer_portal_access(user) and not user_has_non_lecturer_staff_group(user)
    if lecturer_only:
        return update_fields

    if not user.is_staff and not user_has_non_lecturer_staff_group(user):
        return update_fields

    if user.is_student:
        user.is_student = False
        update_fields.append("is_student")
    if user.is_applicant:
        user.is_applicant = False
        update_fields.append("is_applicant")

    modes = user_portal_modes(user)
    if not modes:
        return update_fields

    preferred = resolve_portal_mode(user)
    if preferred and user.portal_mode != preferred:
        user.portal_mode = preferred
        update_fields.append("portal_mode")
    elif user.portal_mode == PORTAL_MODE_STUDENT and PORTAL_MODE_ADMIN in modes:
        user.portal_mode = PORTAL_MODE_ADMIN
        update_fields.append("portal_mode")

    return update_fields


def set_user_roles(user, role_names: list[str]):
    """Replace all role groups with the given set and sync portal flags."""
    cleaned = _normalized_role_names(role_names)
    if not cleaned:
        raise serializers.ValidationError({"roles": "At least one role is required."})

    groups = []
    for name in cleaned:
        try:
            groups.append(Group.objects.get(name=name))
        except Group.DoesNotExist as exc:
            raise serializers.ValidationError(
                {"roles": f'Role "{name}" does not exist.'}
            ) from exc

    user.groups.set(groups)
    sync_user_role_flags(user, save=False)

    primary = primary_staff_role(user)
    if primary:
        user.role = primary
    elif LECTURER_ROLE_NAME in cleaned:
        user.role = LECTURER_ROLE_NAME

    update_fields = ["role", "is_staff", "is_lecturer"]
    update_fields.extend(_promote_staff_portal_identity(user))

    user.save(update_fields=list(dict.fromkeys(update_fields)))
    return user


def assign_user_role(user, role_name: str, *, replace: bool = True):
    """Assign a role group to the user and sync role/is_staff/is_lecturer flags."""
    role_name = (role_name or "").strip()
    if not role_name:
        return user

    try:
        group = Group.objects.get(name=role_name)
    except Group.DoesNotExist as exc:
        raise serializers.ValidationError(
            {"role": f'Role "{role_name}" does not exist.'}
        ) from exc

    if replace:
        user.groups.set([group])
    else:
        user.groups.add(group)

    sync_user_role_flags(user, save=False)
    primary = primary_staff_role(user)
    user.role = primary or role_name
    update_fields = ["role", "is_staff", "is_lecturer"]
    update_fields.extend(_promote_staff_portal_identity(user))
    user.save(update_fields=list(dict.fromkeys(update_fields)))
    return user
