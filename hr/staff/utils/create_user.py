from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import transaction

from accounts.models import User
from accounts.role_assignment import sync_user_role_flags
from accounts.utils.passwords import generate_changeme_password

__all__ = ["create_user_for_staff", "generate_changeme_password"]


def create_user_for_staff(
    staff,
    initial_password=None,
    *,
    activate: bool = False,
    assign_role_groups: bool = False,
):
    """
    Create or link an ERP user for an HR staff profile (university email login).

    Staff-provisioned accounts are ALWAYS inactive unless activate=True.
    Admins assign roles in User Management, then activate (which emails credentials).
    """
    password = (initial_password or "").strip() or None
    if not password:
        password = generate_changeme_password()

    with transaction.atomic():
        email = (staff.university_email or "").lower().strip()
        if not email:
            raise ValidationError("University email is required to create a system login.")

        first_name = (staff.first_name or "").strip()
        last_name = (staff.last_name or "").strip()

        existing = User.objects.filter(username__iexact=email).first()
        created_new = False
        if existing:
            if getattr(staff, "user_id", None) and staff.user_id != existing.id:
                raise ValidationError("A user with this email already exists for another account.")
            user = existing
        else:
            # is_active=False at create — never rely on a later save alone.
            user = User.objects.create_user(
                username=email,
                email=email,
                first_name=first_name,
                last_name=last_name,
                is_active=False,
            )
            created_new = True

        user.set_password(password)
        user.must_change_password = True

        # Policy: HR onboarding / staff-form provisioning never leaves accounts active.
        # Only ChangeUserStatus (activate=True) or an explicit activate flag may flip this on.
        user.is_active = bool(activate)

        if staff.campus.exists():
            user.campuses.set(staff.campus.all())

        if staff.staff_no and not user.staff_id:
            user.staff_id = staff.staff_no

        user.is_staff = True
        user.is_applicant = False
        user.is_student = False
        user.save()

        if assign_role_groups:
            user.groups.add(Group.objects.get_or_create(name="Staff")[0])
            if staff.is_supervisor:
                user.groups.add(Group.objects.get_or_create(name="Supervisor")[0])
            if staff.is_hr:
                user.groups.add(Group.objects.get_or_create(name="HR")[0])

        sync_user_role_flags(user)

        # sync_user_role_flags must never undo inactive-until-admin policy
        if not activate and user.is_active:
            user.is_active = False
            user.save(update_fields=["is_active"])

        staff.user = user
        staff.save(update_fields=["user"])

    return user
