"""Exemption year catalogue + curriculum version resolution helpers."""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from admissions.exemption_services import is_exemption_eligible_year
from Programs.curriculum_inheritance import resolve_curriculum_version_with_lines


class ExemptionEligibleYearTests(SimpleTestCase):
    def test_years_one_through_three(self):
        self.assertTrue(is_exemption_eligible_year(1))
        self.assertTrue(is_exemption_eligible_year(2))
        self.assertTrue(is_exemption_eligible_year(3))
        self.assertTrue(is_exemption_eligible_year("1"))
        self.assertTrue(is_exemption_eligible_year("3"))
        self.assertFalse(is_exemption_eligible_year(4))
        self.assertFalse(is_exemption_eligible_year(0))
        self.assertFalse(is_exemption_eligible_year(None))
        self.assertFalse(is_exemption_eligible_year("x"))


class CurriculumVersionWithLinesTests(SimpleTestCase):
    def test_prefers_pinned_when_owner_and_has_lines(self):
        owner = MagicMock()
        owner.id = 10
        program = MagicMock()
        pinned = MagicMock()
        pinned.program_id = 10
        pinned.lines.filter.return_value.exists.return_value = True

        with patch(
            "Programs.curriculum_inheritance.curriculum_owner_program",
            return_value=owner,
        ):
            result = resolve_curriculum_version_with_lines(
                program, batch=None, pinned=pinned
            )
        self.assertIs(result, pinned)

    def test_skips_empty_pin_and_uses_effective(self):
        owner = MagicMock()
        owner.id = 10
        program = MagicMock()
        empty_pin = MagicMock()
        empty_pin.program_id = 10
        empty_pin.lines.filter.return_value.exists.return_value = False
        effective = MagicMock()
        effective.program_id = 10
        effective.lines.filter.return_value.exists.return_value = True

        with patch(
            "Programs.curriculum_inheritance.curriculum_owner_program",
            return_value=owner,
        ), patch(
            "Programs.curriculum_inheritance.resolve_effective_curriculum_version",
            return_value=effective,
        ):
            result = resolve_curriculum_version_with_lines(
                program, batch=None, pinned=empty_pin
            )
        self.assertIs(result, effective)

    def test_skips_pin_on_wrong_programme(self):
        owner = MagicMock()
        owner.id = 10
        program = MagicMock()
        wrong_pin = MagicMock()
        wrong_pin.program_id = 99
        wrong_pin.lines.filter.return_value.exists.return_value = True
        effective = MagicMock()
        effective.program_id = 10
        effective.lines.filter.return_value.exists.return_value = True

        with patch(
            "Programs.curriculum_inheritance.curriculum_owner_program",
            return_value=owner,
        ), patch(
            "Programs.curriculum_inheritance.resolve_effective_curriculum_version",
            return_value=effective,
        ):
            result = resolve_curriculum_version_with_lines(
                program, batch=None, pinned=wrong_pin
            )
        self.assertIs(result, effective)
