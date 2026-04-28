from django.contrib.auth.backends import ModelBackend
from django.db.models import Q
from .models import User


class StudentIdBackend(ModelBackend):
    """Authenticate by email, username, student_id, or reg_no."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None
        try:
            user = User.objects.get(
                Q(email__iexact=username) |
                Q(username__iexact=username)
            )
        except User.DoesNotExist:
            return None
        except User.MultipleObjectsReturned:
            user = User.objects.filter(email__iexact=username).first()
            if not user:
                return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
