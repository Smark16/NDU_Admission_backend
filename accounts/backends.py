from django.contrib.auth.backends import ModelBackend
from django.db.models import Q

from .models import User


class StudentIdBackend(ModelBackend):
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
