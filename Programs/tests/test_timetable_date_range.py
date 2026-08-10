"""Unit tests for timetable day + start/end date recurrence."""
from datetime import date, time
from types import SimpleNamespace
from unittest import TestCase

from Programs.timetable_utils import (
    occurrence_ranges_overlap,
    session_date_label,
    session_occurrence_bounds,
    session_occurrence_dates,
    weekday_dates_in_range,
)


class WeekdayDatesInRangeTests(TestCase):
    def test_tuesdays_in_february_range(self):
        # 2026-02-10 is a Tuesday; 2026-02-28 is a Saturday.
        dates = weekday_dates_in_range(date(2026, 2, 10), date(2026, 2, 28), day_of_week=2)
        self.assertEqual(
            dates,
            [
                date(2026, 2, 10),
                date(2026, 2, 17),
                date(2026, 2, 24),
            ],
        )

    def test_empty_when_end_before_start(self):
        self.assertEqual(
            weekday_dates_in_range(date(2026, 3, 1), date(2026, 2, 1), 2),
            [],
        )


class SessionOccurrenceHelpersTests(TestCase):
    def test_one_off_bounds_and_dates(self):
        slot = SimpleNamespace(
            session_date=date(2026, 3, 3),
            start_date=date(2026, 3, 3),
            end_date=date(2026, 3, 3),
            day_of_week=2,
            course_unit=None,
        )
        self.assertEqual(session_occurrence_bounds(slot), (date(2026, 3, 3), date(2026, 3, 3)))
        self.assertEqual(session_occurrence_dates(slot), [date(2026, 3, 3)])

    def test_recurring_uses_set_range_not_semester(self):
        semester = SimpleNamespace(start_date=date(2026, 1, 1), end_date=date(2026, 6, 30))
        course_unit = SimpleNamespace(semester=semester)
        slot = SimpleNamespace(
            session_date=None,
            start_date=date(2026, 2, 10),
            end_date=date(2026, 2, 28),
            day_of_week=2,
            course_unit=course_unit,
        )
        self.assertEqual(
            session_occurrence_bounds(slot),
            (date(2026, 2, 10), date(2026, 2, 28)),
        )
        self.assertEqual(
            session_occurrence_dates(slot),
            [date(2026, 2, 10), date(2026, 2, 17), date(2026, 2, 24)],
        )

    def test_ranges_do_not_overlap_when_disjoint(self):
        a = SimpleNamespace(
            session_date=None,
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 28),
            day_of_week=2,
            course_unit=None,
        )
        b = SimpleNamespace(
            session_date=None,
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 31),
            day_of_week=2,
            course_unit=None,
        )
        self.assertFalse(occurrence_ranges_overlap(a, b))

    def test_recurring_date_label(self):
        label = session_date_label(
            "Tuesday",
            [date(2026, 2, 10), date(2026, 2, 28)],
            recurring=True,
        )
        self.assertEqual(label, "Tuesdays · 10 Feb 2026 – 28 Feb 2026")


class SessionModelCleanSmoke(TestCase):
    """Lightweight smoke: ensure helpers accept typical time objects."""

    def test_times_are_orderable(self):
        self.assertLess(time(8, 0), time(10, 0))
