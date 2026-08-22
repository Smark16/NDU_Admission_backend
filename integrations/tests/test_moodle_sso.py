from django.test import SimpleTestCase

from integrations.moodle_sso import (
    build_launch_profile_signature,
    build_launch_signature,
    build_moodle_sso_launch_url,
    split_full_name,
    verify_launch_profile_signature,
    verify_launch_signature,
)


class MoodleSsoTests(SimpleTestCase):
    def test_build_and_verify_launch_signature(self):
        secret = "ndu_moodle_test_secret"
        reg = "26/1/224/D/1174"
        exp = 1_700_000_000
        sig = build_launch_signature(reg_no=reg, exp=exp, secret=secret)
        self.assertEqual(len(sig), 64)
        self.assertTrue(
            verify_launch_signature(reg_no=reg, exp=exp, sig=sig, secret=secret, now=exp - 10)
        )
        self.assertFalse(
            verify_launch_signature(
                reg_no=reg, exp=exp, sig="deadbeef", secret=secret, now=exp - 10
            )
        )
        self.assertFalse(
            verify_launch_signature(reg_no=reg, exp=exp, sig=sig, secret=secret, now=exp + 1)
        )

    def test_build_moodle_sso_launch_url_shape(self):
        payload = build_moodle_sso_launch_url(
            base_url="https://nduels.ndu.ac.ug",
            reg_no="26/1/224/D/1174",
            secret="ndu_moodle_test_secret",
            ttl_seconds=90,
            now=1_700_000_000,
        )
        self.assertEqual(payload["exp"], 1_700_000_090)
        self.assertEqual(payload["ttl_seconds"], 90)
        self.assertTrue(
            payload["launch_url"].startswith("https://nduels.ndu.ac.ug/auth/ndu_erp/sso.php?")
        )
        self.assertIn("reg_no=26%2F1%2F224%2FD%2F1174", payload["launch_url"])
        self.assertIn("exp=1700000090", payload["launch_url"])
        self.assertIn("sig=", payload["launch_url"])

    def test_split_full_name(self):
        self.assertEqual(split_full_name("Jane Akello"), ("Jane", "Akello"))
        self.assertEqual(split_full_name("Jane"), ("Jane", "."))
        self.assertEqual(split_full_name(""), ("", ""))

    def test_launch_url_includes_signed_profile(self):
        payload = build_moodle_sso_launch_url(
            base_url="https://nduels.ndu.ac.ug",
            reg_no="26/1/224/D/1174",
            secret="ndu_moodle_test_secret",
            ttl_seconds=90,
            now=1_700_000_000,
            profile={
                "username": "26_1_224_D_1174",
                "firstname": "Jane",
                "lastname": "Akello",
                "email": "jane@example.com",
            },
        )
        self.assertIn("username=26_1_224_D_1174", payload["launch_url"])
        self.assertIn("firstname=Jane", payload["launch_url"])
        self.assertIn("lastname=Akello", payload["launch_url"])
        self.assertIn("psig=", payload["launch_url"])
        psig = build_launch_profile_signature(
            reg_no="26/1/224/D/1174",
            exp=payload["exp"],
            username="26_1_224_D_1174",
            firstname="Jane",
            lastname="Akello",
            email="jane@example.com",
            secret="ndu_moodle_test_secret",
        )
        self.assertTrue(
            verify_launch_profile_signature(
                reg_no="26/1/224/D/1174",
                exp=payload["exp"],
                username="26_1_224_D_1174",
                firstname="Jane",
                lastname="Akello",
                email="jane@example.com",
                psig=psig,
                secret="ndu_moodle_test_secret",
            )
        )
