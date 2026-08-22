from django.test import SimpleTestCase

from Programs.shared_teaching import (
    moodle_group_idnumber,
    moodle_parent_idnumber,
    moodle_shared_fields_for_course_unit,
    moodle_unit_idnumber,
    normalize_shared_unit_key,
    offering_label_for_course_unit,
)


class _Semester:
    year_of_study = 1
    term_number = 1
    order = 1
    start_date = None
    name = "Year 1 Semester 1"


class _Program:
    short_form = "BBA"
    name = "Bachelor of Business Administration-Day"
    faculty_id = None
    faculty = None


class _Batch:
    academic_year = "2026/2027"
    name = "CLASS OF 2026-2030"
    program_id = 1
    program = _Program()


class _Catalog:
    code = "ETH 1101"


class _STO:
    pk = 42
    code = "ETH 1101"
    name = "Ethics"
    catalog_unit = _Catalog()
    academic_year_label = "2026/2027"

    @property
    def moodle_idnumber(self):
        return f"STO-{self.pk}"


class _CourseUnit:
    pk = 88001
    code = "ETH 1101"
    name = "Ethics"
    semester_id = 12
    semester = _Semester()
    program_batch_id = 1
    program_batch = _Batch()
    shared_teaching_offering_id = 42
    shared_teaching_offering = _STO()
    credit_units = None
    lecturers = None


class MoodleSharedFieldsTests(SimpleTestCase):
    def test_normalize_shared_unit_key(self):
        self.assertEqual(normalize_shared_unit_key("ETH 1101"), "ETH1101")
        self.assertEqual(normalize_shared_unit_key("BXE 1101"), "BXE1101")

    def test_offering_label(self):
        cu = _CourseUnit()
        self.assertEqual(offering_label_for_course_unit(cu), "BBA Day · Year 1")

    def test_shared_fields_for_linked_unit(self):
        cu = _CourseUnit()
        fields = moodle_shared_fields_for_course_unit(cu, parent_ids={42: "88001"})
        self.assertTrue(fields["is_shared"])
        self.assertEqual(fields["shared_unit_key"], "ETH1101")
        self.assertEqual(fields["offering_id"], "88001")
        self.assertEqual(fields["parent_unit_id"], "88001")
        self.assertEqual(fields["group_idnumber"], moodle_group_idnumber(88001))
        self.assertEqual(
            fields["parent_idnumber"],
            moodle_parent_idnumber(_STO(), "2026-S1"),
        )
        self.assertEqual(fields["idnumber"], fields["parent_idnumber"])

    def test_non_shared_fields(self):
        cu = _CourseUnit()
        cu.shared_teaching_offering_id = None
        cu.shared_teaching_offering = None
        fields = moodle_shared_fields_for_course_unit(cu)
        self.assertFalse(fields["is_shared"])
        self.assertIsNone(fields["shared_unit_key"])
        self.assertEqual(fields["idnumber"], moodle_unit_idnumber(88001))
