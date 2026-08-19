"""Eligibility gates for student course-exemption applications."""
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from admissions.exemption_services import (
    exemption_ineligibility,
    exemption_paper_meets_min_mark,
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
    def test_registration_no_longer_required(self):
        student = _student(accounts=False, docs=False, year=1, term=1)
        self.assertIsNone(exemption_ineligibility(student)[0])
        self.assertTrue(student_may_apply_course_exemption(student))

    def test_min_mark_no_longer_required(self):
        ok, msg = exemption_paper_meets_min_mark({"course_code": "ABC", "score_obtained": "D (45)"})
        self.assertTrue(ok)
        self.assertEqual(msg, "")
