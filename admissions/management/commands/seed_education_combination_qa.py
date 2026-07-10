"""
Seed data + optional verification for teaching subject combination at admission.

Usage:
    python manage.py seed_education_combination_qa
    python manage.py seed_education_combination_qa --verify
    python manage.py seed_education_combination_qa --reset-applications
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

User = get_user_model()
TAG = "[QA-EDU]"


class Command(BaseCommand):
    help = "Seed education programme + combinations for extensive admission QA testing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--verify",
            action="store_true",
            help="Run automated checks after seeding (serializer, offer context, API shape).",
        )
        parser.add_argument(
            "--reset-applications",
            action="store_true",
            help="Delete QA applicant/admission rows and recreate fresh accepted application.",
        )

    def handle(self, *args, **options):
        with transaction.atomic():
            ctx = self._seed_all(reset_applications=options["reset_applications"])

        self._print_playbook(ctx)

        if options["verify"]:
            self._run_verifications(ctx)

    def _seed_all(self, *, reset_applications: bool):
        from accounts.models import Campus
        from admissions.models import (
            AcademicLevel,
            Application,
            ApplicationProgramChoice,
            Batch,
            Faculty,
        )
        from Programs.models import (
            CourseCatalogUnit,
            Program,
            ProgramBatch,
            ProgramCurriculumLine,
            ProgramCurriculumVersion,
            ProgramSpecialization,
            ensure_program_default_curriculum_version,
        )

        campus, _ = Campus.objects.get_or_create(
            code="QA-MAIN",
            defaults={
                "name": f"{TAG} Main Campus",
                "address": "QA Campus",
                "email": "qa@ndu.test",
            },
        )

        acad_level, _ = AcademicLevel.objects.get_or_create(
            name=f"{TAG} Undergraduate",
            defaults={"is_active": True},
        )

        faculty, _ = Faculty.objects.get_or_create(
            code="QA-EDU",
            defaults={"name": f"{TAG} Faculty of Education", "is_active": True},
        )
        faculty.campuses.add(campus)

        program, created = Program.objects.get_or_create(
            code="QA-BSED",
            defaults={
                "name": f"{TAG} BSc Education (Secondary)",
                "short_form": "BSED-QA",
                "faculty": faculty,
                "academic_level": acad_level,
                "min_years": 3,
                "max_years": 3,
                "calendar_type": "semester",
                "minimum_graduation_load": Decimal("120.00"),
                "has_specialization": True,
                "specialization_entry_year": 1,
                "specialization_entry_term": 1,
                "is_active": True,
            },
        )
        if not created:
            Program.objects.filter(pk=program.pk).update(
                has_specialization=True,
                specialization_entry_year=1,
                specialization_entry_term=1,
                is_active=True,
            )
            program.refresh_from_db()
        program.campuses.add(campus)

        combo_names = [
            "Mathematics & Physics",
            "Mathematics & Biology",
            "Mathematics & Chemistry",
            "Mathematics & English",
        ]
        specs = {}
        for name in combo_names:
            spec, _ = ProgramSpecialization.objects.get_or_create(
                program=program,
                name=name,
                defaults={"is_active": True},
            )
            specs[name] = spec

        version = ensure_program_default_curriculum_version(program)
        version.name = f"{TAG} Default curriculum"
        version.is_default = True
        version.is_active = True
        version.save()

        shared_course, _ = CourseCatalogUnit.objects.get_or_create(
            code="QA-EDU101",
            defaults={
                "title": f"{TAG} Foundations of Education",
                "credit_units": Decimal("3.00"),
                "is_active": True,
            },
        )
        method_courses = {}
        for label, code in [
            ("Mathematics & Physics", "QA-MTH-MET"),
            ("Mathematics & Biology", "QA-MTH-BIO"),
            ("Mathematics & Chemistry", "QA-MTH-CHE"),
            ("Mathematics & English", "QA-MTH-ENG"),
        ]:
            cat, _ = CourseCatalogUnit.objects.get_or_create(
                code=code,
                defaults={
                    "title": f"{TAG} Methods - {label}",
                    "credit_units": Decimal("3.00"),
                    "is_active": True,
                },
            )
            method_courses[label] = cat

        ProgramCurriculumLine.objects.get_or_create(
            curriculum_version=version,
            catalog_course=shared_course,
            year_of_study=1,
            term_number=1,
            defaults={
                "program": program,
                "course_type": "mandatory",
                "specialization": None,
                "sort_order": 1,
                "is_active": True,
            },
        )
        sort = 2
        for label, cat in method_courses.items():
            ProgramCurriculumLine.objects.get_or_create(
                curriculum_version=version,
                catalog_course=cat,
                year_of_study=1,
                term_number=1,
                defaults={
                    "program": program,
                    "course_type": "mandatory",
                    "specialization": label,
                    "sort_order": sort,
                    "is_active": True,
                },
            )
            sort += 1

        today = timezone.now().date()
        admin_user = User.objects.filter(is_superuser=True).order_by("id").first()
        if not admin_user:
            admin_user = User.objects.order_by("id").first()

        adm_batch = (
            Batch.objects.filter(is_active=True, programs=program)
            .order_by("-id")
            .first()
        )
        if adm_batch is None:
            adm_batch, _ = Batch.objects.get_or_create(
                code="QA-EDU-2026",
                defaults={
                    "name": f"{TAG} Aug 2026 Intake",
                    "application_start_date": today - timedelta(days=30),
                    "application_end_date": today + timedelta(days=30),
                    "admission_start_date": today - timedelta(days=7),
                    "admission_end_date": today + timedelta(days=60),
                    "offer_start_date": today - timedelta(days=7),
                    "offer_end_date": today + timedelta(days=90),
                    "is_active": True,
                    "created_by": admin_user,
                },
            )
        adm_batch.programs.add(program)

        prog_batch, _ = ProgramBatch.objects.get_or_create(
            program=program,
            name=f"{TAG} 2026 Cohort",
            defaults={
                "academic_year": "2026/2027",
                "start_date": today,
                "is_active": True,
                "curriculum_version": version,
            },
        )

        if reset_applications:
            Application.objects.filter(email__startswith="qa.edu.applicant").delete()

        applicant, _ = User.objects.get_or_create(
            username="qa.edu.applicant@ndu.test",
            defaults={
                "email": "qa.edu.applicant@ndu.test",
                "first_name": "QA",
                "last_name": "Applicant",
                "is_applicant": True,
            },
        )
        if not applicant.has_usable_password():
            applicant.set_password("QaTest123!")
            applicant.save(update_fields=["password"])

        application, _ = Application.objects.get_or_create(
            applicant=applicant,
            defaults={
                "first_name": "QA",
                "last_name": "Applicant",
                "middle_name": "",
                "title": "MR.",
                "date_of_birth": date(2000, 1, 15),
                "gender": "male",
                "nationality": "Ugandan",
                "phone": "0700000001",
                "email": "qa.edu.applicant@ndu.test",
                "address": "QA Address",
                "next_of_kin_name": "QA Kin",
                "next_of_kin_contact": "0700000002",
                "next_of_kin_relationship": "Parent",
                "campus": campus,
                "batch": adm_batch,
                "academic_level": acad_level,
                "status": "accepted",
                "application_reference": "QA-EDU-APP-001",
                "has_olevel": True,
                "has_alevel": False,
            },
        )
        Application.objects.filter(pk=application.pk).update(status="accepted")
        application.refresh_from_db()

        ApplicationProgramChoice.objects.filter(application=application).delete()
        ApplicationProgramChoice.objects.create(
            application=application,
            program=program,
            choice_order=1,
        )

        return {
            "campus": campus,
            "program": program,
            "specs": specs,
            "version": version,
            "adm_batch": adm_batch,
            "prog_batch": prog_batch,
            "application": application,
            "applicant_user": applicant,
        }

    def _print_playbook(self, ctx):
        program = ctx["program"]
        application = ctx["application"]
        specs = ctx["specs"]

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=" * 72))
        self.stdout.write(self.style.SUCCESS("  EDUCATION COMBINATION QA - SEED COMPLETE"))
        self.stdout.write(self.style.SUCCESS("=" * 72))
        self.stdout.write(f"  Programme ID:     {program.id}  ({program.code})")
        self.stdout.write(f"  has_specialization: {program.has_specialization}")
        self.stdout.write(f"  Application ID:   {application.id}  (status=accepted)")
        self.stdout.write(f"  Applicant login:  qa.edu.applicant@ndu.test / QaTest123!")
        self.stdout.write("")
        self.stdout.write("  Teaching combinations:")
        for name, spec in specs.items():
            self.stdout.write(f"    - [{spec.id}] {name}")
        self.stdout.write("")
        self.stdout.write(self.style.WARNING("  EXTENSIVE TEST PLAYBOOK"))
        self.stdout.write("")
        sections = [
            (
                "A. Setup / API smoke",
                [
                    f"GET /api/admissions/program_specializations/{program.id}/",
                    "Expect: has_specialization=true, 4 specializations",
                    f"Open HORIZON: /admin/admit_student/{application.id}",
                    "Expect: Teaching subject combination dropdown appears",
                ],
            ),
            (
                "B. Admit validation (negative)",
                [
                    "Try admit WITHOUT selecting combination - blocked in UI",
                    "POST create_admissions without admitted_specialization - 400",
                ],
            ),
            (
                "C. Admit happy path",
                [
                    "Select Mathematics & Physics - admit",
                    "GET candidate_admission - admitted_specialization + subject_combination",
                    "List admitted students - subject_combination column populated",
                ],
            ),
            (
                "D. Offer letter",
                [
                    "Add PDF/DOCX field mapped to: subject_combination",
                    "Generate offer letter - text shows Mathematics & Physics",
                    "Try generate WITHOUT combination on old record - blocked with clear error",
                ],
            ),
            (
                "E. Edit admission",
                [
                    f"Open edit admitted student record after admit (use admission id from list)",
                    "Change combination to Mathematics & Biology - save",
                    "Regenerate offer letter - updated combination",
                ],
            ),
            (
                "F. Academic enrollment",
                [
                    "Admin enroll student (Enrollment page)",
                    "Expect specialization pre-filled from admission",
                    "Student my_courses / expected curriculum shows track-specific lines",
                ],
            ),
            (
                "G. Curriculum manager",
                [
                    f"Programme hub - curriculum for program {program.id}",
                    "Verify shared line (Foundations) + tagged Methods lines per combination",
                ],
            ),
        ]
        for title, steps in sections:
            self.stdout.write(self.style.NOTICE(f"  {title}"))
            for step in steps:
                self.stdout.write(f"    - {step}")
            self.stdout.write("")

    def _run_verifications(self, ctx):
        from admissions.admission_specialization import (
            offer_letter_combination_context,
            validate_admitted_specialization_for_program,
            validate_offer_letter_admission,
        )
        from admissions.models import AdmittedStudent
        from admissions.serializers import AdmittedStudentSerializer

        program = ctx["program"]
        spec = ctx["specs"]["Mathematics & Physics"]
        application = ctx["application"]

        self.stdout.write(self.style.NOTICE("Running automated verifications..."))

        err = validate_admitted_specialization_for_program(program, None)
        assert err, "Expected error when combination missing"
        self.stdout.write("  OK  missing combination rejected")

        err = validate_admitted_specialization_for_program(program, spec)
        assert err is None, err
        self.stdout.write("  OK  valid combination accepted")

        reg_suffix = timezone.now().strftime("%H%M%S")
        payload = {
            "application": application.id,
            "admitted_program": program.id,
            "admitted_campus": ctx["campus"].id,
            "admitted_batch": ctx["adm_batch"].id,
            "intended_program_batch": ctx["prog_batch"].id,
            "study_mode": "D",
            "reg_no": f"QA/EDU/{reg_suffix}",
            "is_admitted": True,
        }
        ser = AdmittedStudentSerializer(data=payload)
        assert not ser.is_valid(), ser.errors
        assert "admitted_specialization" in ser.errors
        self.stdout.write("  OK  serializer requires combination")

        payload["admitted_specialization"] = spec.id
        ser = AdmittedStudentSerializer(data=payload)
        assert ser.is_valid(), ser.errors
        self.stdout.write("  OK  serializer accepts combination")

        # Dry-run offer context using unsaved admission shell
        admission = AdmittedStudent(
            application=application,
            admitted_program=program,
            admitted_campus=ctx["campus"],
            admitted_batch=ctx["adm_batch"],
            admitted_specialization=spec,
            study_mode="D",
            reg_no="QA/EDU/999",
            is_admitted=True,
        )
        combo_err = validate_offer_letter_admission(admission)
        assert combo_err is None, combo_err
        extras = offer_letter_combination_context(admission)
        assert extras["subject_combination"] == "Mathematics & Physics"
        self.stdout.write("  OK  offer letter context includes subject_combination")

        self.stdout.write(self.style.SUCCESS("All automated verifications passed."))
