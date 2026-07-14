"""Keep accounts.User and hr.staff.StaffProfile in sync."""
from hr.staff.models import StaffProfile


def resolve_staff_profile_for_user(user):
    """
    Return the StaffProfile for a logged-in user, linking by email when possible.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return None

    try:
        profile = user.staff_profile
        if profile:
            return profile
    except StaffProfile.DoesNotExist:
        pass

    profile = StaffProfile.objects.filter(user=user).first()
    if profile:
        return profile

    email = (user.email or user.username or "").strip()
    if email:
        profile = StaffProfile.objects.filter(university_email__iexact=email).first()
        if profile:
            if not profile.user_id:
                profile.user = user
                profile.system_login = True
                profile.save(update_fields=["user", "system_login"])
            return profile

    if getattr(user, "is_staff", False):
        return ensure_staff_profile_for_user(user)

    return None


def ensure_staff_profile_for_user(user):
    """
    Create or link a StaffProfile when an ERP staff user exists.
    Called from User Management registration/update.
    """
    if not user or not getattr(user, "is_staff", False):
        return None

    try:
        profile = user.staff_profile
        if profile:
            updated = False
            if user.email and profile.university_email != user.email:
                profile.university_email = user.email
                updated = True
            if user.first_name and profile.first_name != user.first_name:
                profile.first_name = user.first_name
                updated = True
            if user.last_name and profile.last_name != user.last_name:
                profile.last_name = user.last_name
                updated = True
            if user.staff_id and profile.staff_no != user.staff_id:
                profile.staff_no = user.staff_id
                updated = True
            if updated:
                profile.save()
            if user.campuses.exists():
                profile.campus.set(user.campuses.all())
            return profile
    except StaffProfile.DoesNotExist:
        pass

    staff = StaffProfile.objects.create(
        user=user,
        first_name=user.first_name or "",
        last_name=user.last_name or "",
        university_email=user.email or user.username,
        staff_no=user.staff_id or "",
        system_login=True,
    )
    if user.campuses.exists():
        staff.campus.set(user.campuses.all())
    return staff
