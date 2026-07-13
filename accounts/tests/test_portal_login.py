from types import SimpleNamespace

from django.test import SimpleTestCase
from rest_framework.exceptions import AuthenticationFailed

from accounts.portal_login import assert_user_allowed_on_portal


class PortalLoginGuardTests(SimpleTestCase):
    def test_staff_blocked_from_admissions(self):
        user = SimpleNamespace(
            is_staff=True,
            is_student=False,
            is_lecturer=False,
            is_superuser=False,
            is_applicant=False,
        )
        with self.assertRaises(AuthenticationFailed) as ctx:
            assert_user_allowed_on_portal(user, "admissions")
        self.assertIn("erp.ndejje.ndu.ac.ug", str(ctx.exception.detail))

    def test_applicant_allowed_on_admissions(self):
        user = SimpleNamespace(
            is_staff=False,
            is_student=False,
            is_lecturer=False,
            is_superuser=False,
            is_applicant=True,
        )
        assert_user_allowed_on_portal(user, "admissions")

    def test_applicant_blocked_from_erp(self):
        user = SimpleNamespace(
            is_staff=False,
            is_student=False,
            is_lecturer=False,
            is_superuser=False,
            is_applicant=True,
        )
        with self.assertRaises(AuthenticationFailed):
            assert_user_allowed_on_portal(user, "erp")

    def test_staff_allowed_on_erp(self):
        user = SimpleNamespace(
            is_staff=True,
            is_student=False,
            is_lecturer=False,
            is_superuser=False,
            is_applicant=False,
        )
        assert_user_allowed_on_portal(user, "erp")
