from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import transaction

from accounts.models import User
from accounts.role_assignment import sync_user_role_flags


def create_user_for_staff(staff, initial_password=None):
    """Create or link an ERP user for an HR staff profile (university email login)."""
    with transaction.atomic():
        email = (staff.university_email or "").lower().strip()
        if not email:
            raise ValidationError("University email is required to create a system login.")

        first_name = (staff.first_name or "").strip()
        last_name = (staff.last_name or "").strip()
        password = (initial_password or "").strip() or None

        existing = User.objects.filter(username__iexact=email).first()
        if existing:
            if getattr(staff, "user_id", None) and staff.user_id != existing.id:
                raise ValidationError("A user with this email already exists for another account.")
            user = existing
        else:
            user = User.objects.create_user(
                username=email,
                email=email,
                first_name=first_name,
                last_name=last_name,
            )

        if password:
            user.set_password(password)
            user.is_active = True
            user.must_change_password = True
        elif not existing:
            user.set_unusable_password()
            user.is_active = False
            user.must_change_password = True

        if staff.campus.exists():
            user.campuses.set(staff.campus.all())

        if staff.staff_no and not user.staff_id:
            user.staff_id = staff.staff_no

        user.is_staff = True
        user.save()

        user.groups.add(Group.objects.get_or_create(name="Staff")[0])
        if staff.is_supervisor:
            user.groups.add(Group.objects.get_or_create(name="Supervisor")[0])
        if staff.is_hr:
            user.groups.add(Group.objects.get_or_create(name="HR")[0])

        sync_user_role_flags(user)

        staff.user = user
        staff.save(update_fields=["user"])

    return user
