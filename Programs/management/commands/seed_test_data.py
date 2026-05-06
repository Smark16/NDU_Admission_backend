"""
Management command: seed_test_data
===================================
Populates the database with realistic test/demo data for end-to-end testing
of the academic flow: curriculum → enrollment → registration eligibility.

Safe to re-run — uses get_or_create throughout (idempotent).
Does NOT touch or delete any existing real data.

Usage:
    python manage.py seed_test_data
    python manage.py seed_test_data --reset-payments   # also set one student past threshold
    python manage.py seed_test_data --skip-tuition     # toggle skip_tuition_check ON
"""
from __future__ import annotations

import textwrap
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

User = get_user_model()

# ── Sentinel prefix so seed records are easy to spot ──────────────────────────
TAG = "[TEST]"


class Command(BaseCommand):
    help = "Seed test data for academic flow E2E testing (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-payments",
            action="store_true",
            help="Create StudentTuitionPayment records so one student passes the tuition gate.",
        )
        parser.add_argument(
            "--skip-tuition",
            action="store_true",
            help="Set RegistrationSettings.skip_tuition_check = True after seeding.",
        )
        parser.add_argument(
            "--unenroll",
            action="store_true",
            help="Set all TEST StudentProgrammeEnrollments back to 'pending' (useful for re-testing gates).",
        )

    # ─────────────────────────────────────────────────────────────────────────
    def handle(self, *args, **options):
        self.log = []

        with transaction.atomic():
            campus      = self._seed_campus()
            admin_user  = self._get_admin_user()
            acad_level  = self._seed_academic_level()
            faculty     = self._seed_faculty(campus)

            # Two programmes: one semester-based, one trimester-based
            prog_sem  = self._seed_program_semester(acad_level, faculty, campus)
            prog_tri  = self._seed_program_trimester(acad_level, faculty, campus)

            # Catalog courses
            cat_sem = self._seed_catalog_courses_semester()
            cat_tri = self._seed_catalog_courses_trimester()

            # Curriculum mappings
            self._seed_curriculum(prog_sem, cat_sem, "semester")
            self._seed_curriculum(prog_tri, cat_tri, "trimester")

            # Academic batches (ProgramBatch) + positioned Semesters
            batch_sem, sems_sem = self._seed_program_batch_semester(prog_sem)
            batch_tri, sems_tri = self._seed_program_batch_trimester(prog_tri)

            # CourseUnits (offered in the batch semesters)
            cu_sem = self._seed_course_units(batch_sem, sems_sem, prog_sem, cat_sem)
            cu_tri = self._seed_course_units(batch_tri, sems_tri, prog_tri, cat_tri)

            # Admission Batch (for AdmittedStudent FK)
            adm_batch = self._seed_admission_batch(admin_user, prog_sem, prog_tri, campus)

            # Test students
            student_a, admitted_a = self._seed_test_student(
                username="test.student.sem@ndu.test",
                first_name="Alice",
                last_name="TEST",
                student_id="TEST-SEM-001",
                reg_no="2025/TEST/SEM/001",
                program=prog_sem,
                campus=campus,
                adm_batch=adm_batch,
                admin_user=admin_user,
            )
            student_b, admitted_b = self._seed_test_student(
                username="test.student.tri@ndu.test",
                first_name="Bob",
                last_name="TEST",
                student_id="TEST-TRI-001",
                reg_no="2025/TEST/TRI/001",
                program=prog_tri,
                campus=campus,
                adm_batch=adm_batch,
                admin_user=admin_user,
            )

            # Enroll students (StudentProgrammeEnrollment)
            spe_a = self._seed_programme_enrollment(
                admitted_a, prog_sem, batch_sem, year=1, term=1, admin_user=admin_user
            )
            spe_b = self._seed_programme_enrollment(
                admitted_b, prog_tri, batch_tri, year=1, term=1, admin_user=admin_user
            )

            if options["unenroll"]:
                from Programs.models import StudentProgrammeEnrollment
                StudentProgrammeEnrollment.objects.filter(
                    notes__contains=TAG
                ).update(status="pending", enrolled_at=None)
                self._note("  ↺  All TEST enrollments reset to 'pending'")

            # Admin-enroll students into course units (StudentCourseUnitEnrollment)
            self._seed_course_unit_enrollments(admitted_a, cu_sem)
            self._seed_course_unit_enrollments(admitted_b, cu_tri)

            # Registration settings
            reg_settings = self._seed_registration_settings(admin_user)

            # Fee plan rules so payment status is calculable
            fee_plan = self._seed_fee_plan(prog_sem, batch_sem, sems_sem, admin_user, adm_batch)

            # Payments
            if options["reset_payments"]:
                self._seed_tuition_payment(admitted_a, fee_plan, amount=Decimal("1200000"))
                self._note("  💳  Tuition payment seeded for Alice (should pass 50% gate)")

            if options["skip_tuition"]:
                reg_settings.skip_tuition_check = True
                reg_settings.save()
                self._note("  ⚙️   skip_tuition_check set to TRUE on RegistrationSettings")

        self._print_summary(
            prog_sem, prog_tri,
            batch_sem, batch_tri,
            sems_sem, sems_tri,
            admitted_a, admitted_b,
            spe_a, spe_b,
            reg_settings,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _note(self, msg: str):
        self.log.append(msg)
        try:
            self.stdout.write(msg)
        except UnicodeEncodeError:
            safe = msg.encode("ascii", errors="replace").decode("ascii")
            self.stdout.write(safe)

    def _ok(self, label: str, created: bool):
        verb = "created" if created else "exists "
        marker = "+" if created else "."
        self._note(f"  {marker}  [{verb}] {label}")

    # ── Infrastructure ────────────────────────────────────────────────────────

    def _seed_campus(self):
        from accounts.models import Campus
        obj, created = Campus.objects.get_or_create(
            code="TEST-MAIN",
            defaults=dict(name=f"{TAG} Main Campus", address="Test Address, Kampala", email="test@ndu.edu"),
        )
        self._ok(f"Campus: {obj.name}", created)
        return obj

    def _get_admin_user(self):
        user = User.objects.filter(is_superuser=True).first()
        if not user:
            user = User.objects.create_superuser(
                username="test_admin", email="test_admin@ndu.test", password="test1234",
                first_name="Test", last_name="Admin",
            )
            self._ok("Created superuser test_admin", True)
        return user

    def _seed_academic_level(self):
        from admissions.models import AcademicLevel
        obj, created = AcademicLevel.objects.get_or_create(
            name="Undergraduate",
            defaults=dict(is_active=True),
        )
        self._ok(f"AcademicLevel: {obj.name}", created)
        return obj

    def _seed_faculty(self, campus):
        from admissions.models import Faculty
        obj, created = Faculty.objects.get_or_create(
            code="TEST-FAC",
            defaults=dict(name=f"{TAG} Faculty of Computing", is_active=True),
        )
        if created:
            obj.campuses.add(campus)
        self._ok(f"Faculty: {obj.name}", created)
        return obj

    # ── Programmes ───────────────────────────────────────────────────────────

    def _seed_program_semester(self, acad_level, faculty, campus):
        from Programs.models import Program
        obj, created = Program.objects.get_or_create(
            code="TEST-CS",
            defaults=dict(
                name=f"{TAG} Computer Science",
                short_form="BCS",
                faculty=faculty,
                academic_level=acad_level,
                min_years=3,
                max_years=3,
                calendar_type="semester",
                minimum_graduation_load=Decimal("120.00"),
                is_active=True,
            ),
        )
        if created:
            obj.campuses.add(campus)
        self._ok(f"Program (semester): {obj.name}", created)
        return obj

    def _seed_program_trimester(self, acad_level, faculty, campus):
        from Programs.models import Program
        obj, created = Program.objects.get_or_create(
            code="TEST-BIT",
            defaults=dict(
                name=f"{TAG} Business IT",
                short_form="BIT",
                faculty=faculty,
                academic_level=acad_level,
                min_years=3,
                max_years=3,
                calendar_type="trimester",
                minimum_graduation_load=Decimal("108.00"),
                is_active=True,
            ),
        )
        if created:
            obj.campuses.add(campus)
        self._ok(f"Program (trimester): {obj.name}", created)
        return obj

    # ── Course Catalog ────────────────────────────────────────────────────────

    def _seed_catalog_courses_semester(self):
        from Programs.models import CourseCatalogUnit
        courses = [
            ("TEST-CS101", "Introduction to Programming",         3, "mandatory"),
            ("TEST-CS102", "Discrete Mathematics",                3, "mandatory"),
            ("TEST-CS103", "Computer Organisation",               2, "mandatory"),
            ("TEST-CS104", "Communication Skills",                2, "mandatory"),
            ("TEST-CS201", "Data Structures & Algorithms",        3, "mandatory"),
            ("TEST-CS202", "Database Systems",                    3, "mandatory"),
            ("TEST-CS203", "Operating Systems",                   3, "mandatory"),
            ("TEST-CS204", "Web Technologies",                    2, "elective"),
            ("TEST-CS205", "Mobile Application Development",      2, "elective"),
        ]
        objs = []
        for code, title, cu, _ in courses:
            obj, created = CourseCatalogUnit.objects.get_or_create(
                code=code,
                defaults=dict(title=f"{TAG} {title}", credit_units=Decimal(str(cu)), is_active=True),
            )
            self._ok(f"  CatalogUnit: {code}", created)
            objs.append((obj, _))  # (catalog_unit, course_type)
        return objs

    def _seed_catalog_courses_trimester(self):
        from Programs.models import CourseCatalogUnit
        courses = [
            ("TEST-BIT101", "Principles of Management",           3, "mandatory"),
            ("TEST-BIT102", "Business Computing",                 3, "mandatory"),
            ("TEST-BIT103", "Accounting Fundamentals",            2, "mandatory"),
            ("TEST-BIT201", "Systems Analysis & Design",          3, "mandatory"),
            ("TEST-BIT202", "E-Commerce",                         2, "mandatory"),
            ("TEST-BIT203", "Entrepreneurship",                   2, "mandatory"),
            ("TEST-BIT204", "Project Management",                 2, "elective"),
            ("TEST-BIT205", "Digital Marketing",                  2, "elective"),
            ("TEST-BIT206", "Data Analytics",                     2, "elective"),
        ]
        objs = []
        for code, title, cu, ctype in courses:
            obj, created = CourseCatalogUnit.objects.get_or_create(
                code=code,
                defaults=dict(title=f"{TAG} {title}", credit_units=Decimal(str(cu)), is_active=True),
            )
            self._ok(f"  CatalogUnit: {code}", created)
            objs.append((obj, ctype))
        return objs

    # ── Curriculum Mapping ────────────────────────────────────────────────────

    def _seed_curriculum(self, program, catalog_list, cal_type):
        from Programs.models import ProgramCurriculumLine

        # Assign courses to year/term slots
        # semester:  Y1T1, Y1T2, Y2T1, Y2T2 ...
        # trimester: Y1T1, Y1T2, Y1T3, Y2T1 ...
        if cal_type == "semester":
            slots = [
                (1, 1), (1, 1), (1, 1),   # first 3 → Y1T1
                (1, 2), (1, 2),             # next 2  → Y1T2
                (2, 1), (2, 1),             # next 2  → Y2T1
                (2, 2), (2, 2),             # last 2  → Y2T2
            ]
        else:  # trimester
            slots = [
                (1, 1), (1, 1), (1, 1),   # Y1T1
                (1, 2), (1, 2), (1, 2),   # Y1T2
                (1, 3), (1, 3), (1, 3),   # Y1T3
            ]

        for idx, ((catalog_unit, ctype), (yr, term)) in enumerate(zip(catalog_list, slots)):
            obj, created = ProgramCurriculumLine.objects.get_or_create(
                program=program,
                catalog_course=catalog_unit,
                year_of_study=yr,
                term_number=term,
                defaults=dict(
                    course_type=ctype,
                    elective_group="Group A" if ctype == "elective" else "",
                    sort_order=idx + 1,
                    is_active=True,
                ),
            )
            self._ok(f"  CurriculumLine: {program.short_form} Y{yr}T{term} {catalog_unit.code} ({ctype})", created)

    # ── ProgramBatch + Semesters ──────────────────────────────────────────────

    def _seed_program_batch_semester(self, program):
        from Programs.models import ProgramBatch, Semester
        today = date.today()

        batch, created = ProgramBatch.objects.get_or_create(
            program=program,
            name=f"{TAG} 2025 Cohort",
            defaults=dict(academic_year="2025/2026", start_date=today, is_active=True),
        )
        self._ok(f"ProgramBatch: {batch.name} ({program.short_form})", created)

        semesters = []
        sem_defs = [
            # (name, order, year_of_study, term_number, start_offset_days, end_offset_days)
            ("Semester 1 (Y1T1)", 1, 1, 1,   0,  120),
            ("Semester 2 (Y1T2)", 2, 1, 2, 130,  250),
            ("Semester 3 (Y2T1)", 3, 2, 1, 260,  380),
            ("Semester 4 (Y2T2)", 4, 2, 2, 390,  510),
        ]
        for name, order, yr, term, s_off, e_off in sem_defs:
            sem, created = Semester.objects.get_or_create(
                program_batch=batch,
                order=order,
                defaults=dict(
                    name=name,
                    year_of_study=yr,
                    term_number=term,
                    start_date=today + timedelta(days=s_off),
                    end_date=today + timedelta(days=e_off),
                    is_active=True,
                ),
            )
            self._ok(f"  Semester: {sem.name} [Y{yr}T{term}]", created)
            semesters.append(sem)
        return batch, semesters

    def _seed_program_batch_trimester(self, program):
        from Programs.models import ProgramBatch, Semester
        today = date.today()

        batch, created = ProgramBatch.objects.get_or_create(
            program=program,
            name=f"{TAG} 2025 Cohort",
            defaults=dict(academic_year="2025/2026", start_date=today, is_active=True),
        )
        self._ok(f"ProgramBatch: {batch.name} ({program.short_form})", created)

        semesters = []
        # 3 terms in year 1 for trimester programme
        tri_defs = [
            ("Trimester 1 (Y1T1)", 1, 1, 1,   0,   90),
            ("Trimester 2 (Y1T2)", 2, 1, 2, 100,  190),
            ("Trimester 3 (Y1T3)", 3, 1, 3, 200,  290),
            ("Trimester 4 (Y2T1)", 4, 2, 1, 300,  390),
        ]
        for name, order, yr, term, s_off, e_off in tri_defs:
            sem, created = Semester.objects.get_or_create(
                program_batch=batch,
                order=order,
                defaults=dict(
                    name=name,
                    year_of_study=yr,
                    term_number=term,
                    start_date=today + timedelta(days=s_off),
                    end_date=today + timedelta(days=e_off),
                    is_active=True,
                ),
            )
            self._ok(f"  Trimester: {sem.name} [Y{yr}T{term}]", created)
            semesters.append(sem)
        return batch, semesters

    # ── CourseUnits (operational) ─────────────────────────────────────────────

    def _seed_course_units(self, batch, semesters, program, catalog_list):
        """Create one CourseUnit per catalog entry, placed in the semester
        whose year_of_study + term_number matches the curriculum mapping."""
        from Programs.models import CourseUnit, ProgramCurriculumLine

        sem_map = {(s.year_of_study, s.term_number): s for s in semesters}
        created_units = []

        for catalog_unit, _ in catalog_list:
            # Find the curriculum line for this catalog course in this program
            cl = ProgramCurriculumLine.objects.filter(
                program=program, catalog_course=catalog_unit, is_active=True
            ).first()
            if not cl:
                continue

            target_sem = sem_map.get((cl.year_of_study, cl.term_number))
            if not target_sem:
                continue

            cu, created = CourseUnit.objects.get_or_create(
                code=catalog_unit.code,
                semester=target_sem,
                defaults=dict(
                    name=catalog_unit.title,
                    program_batch=batch,
                    catalog_unit=catalog_unit,
                    curriculum_line=cl,
                    credit_units=catalog_unit.credit_units,
                    is_active=True,
                ),
            )
            self._ok(f"  CourseUnit: {cu.code} in '{target_sem.name}'", created)
            created_units.append(cu)

        return created_units

    # ── Admission Batch ───────────────────────────────────────────────────────

    def _seed_admission_batch(self, admin_user, prog_sem, prog_tri, campus):
        from admissions.models import Batch
        today = date.today()
        batch, created = Batch.objects.get_or_create(
            code="TEST-BATCH-2025",
            defaults=dict(
                name=f"{TAG} 2025 Test Intake",
                academic_year="2025/2026",
                application_start_date=today - timedelta(days=90),
                application_end_date=today - timedelta(days=30),
                admission_start_date=today - timedelta(days=25),
                admission_end_date=today + timedelta(days=30),
                is_active=True,
                created_by=admin_user,
            ),
        )
        if created:
            batch.programs.set([prog_sem, prog_tri])
        self._ok(f"AdmissionBatch: {batch.name}", created)
        return batch

    # ── Test Students ─────────────────────────────────────────────────────────

    def _seed_test_student(
        self, username, first_name, last_name,
        student_id, reg_no, program, campus, adm_batch, admin_user,
    ):
        from admissions.models import AcademicLevel, Application, AdmittedStudent

        # User
        user, ucreated = User.objects.get_or_create(
            username=username,
            defaults=dict(
                email=username,
                first_name=first_name,
                last_name=last_name,
                is_applicant=True,
            ),
        )
        if ucreated:
            user.set_password("test1234")
            user.save()
        self._ok(f"User: {username}", ucreated)

        acad_level = AcademicLevel.objects.get(name="Undergraduate")

        # Application (passport_photo is blank=False in model but ImageField allows empty string on create)
        app, acreated = Application.objects.get_or_create(
            applicant=user,
            batch=adm_batch,
            defaults=dict(
                campus=campus,
                academic_level=acad_level,
                first_name=first_name,
                last_name=last_name,
                date_of_birth=date(2000, 1, 1),
                gender="Male",
                nationality="Ugandan",
                phone="0700000000",
                email=username,
                next_of_kin_name="Test Parent",
                next_of_kin_contact="0700000001",
                next_of_kin_relationship="Parent",
                olevel_year=2018,
                olevel_index_number="TEST/001/2018",
                olevel_school="Test Secondary School",
                alevel_year=2020,
                alevel_index_number="TEST/001/2020",
                alevel_school="Test High School",
                alevel_combination="PCM",
                status="admitted",
                application_fee_paid=True,
                offer_letter_status="sent",
                offer_letter_progress=100,
            ),
        )
        if acreated:
            app.programs.set([program])
        self._ok(f"Application for {username}", acreated)

        # AdmittedStudent
        admitted, as_created = AdmittedStudent.objects.get_or_create(
            student_id=student_id,
            defaults=dict(
                application=app,
                study_mode="Day",
                reg_no=reg_no,
                admitted_program=program,
                admitted_batch=adm_batch,
                admitted_campus=campus,
                is_admitted=True,
                admission_date=timezone.now(),
                admitted_by=admin_user,
            ),
        )
        self._ok(f"AdmittedStudent: {student_id} ({first_name} {last_name})", as_created)
        return user, admitted

    # ── StudentProgrammeEnrollment ────────────────────────────────────────────

    def _seed_programme_enrollment(self, admitted, program, batch, year, term, admin_user):
        from Programs.models import StudentProgrammeEnrollment

        spe, created = StudentProgrammeEnrollment.objects.get_or_create(
            student=admitted,
            defaults=dict(
                program=program,
                program_batch=batch,
                current_year_of_study=year,
                current_term_number=term,
                status="enrolled",
                enrolled_by=admin_user,
                notes=f"{TAG} Created by seed_test_data command",
            ),
        )
        # If already exists but pending, promote to enrolled
        if not created and spe.status != "enrolled":
            spe.status = "enrolled"
            spe.enrolled_at = timezone.now()
            spe.save()
            self._note(f"  ↑  Promoted existing SPE to 'enrolled' for {admitted.student_id}")
        else:
            self._ok(
                f"StudentProgrammeEnrollment: {admitted.student_id} → {program.short_form} "
                f"Y{year}T{term} status={spe.status}",
                created,
            )
        return spe

    # ── StudentCourseUnitEnrollment (admin-enrol student in course units) ─────

    def _seed_course_unit_enrollments(self, admitted, course_units):
        from Programs.models import StudentCourseUnitEnrollment

        for cu in course_units:
            obj, created = StudentCourseUnitEnrollment.objects.get_or_create(
                student=admitted,
                course_unit=cu,
                defaults=dict(status="enrolled"),
            )
            self._ok(f"  CourseUnitEnrollment: {admitted.student_id} → {cu.code}", created)

    # ── Registration Settings ─────────────────────────────────────────────────

    def _seed_registration_settings(self, admin_user):
        from payments.models import RegistrationSettings

        settings = RegistrationSettings.get_settings()
        # Only set defaults if they appear to be factory-fresh
        changed = False
        if settings.min_tuition_payment_percentage == Decimal("50.00"):
            settings.min_tuition_payment_percentage = Decimal("50.00")
            changed = True
        settings.require_admission_approval = True
        settings.require_programme_enrollment = True
        settings.skip_tuition_check = False
        settings.is_active = True
        settings.updated_by = admin_user
        settings.save()
        self._ok(
            f"RegistrationSettings: threshold={settings.min_tuition_payment_percentage}% | "
            f"skip_tuition={settings.skip_tuition_check} | active={settings.is_active}",
            changed,
        )
        return settings

    # ── Fee Plan (for payment eligibility testing) ────────────────────────────

    def _seed_fee_plan(self, program, batch, semesters, admin_user, adm_batch):
        from payments.models import FeeHead, FeePlan, FeePlanRule
        from admissions.models import AcademicLevel

        tuition_head, _ = FeeHead.objects.get_or_create(
            code="TUITION_FEE",
            defaults=dict(name="Tuition Fee", category="tuition", is_active=True),
        )

        acad_level = AcademicLevel.objects.get(name="Undergraduate")
        plan, created = FeePlan.objects.get_or_create(
            name=f"{TAG} {program.short_form} Tuition Plan 2025",
            defaults=dict(
                plan_type="tuition",
                scope="program",
                term="semester",
                nationality_type="local",
                program=program,
                status="active",
                version=1,
                is_active=True,
                created_by=admin_user,
            ),
        )
        if created:
            plan.programs.set([program])
            plan.academic_levels.set([acad_level])
        self._ok(f"FeePlan: {plan.name}", created)

        # Create a rule for the FIRST semester of the batch (Y1T1)
        first_sem = semesters[0] if semesters else None
        if first_sem:
            rule, rcreated = FeePlanRule.objects.get_or_create(
                fee_plan=plan,
                fee_head=tuition_head,
                program_batch=batch,
                semester=first_sem,
                defaults=dict(
                    trigger_stage="semester_start",
                    program=program,
                    amount=Decimal("2000000.00"),
                    currency="UGX",
                    amount_international=Decimal("600.00"),
                    currency_international="USD",
                    is_active=True,
                    order=1,
                ),
            )
            self._ok(
                f"FeePlanRule: {program.short_form} {first_sem.name} "
                f"UGX {rule.amount:,.0f}",
                rcreated,
            )
        return plan

    # ── Tuition Payment (optional) ────────────────────────────────────────────

    def _seed_tuition_payment(self, admitted, fee_plan, amount: Decimal):
        from payments.models import StudentTuitionPayment

        obj, created = StudentTuitionPayment.objects.get_or_create(
            student=admitted,
            external_reference=f"TEST-PAY-{admitted.student_id}",
            defaults=dict(
                amount=amount,
                currency="UGX",
                status="PAID",
                payment_date=timezone.now(),
                receipt_number=f"RCP-{admitted.student_id}",
                notes=f"{TAG} Seeded payment for testing",
            ),
        )
        self._ok(f"TuitionPayment: {admitted.student_id} UGX {amount:,.0f}", created)
        return obj

    # ─────────────────────────────────────────────────────────────────────────
    # Summary
    # ─────────────────────────────────────────────────────────────────────────

    def _print_summary(
        self, prog_sem, prog_tri, batch_sem, batch_tri,
        sems_sem, sems_tri, admitted_a, admitted_b,
        spe_a, spe_b, reg_settings,
    ):
        from Programs.models import (
            ProgramCurriculumLine, CourseUnit, StudentCourseUnitEnrollment
        )

        cu_count_sem = CourseUnit.objects.filter(program_batch=batch_sem).count()
        cu_count_tri = CourseUnit.objects.filter(program_batch=batch_tri).count()
        cl_count_sem = ProgramCurriculumLine.objects.filter(program=prog_sem).count()
        cl_count_tri = ProgramCurriculumLine.objects.filter(program=prog_tri).count()
        sce_a = StudentCourseUnitEnrollment.objects.filter(student=admitted_a).count()
        sce_b = StudentCourseUnitEnrollment.objects.filter(student=admitted_b).count()

        banner = textwrap.dedent(f"""
        ╔══════════════════════════════════════════════════════════════╗
        ║              SEED DATA SUMMARY — NDU Portal                  ║
        ╠══════════════════════════════════════════════════════════════╣
        ║  PROGRAMMES                                                  ║
        ║  • {prog_sem.name:<55} ║
        ║    calendar=semester | max_years={prog_sem.max_years} | grad_load={prog_sem.minimum_graduation_load} CU  ║
        ║    Batch : {batch_sem.name:<49} ║
        ║    Curriculum lines : {cl_count_sem:<38} ║
        ║    CourseUnits (offered) : {cu_count_sem:<32} ║
        ║    Semesters:                                                ║
        """)
        for s in sems_sem:
            banner += f"        ║      [{s.order}] {s.name:<50} ║\n"

        banner += textwrap.dedent(f"""
        ║  • {prog_tri.name:<55} ║
        ║    calendar=trimester | max_years={prog_tri.max_years} | grad_load={prog_tri.minimum_graduation_load} CU   ║
        ║    Batch : {batch_tri.name:<49} ║
        ║    Curriculum lines : {cl_count_tri:<38} ║
        ║    CourseUnits (offered) : {cu_count_tri:<32} ║
        ║    Semesters/Trimesters:                                     ║
        """)
        for s in sems_tri:
            banner += f"        ║      [{s.order}] {s.name:<50} ║\n"

        banner += textwrap.dedent(f"""
        ╠══════════════════════════════════════════════════════════════╣
        ║  TEST STUDENTS                                               ║
        ║  A) Alice TEST  username=test.student.sem@ndu.test           ║
        ║     student_id ={admitted_a.student_id:<44} ║
        ║     Programme  ={prog_sem.short_form:<44} ║
        ║     Enrollment ={spe_a.status:<44} ║
        ║     Admin-enrolled in {sce_a} course unit(s)                      ║
        ║                                                              ║
        ║  B) Bob TEST    username=test.student.tri@ndu.test           ║
        ║     student_id ={admitted_b.student_id:<44} ║
        ║     Programme  ={prog_tri.short_form:<44} ║
        ║     Enrollment ={spe_b.status:<44} ║
        ║     Admin-enrolled in {sce_b} course unit(s)                      ║
        ║                                                              ║
        ║  Password for both: test1234                                 ║
        ╠══════════════════════════════════════════════════════════════╣
        ║  REGISTRATION SETTINGS                                       ║
        ║  • is_active                  = {str(reg_settings.is_active):<29} ║
        ║  • require_admission_approval = {str(reg_settings.require_admission_approval):<29} ║
        ║  • require_programme_enrollmt = {str(reg_settings.require_programme_enrollment):<29} ║
        ║  • skip_tuition_check         = {str(reg_settings.skip_tuition_check):<29} ║
        ║  • min_tuition_payment_%      = {str(reg_settings.min_tuition_payment_percentage)+'%':<29} ║
        ╠══════════════════════════════════════════════════════════════╣
        ║  HOW TO RUN TEST SCENARIOS                                   ║
        ║                                                              ║
        ║  1. Login at / as test.student.sem@ndu.test / test1234       ║
        ║     → My Enrollment: should show BCS Y1T1 enrolled           ║
        ║     → Course Registration: should show enrolled courses      ║
        ║     → Eligibility: blocked unless tuition threshold met      ║
        ║                                                              ║
        ║  2. Skip tuition gate (bypass payment check):                ║
        ║     python manage.py seed_test_data --skip-tuition           ║
        ║     OR toggle in Admin → Tuition & Registration Settings     ║
        ║                                                              ║
        ║  3. Seed a passing payment for Alice:                        ║
        ║     python manage.py seed_test_data --reset-payments         ║
        ║     (Adds UGX 1,200,000 payment = 60% of 2,000,000)         ║
        ║                                                              ║
        ║  4. Reset enrollment to pending (re-test SPE gate):          ║
        ║     python manage.py seed_test_data --unenroll               ║
        ║                                                              ║
        ║  5. Login as test.student.tri@ndu.test for trimester flow    ║
        ╚══════════════════════════════════════════════════════════════╝
        """)
        try:
            self.stdout.write(self.style.SUCCESS(banner))
        except UnicodeEncodeError:
            safe = banner.encode("ascii", errors="replace").decode("ascii")
            self.stdout.write(self.style.SUCCESS(safe))
