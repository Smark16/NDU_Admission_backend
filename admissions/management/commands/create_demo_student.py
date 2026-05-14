"""
Create a new demo admitted student (applicant user + application + AdmittedStudent).

Use for local QA or when you need a fresh student row without using the UI.
"""
from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import User, Campus
from admissions.models import AcademicLevel, AdmittedStudent, Application, Batch
from admissions.utils.batch_offer_filters import batch_offer_window_q
from admissions.student_accounts import ensure_student_portal_account
from Programs.models import Program, ProgramBatch


class Command(BaseCommand):
    help = (
        "Create one demo applicant + accepted application + admitted student "
        "(optional portal account). Uses the first suitable batch, campus, and programme."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--first-name",
            default="Demo",
            help="Applicant first name (default: Demo).",
        )
        parser.add_argument(
            "--last-name",
            default="Student",
            help="Applicant last name (default: Student).",
        )
        parser.add_argument(
            "--skip-portal-account",
            action="store_true",
            help="Do not create/link the student portal User (reg_no login).",
        )

    def handle(self, *args, **options):
        first = options["first_name"].strip() or "Demo"
        last = options["last_name"].strip() or "Student"
        skip_portal = options["skip_portal_account"]

        batch = (
            Batch.objects.filter(is_active=True)
            .filter(batch_offer_window_q())
            .order_by("-id")
            .first()
            or Batch.objects.order_by("-id").first()
        )
        if not batch:
            raise CommandError("No admissions Batch found. Create an intake batch first.")

        campus = Campus.objects.order_by("id").first()
        if not campus:
            raise CommandError("No Campus found.")

        program = Program.objects.filter(is_active=True).order_by("id").first()
        if not program:
            raise CommandError("No active Programme found.")

        academic_level = program.academic_level_id and program.academic_level
        if not academic_level:
            academic_level = AcademicLevel.objects.order_by("id").first()
        if not academic_level:
            raise CommandError("No AcademicLevel found.")

        admin_user = User.objects.filter(is_superuser=True).order_by("id").first() or User.objects.order_by(
            "id"
        ).first()
        if not admin_user:
            raise CommandError("No User found to set as admitted_by.")

        ts = timezone.now().strftime("%Y%m%d%H%M%S")
        email = f"demo.student.{ts}@example.test"
        username = email

        ipb = (
            ProgramBatch.objects.filter(program=program, is_active=True)
            .order_by("-start_date", "name")
            .first()
        )

        reg_no = f"DEMO-{ts}"[:100]
        student_id = (f"9{ts}"[-10:]).ljust(10, "0")[:50]
        if AdmittedStudent.objects.filter(reg_no=reg_no).exists():
            raise CommandError(f"reg_no collision: {reg_no}")
        if AdmittedStudent.objects.filter(student_id=student_id).exists():
            student_id = f"9{ts[-9:]}"[:50]

        with transaction.atomic():
            applicant = User.objects.create_user(
                username=username,
                email=email,
                password="DemoStudent@123",
                first_name=first,
                last_name=last,
                is_applicant=True,
                is_student=False,
                is_active=True,
            )

            app = Application.objects.create(
                applicant=applicant,
                batch=batch,
                campus=campus,
                academic_level=academic_level,
                first_name=first,
                last_name=last,
                middle_name="",
                date_of_birth=date(2000, 1, 15),
                gender="Male",
                nationality="Ugandan",
                phone=f"+2567{ts[-8:]}",
                email=email,
                next_of_kin_name="Demo Next Of Kin",
                next_of_kin_contact="+256700000000",
                next_of_kin_relationship="Parent",
                olevel_year=2018,
                olevel_index_number=f"DEMO/{ts}/2018",
                olevel_school="Demo Secondary School",
                has_olevel=True,
                has_alevel=False,
                alevel_year=0,
                alevel_index_number="",
                alevel_school="",
                alevel_combination="",
                status="accepted",
                application_fee_paid=True,
            )
            app.programs.set([program])

            admission = AdmittedStudent.objects.create(
                application=app,
                student_id=student_id,
                reg_no=reg_no,
                study_mode="D",
                admitted_program=program,
                admitted_batch=batch,
                admitted_campus=campus,
                is_admitted=True,
                admission_notes="Created by create_demo_student management command.",
                admitted_by=admin_user,
                intended_program_batch=ipb,
            )

        if not skip_portal:
            ensure_student_portal_account(admission)

        self.stdout.write(self.style.SUCCESS("Demo student created."))
        self.stdout.write(f"  Application id: {app.id}")
        self.stdout.write(f"  Admission id:   {admission.id}")
        self.stdout.write(f"  Applicant login: {email} / DemoStudent@123")
        self.stdout.write(f"  Reg no:          {reg_no}")
        self.stdout.write(f"  Student id:      {student_id}")
        self.stdout.write(f"  Programme:      {program.code} — {program.name}")
        self.stdout.write(f"  Intake batch:    {batch.name} (id={batch.id})")
        if ipb:
            self.stdout.write(f"  Intended ProgramBatch: {ipb.name} (id={ipb.id})")
        else:
            self.stdout.write("  Intended ProgramBatch: (none — auto-assign on enroll)")
        self.stdout.write(f"  Admit form URL (dev): /admin/admit_student/{app.id}")
