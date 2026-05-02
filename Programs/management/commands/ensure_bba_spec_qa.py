"""
Idempotent QA fixture: one admitted student on BBA (program 38) for specialization API tests.

  python manage.py ensure_bba_spec_qa
  python manage.py ensure_bba_spec_qa --exercise-api

Adds programme 38 to admission Batch 5 if missing. Does not delete other data.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

USER_USERNAME = "bba_spec_qa"
USER_EMAIL = "bba_spec_qa@ndu.test"
USER_PASSWORD = "testpass123"
STUDENT_ID = "BBA-SPEC-QA-001"
REG_NO = "BBA/SPEC/QA/001"
TAG = "[BBA-SPEC-QA]"
PROGRAM_PK = 38
ADM_BATCH_PK = 5
PROG_BATCH_PK = 32
CURRICULUM_VERSION_PK = 2


class Command(BaseCommand):
    help = "Ensure BBA specialization QA student + enrollment exist (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--exercise-api",
            action="store_true",
            help="After seeding, call student specialization endpoints via APIClient and print results.",
        )

    def handle(self, *args, **options):
        from admissions.models import AdmittedStudent, Application, Batch
        from admissions.utils.reference import generate_reference
        from Programs.models import (
            Program,
            ProgramBatch,
            ProgramCurriculumVersion,
            StudentProgrammeEnrollment,
        )

        program = Program.objects.get(pk=PROGRAM_PK)
        adm_batch = Batch.objects.get(pk=ADM_BATCH_PK)
        prog_batch = ProgramBatch.objects.get(pk=PROG_BATCH_PK)
        curriculum_version = ProgramCurriculumVersion.objects.get(pk=CURRICULUM_VERSION_PK)

        if prog_batch.program_id != program.id:
            raise CommandError("ProgramBatch %s does not belong to program %s." % (PROG_BATCH_PK, PROGRAM_PK))
        if curriculum_version.program_id != program.id:
            raise CommandError("Curriculum version %s does not belong to program %s." % (CURRICULUM_VERSION_PK, PROGRAM_PK))

        adm_batch.programs.add(program)

        campus = program.campuses.first()
        if not campus:
            raise CommandError("Program %s has no campus; cannot create application." % program.code)

        tpl = Application.objects.filter(batch=adm_batch).first()
        if not tpl:
            raise CommandError("No template Application in admission batch %s." % ADM_BATCH_PK)

        User = get_user_model()

        with transaction.atomic():
            user, created = User.objects.get_or_create(
                username=USER_USERNAME,
                defaults={
                    "email": USER_EMAIL,
                    "first_name": "BBA",
                    "last_name": "SpecQA",
                    "is_active": True,
                },
            )
            if created:
                user.set_password(USER_PASSWORD)
                user.save()
                self.stdout.write(self.style.SUCCESS("Created user %s (password: %s)" % (USER_USERNAME, USER_PASSWORD)))
            else:
                self.stdout.write("User %s already exists." % USER_USERNAME)

            admitted = AdmittedStudent.objects.filter(student_id=STUDENT_ID).first()
            if admitted:
                if admitted.admitted_program_id != program.id:
                    raise CommandError(
                        "AdmittedStudent %s is on programme %s, not BBA (pk=%s)."
                        % (STUDENT_ID, admitted.admitted_program_id, PROGRAM_PK)
                    )
                application = admitted.application
                self.stdout.write("AdmittedStudent %s already exists." % STUDENT_ID)
            else:
                ref = generate_reference()
                while Application.objects.filter(application_reference=ref).exists():
                    ref = generate_reference()
                application = Application.objects.create(
                    applicant=user,
                    batch=adm_batch,
                    campus=campus,
                    academic_level=tpl.academic_level,
                    first_name="BBA",
                    last_name="SpecQA",
                    middle_name="",
                    date_of_birth=tpl.date_of_birth,
                    gender=tpl.gender,
                    nationality=tpl.nationality,
                    phone="0700000999",
                    email=USER_EMAIL,
                    address=tpl.address or "QA",
                    next_of_kin_name=tpl.next_of_kin_name,
                    next_of_kin_contact=tpl.next_of_kin_contact,
                    next_of_kin_relationship=tpl.next_of_kin_relationship,
                    olevel_year=tpl.olevel_year,
                    olevel_index_number=tpl.olevel_index_number,
                    olevel_school=tpl.olevel_school,
                    alevel_year=tpl.alevel_year,
                    alevel_index_number=tpl.alevel_index_number,
                    alevel_school=tpl.alevel_school,
                    alevel_combination=tpl.alevel_combination,
                    source=Application.SOURCE_PORTAL,
                    status="accepted",
                    application_reference=ref,
                    is_direct_entry=False,
                )
                application.programs.set([program])
                admitted = AdmittedStudent.objects.create(
                    application=application,
                    student_id=STUDENT_ID,
                    study_mode="Weekend",
                    reg_no=REG_NO,
                    admitted_program=program,
                    admitted_batch=adm_batch,
                    admitted_campus=campus,
                    is_admitted=True,
                    student_user=user,
                )
                self.stdout.write(self.style.SUCCESS("Created AdmittedStudent %s" % STUDENT_ID))

            if not admitted.student_user_id:
                admitted.student_user = user
                admitted.save(update_fields=["student_user", "updated_at"])

            spe, spe_created = StudentProgrammeEnrollment.objects.update_or_create(
                student=admitted,
                defaults={
                    "program": program,
                    "program_batch": prog_batch,
                    "curriculum_version": curriculum_version,
                    "current_year_of_study": 2,
                    "current_term_number": 1,
                    "specialization": None,
                    "status": "enrolled",
                    "enrolled_at": timezone.now(),
                    "notes": TAG,
                },
            )
            action = "Created" if spe_created else "Updated"
            self.stdout.write(self.style.SUCCESS("%s StudentProgrammeEnrollment id=%s (Y2T1, enrolled)" % (action, spe.id)))

        if options["exercise_api"]:
            self._exercise_api(user)

    def _exercise_api(self, user):
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient

        from admissions.models import AdmittedStudent
        from Programs.models import StudentProgrammeEnrollment
        from Programs.specialization_rules import MSG_EARLY_SPECIALIZATION

        client = APIClient()
        client.force_authenticate(user=user)
        admitted = AdmittedStudent.objects.get(student_id=STUDENT_ID)
        spe = StudentProgrammeEnrollment.objects.get(student=admitted)

        def dump(title, response):
            self.stdout.write("")
            self.stdout.write("=== %s ===" % title)
            self.stdout.write("HTTP %s" % response.status_code)
            data = getattr(response, "data", None)
            if data is not None:
                self.stdout.write(repr(data))
            else:
                self.stdout.write(str(response.content[:800]))

        # —— 1) Before entry (Y2 T1) ——
        spe.current_year_of_study = 2
        spe.current_term_number = 1
        spe.specialization = None
        spe.save(update_fields=["current_year_of_study", "current_term_number", "specialization", "updated_at"])

        r = client.get("/api/program/my_enrollment/specializations")
        dump("GET specializations (Y2 T1, pre-entry)", r)

        r = client.get("/api/program/my_enrollment/expected_courses")
        dump("GET expected_courses (Y2 T1)", r)

        r = client.get("/api/program/student/available_courses")
        dump("GET available_courses (Y2 T1)", r)

        r = client.post(
            "/api/program/my_enrollment/select_specialization",
            {"specialization": "Accounting"},
            format="json",
        )
        dump("POST select_specialization Accounting (early — expect 400)", r)
        if r.status_code == 400 and getattr(r, "data", {}).get("detail") != MSG_EARLY_SPECIALIZATION:
            self.stdout.write(self.style.WARNING("Early-save message differs from MSG_EARLY_SPECIALIZATION constant."))

        # —— 2) At entry, no choice ——
        spe.current_year_of_study = 3
        spe.current_term_number = 1
        spe.specialization = None
        spe.save(update_fields=["current_year_of_study", "current_term_number", "specialization", "updated_at"])

        r = client.get("/api/program/my_enrollment/expected_courses")
        dump("GET expected_courses (Y3 T1, no spec — expect 400)", r)

        r = client.get("/api/program/student/available_courses")
        dump("GET available_courses (Y3 T1, no spec — expect 400)", r)

        r = client.get("/api/program/student/academic_tracker")
        dump("GET academic_tracker (Y3 T1, no spec)", r)

        # —— 3–5) Tracks ——
        for track in ("Accounting", "Marketing", "Management"):
            spe.specialization = None
            spe.save(update_fields=["specialization", "updated_at"])
            r = client.post(
                "/api/program/my_enrollment/select_specialization",
                {"specialization": track},
                format="json",
            )
            dump("POST select_specialization %s" % track, r)

            r = client.get("/api/program/my_enrollment/expected_courses")
            dump("GET expected_courses after %s" % track, r)

            codes = []
            if hasattr(r, "data") and isinstance(r.data, dict):
                for c in r.data.get("courses") or []:
                    if isinstance(c, dict) and c.get("code"):
                        codes.append(c["code"])
            self.stdout.write("Course codes: %s" % sorted(codes))

        # —— 7) Invalid ——
        spe.specialization = None
        spe.save(update_fields=["specialization", "updated_at"])
        r = client.post(
            "/api/program/my_enrollment/select_specialization",
            {"specialization": "Finance"},
            format="json",
        )
        dump("POST select_specialization Finance (invalid — expect 400)", r)

        admin = User.objects.filter(is_staff=True).first()
        if admin:
            client.logout()
            client.force_authenticate(user=admin)
            r = client.patch(
                "/api/program/admin/enrollment/%s" % spe.id,
                {"specialization": "NotATrack"},
                format="json",
            )
            dump("PATCH admin/enrollment invalid specialization (expect 400)", r)
        else:
            self.stdout.write(self.style.WARNING("No staff user — skipped admin PATCH validation test."))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("API exercise finished."))
