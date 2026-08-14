"""
Seed admitted students for Bonafide / Accounts student-list QA.

Creates several personas so you can test work-queue badges, Accounts Clear,
and the accounts_registration_cleared email (Celery) from the UI.

  python manage.py seed_accounts_clearance_qa_students
  python manage.py seed_accounts_clearance_qa_students --email you@ndu.ac.ug
  python manage.py seed_accounts_clearance_qa_students --reset

Do not send clearance emails from this command — clear a student in
/admin/students/bonafide so Celery delivers the real mail.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import User, Campus
from admissions.models import (
    AcademicLevel,
    AdmittedStudent,
    Application,
    ApplicationProgramChoice,
    Batch,
)
from admissions.student_accounts import ensure_student_portal_account
from admissions.utils.batch_offer_filters import batch_offer_window_q
from Programs.models import Program, ProgramBatch


PREFIX = "LISTQA"
PERSONAS = (
    ("awaiting_accounts", "Awaiting Accounts", True, True, False, False),
    ("awaiting_accounts", "Awaiting Accounts", True, True, False, False),
    ("awaiting_accounts", "Awaiting Accounts", True, True, False, False),
    ("awaiting_accounts", "Awaiting Accounts", True, True, False, False),
    ("awaiting_ar", "Accounts done — AR docs pending", True, True, True, False),
    ("awaiting_ar", "Accounts done — AR docs pending", True, True, True, False),
    ("fully_done", "Accounts + AR complete", True, True, True, True),
    ("fully_done", "Accounts + AR complete", True, True, True, True),
    ("unpaid", "Not yet bonafide (unpaid commitment)", False, False, False, False),
    ("unpaid", "Not yet bonafide (unpaid commitment)", False, False, False, False),
)

FIRST_NAMES = [
    "Aisha",
    "Brian",
    "Christine",
    "Daniel",
    "Esther",
    "Francis",
    "Grace",
    "Hassan",
    "Irene",
    "Joseph",
]
LAST_NAMES = [
    "Namukasa",
    "Okello",
    "Nabirye",
    "Mugisha",
    "Atim",
    "Kato",
    "Nalwoga",
    "Ocen",
    "Akello",
    "Ssekandi",
]


class Command(BaseCommand):
    help = (
        "Create LISTQA admitted students for the student list: awaiting Accounts, "
        "awaiting AR, fully done, and unpaid. Use --email so clearance mail hits your inbox."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            default="",
            help="Put this address on every seeded application (so Clear emails reach you).",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete previous LISTQA students (and their applicant users) first.",
        )
        parser.add_argument(
            "--skip-portal-account",
            action="store_true",
            help="Do not create student portal users.",
        )
        parser.add_argument(
            "--no-skip-tuition",
            action="store_true",
            help=(
                "Do not set RegistrationSettings.skip_tuition_check. "
                "Clear in the UI will fail if there is no current-term fee schedule."
            ),
        )
        parser.add_argument(
            "--program-id",
            type=int,
            default=None,
            help="Admit into this programme PK (default: first active programme).",
        )

    def handle(self, *args, **options):
        notify_email = (options["email"] or "").strip()
        skip_portal = options["skip_portal_account"]
        no_skip_tuition = options["no_skip_tuition"]
        program_id = options["program_id"]

        if options["reset"]:
            self._reset_previous()

        batch, campus, program, academic_level, admin_user = self._lookups(program_id)
        ipb = (
            ProgramBatch.objects.filter(program=program, is_active=True)
            .order_by("-start_date", "name")
            .first()
        )

        if not no_skip_tuition:
            self._enable_skip_tuition()

        ts = timezone.now().strftime("%Y%m%d%H%M%S")
        created = []

        with transaction.atomic():
            for i, persona in enumerate(PERSONAS):
                key, label, fee_paid, tuition_met, accounts_cleared, docs_ok = persona
                row = self._create_one(
                    index=i,
                    ts=ts,
                    persona_key=key,
                    persona_label=label,
                    fee_paid=fee_paid,
                    tuition_met=tuition_met,
                    accounts_cleared=accounts_cleared,
                    docs_ok=docs_ok,
                    notify_email=notify_email,
                    batch=batch,
                    campus=campus,
                    program=program,
                    academic_level=academic_level,
                    admin_user=admin_user,
                    ipb=ipb,
                    skip_portal=skip_portal,
                )
                created.append(row)

        self.stdout.write(self.style.SUCCESS(f"Created {len(created)} LISTQA students."))
        self.stdout.write("Search the student list for: LISTQA")
        self.stdout.write("")
        self.stdout.write(
            f"{'Persona':<38} {'Reg no':<22} {'Email':<36} Clear?"
        )
        for row in created:
            self.stdout.write(
                f"{row['label']:<38} {row['reg_no']:<22} {row['email']:<36} "
                f"{'YES — use this for email' if row['key'] == 'awaiting_accounts' else 'no'}"
            )
        self.stdout.write("")
        self.stdout.write("How to test the Accounts clearance email:")
        self.stdout.write("  1. Open /admin/students/bonafide (work-queue sort).")
        self.stdout.write("  2. Filter or search LISTQA — awaiting Accounts sit at the top.")
        self.stdout.write("  3. Open a LISTQA-Awaiting Accounts student and click Clear.")
        self.stdout.write("  4. Keep a Celery worker running so the mail is sent.")
        if notify_email:
            self.stdout.write(f"  5. Inbox: {notify_email}")
        else:
            self.stdout.write(
                "  Tip: re-run with --email you@ndu.ac.ug so mail is not sent to @example.test"
            )
        if not no_skip_tuition:
            self.stdout.write(
                "  Note: skip_tuition_check is ON so Clear is not blocked by missing fee schedules."
            )

    def _lookups(self, program_id):
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

        if program_id:
            program = (
                Program.objects.filter(pk=program_id, is_active=True).first()
                or Program.objects.filter(pk=program_id).first()
            )
            if not program:
                raise CommandError(f"No programme with id={program_id}.")
        else:
            program = Program.objects.filter(is_active=True).order_by("id").first()
            if not program:
                raise CommandError("No active Programme found.")

        academic_level = program.academic_level_id and program.academic_level
        if not academic_level:
            academic_level = AcademicLevel.objects.order_by("id").first()
        if not academic_level:
            raise CommandError("No AcademicLevel found.")

        admin_user = (
            User.objects.filter(is_superuser=True).order_by("id").first()
            or User.objects.order_by("id").first()
        )
        if not admin_user:
            raise CommandError("No User found to set as admitted_by.")

        return batch, campus, program, academic_level, admin_user

    def _enable_skip_tuition(self):
        from payments.models import RegistrationSettings

        settings = RegistrationSettings.get_settings()
        if settings.skip_tuition_check:
            return
        settings.skip_tuition_check = True
        settings.save(update_fields=["skip_tuition_check"])
        self.stdout.write(
            self.style.WARNING(
                "RegistrationSettings.skip_tuition_check set to True so Accounts Clear works locally."
            )
        )

    def _reset_previous(self):
        qs = AdmittedStudent.objects.filter(reg_no__startswith=f"{PREFIX}-")
        n = qs.count()
        applicant_ids = list(
            qs.values_list("application__applicant_id", flat=True)
        )
        app_ids = list(qs.values_list("application_id", flat=True))
        qs.delete()
        Application.objects.filter(pk__in=app_ids).delete()
        User.objects.filter(pk__in=[i for i in applicant_ids if i]).delete()
        User.objects.filter(username__startswith=f"{PREFIX.lower()}.").delete()
        self.stdout.write(self.style.WARNING(f"Removed {n} previous {PREFIX} student(s)."))

    def _create_one(
        self,
        *,
        index,
        ts,
        persona_key,
        persona_label,
        fee_paid,
        tuition_met,
        accounts_cleared,
        docs_ok,
        notify_email,
        batch,
        campus,
        program,
        academic_level,
        admin_user,
        ipb,
        skip_portal,
    ):
        first = FIRST_NAMES[index % len(FIRST_NAMES)]
        last = LAST_NAMES[index % len(LAST_NAMES)]
        suffix = f"{ts}{index:02d}"
        default_email = f"{PREFIX.lower()}.{persona_key}.{suffix}@example.test"
        email = notify_email or default_email
        username = f"{PREFIX.lower()}.{persona_key}.{suffix}"[:150]
        if User.objects.filter(username=username).exists():
            username = f"{username}.{index}"[:150]

        applicant = User.objects.create_user(
            username=username,
            email=email,
            password="ListQa@123",
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
            middle_name=persona_key.replace("_", " "),
            date_of_birth=date(2001, 3, 12) + timedelta(days=index),
            gender="Female" if index % 2 else "Male",
            nationality="Ugandan",
            phone=f"+2567{suffix[-8:]}",
            email=email,
            next_of_kin_name=f"{last} Next of Kin",
            next_of_kin_contact="+256700000111",
            next_of_kin_relationship="Parent",
            olevel_year=2019,
            olevel_index_number=f"{PREFIX}/{suffix}/2019",
            olevel_school="LISTQA Secondary School",
            has_olevel=True,
            has_alevel=False,
            alevel_year=0,
            alevel_index_number="",
            alevel_school="",
            alevel_combination="",
            status="accepted",
            application_fee_paid=True,
            application_reference=f"{PREFIX}-{suffix}"[:50],
            source=Application.SOURCE_DIRECT,
        )
        ApplicationProgramChoice.objects.create(
            application=app,
            program=program,
            choice_order=1,
        )

        now = timezone.now()
        reg_no = f"{PREFIX}-{persona_key[:8].upper()}-{suffix[-8:]}"[:100]
        student_id = f"8{suffix[-9:]}"[:50]
        if AdmittedStudent.objects.filter(student_id=student_id).exists():
            student_id = f"8{suffix[-8:]}{index}"[:50]

        admission = AdmittedStudent.objects.create(
            application=app,
            student_id=student_id,
            reg_no=reg_no,
            study_mode="D",
            admitted_program=program,
            admitted_batch=batch,
            admitted_campus=campus,
            is_admitted=True,
            admission_notes=f"Seeded for student-list QA ({persona_label}).",
            admitted_by=admin_user,
            intended_program_batch=ipb,
            admission_fee_paid=fee_paid,
            admission_fee_paid_at=now if fee_paid else None,
            registration_tuition_pct_met=tuition_met,
            registration_tuition_pct_at=now if tuition_met else None,
            accounts_registration_cleared=accounts_cleared,
            accounts_registration_cleared_at=now if accounts_cleared else None,
            accounts_registration_cleared_by=admin_user if accounts_cleared else None,
            physical_documents_verified=docs_ok,
            physical_documents_verified_at=now if docs_ok else None,
            physical_documents_verified_by=admin_user if docs_ok else None,
        )

        if not skip_portal:
            ensure_student_portal_account(admission)

        return {
            "key": persona_key,
            "label": persona_label,
            "reg_no": admission.reg_no,
            "email": email,
            "id": admission.id,
        }
