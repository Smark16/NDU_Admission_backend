"""Resolve / sync student photos used on ID cards and registration cards."""
from __future__ import annotations

from django.core.files.base import ContentFile


def _file_url(photo, request) -> str | None:
    if not photo or not getattr(photo, "name", None):
        return None
    try:
        url = photo.url
    except ValueError:
        return None
    if request is not None:
        return request.build_absolute_uri(url)
    return url


def admitted_student_photo_file(student):
    """ImageField to use for ID/exam PDF (profile photo first, else application)."""
    app = getattr(student, "application", None)
    user = getattr(student, "student_user", None) or getattr(student, "portal_user", None)
    if user is None and app is not None:
        user = getattr(app, "applicant", None)
    profile = getattr(user, "profile", None) if user is not None else None
    photo = getattr(profile, "profile_photo", None) if profile is not None else None
    if photo and getattr(photo, "name", None):
        return photo
    photo = getattr(app, "passport_photo", None) if app is not None else None
    if photo and getattr(photo, "name", None):
        return photo
    return None


def admitted_student_has_photo(student) -> bool:
    return admitted_student_photo_file(student) is not None


def admitted_student_photo_url(student, request=None) -> str | None:
    """Prefer the student's uploaded profile photo, else application passport photo."""
    return _file_url(admitted_student_photo_file(student), request)


def sync_profile_photo_to_application(user) -> bool:
    """Copy accounts.Profile.profile_photo onto the student's Application.passport_photo."""
    if user is None:
        return False
    profile = getattr(user, "profile", None)
    photo = getattr(profile, "profile_photo", None) if profile is not None else None
    if not photo or not getattr(photo, "name", None):
        return False

    from admissions.models import Application

    application = Application.objects.filter(applicant=user).order_by("-id").first()
    if application is None:
        return False

    filename = photo.name.rsplit("/", 1)[-1]
    photo.open("rb")
    try:
        payload = photo.read()
    finally:
        try:
            photo.close()
        except Exception:
            pass
    application.passport_photo.save(filename, ContentFile(payload), save=True)
    return True
