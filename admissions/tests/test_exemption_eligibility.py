"""Eligibility gates for student course-exemption applications."""
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from admissions.exemption_services import (
    EXEMPTION_DOCS_NOT_VERIFIED_CODE,
    EXEMPTION_NOT_REGISTERED_CODE,
    exemption_ineligibility,
    student_may_apply_course_exemption,
)


def _student(*, accounts=False, docs=False, year=1, term=1):
    student = MagicMock()
    student.accounts_registration_cleared = accounts
    student.physical_documents_verified = docs
    enrollment = MagicMock()
    enrollment.current_year_of_study = year
    enrollment.current_term_number = term
    student.programme_enrollment = enrollment
    return student


class ExemptionEligibilityTests(SimpleTestCase):
    def test_accounts_required_for_everyone(self):
        code, _ = exemption_ineligibility(_student(accounts=False, docs=True, year=2, term=1))
        self.assertEqual(code, EXEMPTION_NOT_REGISTERED_CODE)
        self.assertFalse(student_may_apply_course_exemption(_student(accounts=False)))

    def test_y1t1_requires_ar_docs(self):
        code, _ = exemption_ineligibility(_student(accounts=True, docs=False, year=1, term=1))
        self.assertEqual(code, EXEMPTION_DOCS_NOT_VERIFIED_CODE)

    def test_y1t1_ready_when_both_cleared(self):
        student = _student(accounts=True, docs=True, year=1, term=1)
        self.assertIsNone(exemption_ineligibility(student)[0])
        self.assertTrue(student_may_apply_course_exemption(student))

    def test_continuing_accounts_only(self):
        student = _student(accounts=True, docs=False, year=2, term=1)
        self.assertIsNone(exemption_ineligibility(student)[0])
        self.assertTrue(student_may_apply_course_exemption(student))
