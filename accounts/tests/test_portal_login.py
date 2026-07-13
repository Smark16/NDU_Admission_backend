from types import SimpleNamespace
from unittest.mock import MagicMock

from django.test import SimpleTestCase
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

from accounts.portal_login import (
    assert_session_allowed_on_portal,
    assert_user_allowed_on_portal,
    infer_portal_kind_from_request,
)


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

    def test_infers_admissions_from_origin_without_portal_body(self):
        request = MagicMock()
        request.headers = {"Origin": "https://admissions.ndu.ac.ug"}
        self.assertEqual(infer_portal_kind_from_request(request), "admissions")

        user = SimpleNamespace(
            is_staff=True,
            is_student=False,
            is_lecturer=False,
            is_superuser=False,
            is_applicant=False,
        )
        with self.assertRaises(AuthenticationFailed):
            assert_user_allowed_on_portal(user, None, request=request)

    def test_session_blocks_staff_on_admissions_origin(self):
        request = MagicMock()
        request.headers = {"Origin": "https://admissions.ndu.ac.ug"}
        user = SimpleNamespace(
            is_staff=True,
            is_student=False,
            is_lecturer=False,
            is_superuser=False,
            is_applicant=False,
        )
        with self.assertRaises(PermissionDenied):
            assert_session_allowed_on_portal(user, request)
