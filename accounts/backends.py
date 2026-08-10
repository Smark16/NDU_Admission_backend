from django.contrib.auth.backends import ModelBackend
from django.db.models import Q

from .models import User


class DenyAwarePermissionMixin:
    """Subtract RoleCapability Deny rows from ModelBackend permission sets."""

    def get_all_permissions(self, user_obj, obj=None):
        perms = super().get_all_permissions(user_obj, obj)
        if not perms:
            return perms
        try:
            from accounts.role_capabilities import denied_permission_strings_for_user
            from accounts.super_admin import user_is_super_admin

            if user_is_super_admin(user_obj) or getattr(user_obj, "is_superuser", False):
                return perms
            denied = denied_permission_strings_for_user(user_obj)
            if not denied:
                return perms
            return perms - denied
        except Exception:
            return perms


class StudentIdBackend(DenyAwarePermissionMixin, ModelBackend):
    """Authenticate by email, portal username, registration number, or student ID."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None

        user = self._resolve_user(username)
        if user is None:
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

    def _resolve_user(self, username: str):
        ident = str(username).strip()
        if not ident:
            return None

        user = User.objects.filter(
            Q(email__iexact=ident) | Q(username__iexact=ident)
        ).first()
        if user:
            return user

        try:
            from admissions.models import AdmittedStudent
            from admissions.student_accounts import student_portal_username

            admission = (
                AdmittedStudent.objects.filter(
                    Q(reg_no__iexact=ident) | Q(student_id__iexact=ident)
                )
                .select_related("student_user")
                .first()
            )
            if admission:
                if admission.student_user_id:
                    return admission.student_user
                if admission.is_admitted:
                    try:
                        from admissions.student_accounts import ensure_student_portal_account

                        user, _created = ensure_student_portal_account(admission)
                        if user is not None:
                            return user
                    except Exception:
                        pass

            sanitized = student_portal_username(ident)
            if sanitized and sanitized.lower() != ident.lower():
                user = User.objects.filter(username__iexact=sanitized).first()
                if user:
                    return user

                admission = (
                    AdmittedStudent.objects.filter(reg_no__iexact=ident)
                    .select_related("student_user")
                    .first()
                )
                if admission and admission.student_user_id:
                    return admission.student_user
        except Exception:
            pass

        return None


class DenyAwareModelBackend(DenyAwarePermissionMixin, ModelBackend):
    """Default ModelBackend with role Deny support."""

    pass
