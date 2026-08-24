"""
Seed course-exemption requests at each pipeline stage for QA.

Creates one student + one exemption request per stage:
  HOD pending | Dean pending | AR pending | Accounts (ready to bill) | Billed | HOD rejected

Prerequisites:
  python manage.py seed_exemption_qa_students
  python manage.py migrate

Usage:
  python manage.py seed_exemption_pipeline_qa
  python manage.py seed_exemption_pipeline_qa --reset
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from admissions.exemption_services import (
    EXEMPTION_FORM_FEE_UGX,
    ensure_exemption_fee_heads,
)
from admissions.models import (
    AdmissionChangeRequest,
    AdmittedStudent,
    ExemptionRequestLine,
)
from admissions.student_accounts import DEFAULT_STUDENT_PASSWORD, ensure_student_portal_account
from payments.models import StudentTuitionPayment
from Programs.models import ProgramCurriculumLine

PREFIX = "EXMPL"
PASSWORD = DEFAULT_STUDENT_PASSWORD

# tag, label, hod, dean, ar, accounts, overall_status, line_decision
PIPELINE_CASES = (
    ("HODPEND", "Awaiting HOD review", "pending", "pending", "pending", "pending", "pending", "pending"),
    ("DEANPEND", "HOD done — awaiting Dean", "approved", "pending", "pending", "pending", "pending", "pending"),
    ("ARPEND", "Dean done — awaiting AR", "approved", "approved", "pending", "pending", "pending", "pending"),
    ("BILLRDY", "AR done — ready for Accounts", "approved", "approved", "approved", "pending", "approved", "approved"),
    ("BILLED", "Accounts billed", "approved", "approved", "approved", "billed", "approved", "approved"),
    ("HODREJ", "Rejected at HOD", "rejected", "pending", "pending", "pending", "rejected", "rejected"),
)


class Command(BaseCommand):
    help = "Create EXMPL students with exemption requests at each review stage."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help=f"Delete previous {PREFIX} students and their exemption requests.",
        )
        parser.add_argument(
            "--only",
            type=str,
            default="",
            help="Create only one pipeline case tag, e.g. HODPEND, DEANPEND, ARPEND.",
        )

    def handle(self, *args, **options):
        admin = (
            User.objects.filter(is_superuser=True).order_by("id").first()
            or User.objects.order_by("id").first()
        )
        if not admin:
            raise CommandError("No staff user found.")

        template = (
            AdmittedStudent.objects.filter(
                is_admitted=True,
                accounts_registration_cleared=True,
                reg_no__startswith="EXMQA-",
            )
            .select_related(
                "admitted_program",
                "admitted_campus",
                "programme_enrollment",
                "programme_enrollment__curriculum_version",
            )
            .order_by("id")
            .first()
        )
        if template is None:
            raise CommandError(
                "No EXMQA student found. Run: python manage.py seed_exemption_qa_students"
            )

        if options["reset"]:
            self._reset()

        only_tag = (options.get("only") or "").strip().upper()
        cases = PIPELINE_CASES
        if only_tag:
            cases = tuple(c for c in PIPELINE_CASES if c[0] == only_tag)
            if not cases:
                tags = ", ".join(c[0] for c in PIPELINE_CASES)
                raise CommandError(f"Unknown --only tag {only_tag!r}. Choose one of: {tags}")

        form_head, _ = ensure_exemption_fee_heads()
        now = timezone.now()
        ts = now.strftime("%m%d%H%M")
        created = []

        with transaction.atomic():
            for i, case in enumerate(cases):
                tag, label, hod, dean, ar, accounts, overall, line_dec = case
                reg_no = f"{PREFIX}-{tag}-{ts}{i:02d}"[:100]
                student = self._clone_student(template, reg_no, tag, label, admin, i, ts)
                ensure_student_portal_account(student)
                user = student.student_user
                if user is not None:
                    user.set_password(PASSWORD)
                    user.must_change_password = False
                    user.is_active = True
                    user.is_student = True
                    user.save(update_fields=["password", "must_change_password", "is_active", "is_student"])

                charge = StudentTuitionPayment.objects.create(
                    student=student,
                    source="ad_hoc",
                    fee_head=form_head,
                    label="Exemption application form fee",
                    amount=EXEMPTION_FORM_FEE_UGX,
                    currency="UGX",
                    status="completed",
                    payment_method="mobile_money",
                    payment_reference=f"EXMPL-SEED-{tag}-{ts}",
                    notes="Seeded paid exemption form fee for pipeline QA.",
                    charged_by=admin,
                    semester=None,
                )

                req = AdmissionChangeRequest.objects.create(
                    admitted_student=student,
                    requested_by=user or admin,
                    current_program=student.admitted_program,
                    current_campus=student.admitted_campus,
                    current_study_mode=student.study_mode or "D",
                    change_type="exemption",
                    reason=f"Pipeline QA — {label}. Prior credit at Uganda Management Institute (2019/2020).",
                    form_fee_charge=charge,
                    form_fee_paid_at=now,
                    exemption_attained_at="Uganda Management Institute",
                    exemption_academic_years="2019/2020",
                    exemption_is_alumnus=(i % 2 == 0),
                    status=overall,
                    hod_status=hod,
                    dean_status=dean,
                    ar_status=ar,
                    accounts_status=accounts,
                    reviewed_by=admin if hod != "pending" else None,
                    reviewed_at=now if hod != "pending" else None,
                    hod_reviewed_by=admin if hod != "pending" else None,
                    hod_reviewed_at=now if hod != "pending" else None,
                    hod_notes="Seeded HOD decision." if hod != "pending" else "",
                    dean_reviewed_by=admin if dean != "pending" else None,
                    dean_reviewed_at=now if dean != "pending" else None,
                    dean_notes="Seeded Dean approval." if dean == "approved" else "",
                    ar_reviewed_by=admin if ar != "pending" else None,
                    ar_reviewed_at=now if ar != "pending" else None,
                    ar_notes="Seeded AR approval." if ar == "approved" else "",
                    accounts_reviewed_by=admin if accounts == "billed" else None,
                    accounts_reviewed_at=now if accounts == "billed" else None,
                )

                lines = self._curriculum_lines(student)[:2]
                if len(lines) < 1:
                    raise CommandError(
                        f"No curriculum lines on {student.admitted_program}. "
                        "Run: python manage.py seed_exemption_qa_students --curriculum-only"
                    )
                for line in lines:
                    cat = line.catalog_course
                    hod_line = "approved" if hod == "approved" else ("rejected" if hod == "rejected" else "pending")
                    if line_dec == "rejected":
                        hod_line = "rejected"
                    dean_line = "pending"
                    ar_line = "pending"
                    if hod_line == "approved":
                        if dean in ("approved", "rejected"):
                            dean_line = dean
                        if dean == "approved" and ar in ("approved", "rejected"):
                            ar_line = ar
                    ExemptionRequestLine.objects.create(
                        change_request=req,
                        curriculum_line=line,
                        course_code=(cat.code if cat else "EXMPL101")[:40],
                        course_name=((cat.title if cat else "Seeded paper") or "")[:255],
                        year_of_study=line.year_of_study,
                        term_number=line.term_number,
                        score_obtained="75",
                        decision=hod_line,
                        dean_decision=dean_line,
                        ar_decision=ar_line,
                    )

                created.append(
                    {
                        "reg_no": student.reg_no,
                        "label": label,
                        "request_id": req.id,
                        "hod": hod,
                        "dean": dean,
                        "ar": ar,
                        "accounts": accounts,
                        "alumnus": req.exemption_is_alumnus,
                    }
                )

        self.stdout.write(self.style.SUCCESS(f"Created {len(created)} pipeline QA student(s)."))
        self.stdout.write(f"Portal password: {PASSWORD}")
        self.stdout.write("")
        self.stdout.write(f"{'Stage':<34} {'Reg no (login)':<28} {'Req#':<6} Alumni rate")
        for row in created:
            rate = "100k" if row["alumnus"] else "150k"
            self.stdout.write(
                f"{row['label']:<34} {row['reg_no']:<28} {row['request_id']:<6} {rate}"
            )
        self.stdout.write("")
        self.stdout.write("Admin test path (/admin/course-exemptions):")
        self.stdout.write("  HOD tab -> Pending: EXMPL-HODPEND-*")
        self.stdout.write("  Dean tab -> Pending: EXMPL-DEANPEND-*")
        self.stdout.write("  AR tab -> Pending: EXMPL-ARPEND-*")
        self.stdout.write("  Accounts tab -> Pending: EXMPL-BILLRDY-* (100k or 150k per paper)")
        self.stdout.write("  Accounts tab -> Billed: EXMPL-BILLED-*")

    def _reset(self):
        qs = AdmittedStudent.objects.filter(reg_no__startswith=f"{PREFIX}-")
        n = qs.count()
        AdmissionChangeRequest.objects.filter(
            admitted_student__in=qs, change_type="exemption"
        ).delete()
        qs.delete()
        self.stdout.write(self.style.WARNING(f"Removed {n} previous {PREFIX} student(s)."))

    def _curriculum_lines(self, student: AdmittedStudent):
        try:
            version = student.programme_enrollment.curriculum_version
        except Exception:
            version = None
        program = student.admitted_program
        qs = ProgramCurriculumLine.objects.filter(is_active=True)
        if version is not None:
            qs = qs.filter(curriculum_version=version)
        elif program is not None:
            qs = qs.filter(program=program)
        return list(
            qs.filter(year_of_study__in=[1, 2])
            .select_related("catalog_course")
            .order_by("year_of_study", "term_number", "sort_order")[:4]
        )

    def _clone_student(
        self,
        template: AdmittedStudent,
        reg_no: str,
        tag: str,
        label: str,
        admin: User,
        index: int,
        ts: str,
    ) -> AdmittedStudent:
        from admissions.models import Application, ApplicationProgramChoice
        from Programs.models import StudentProgrammeEnrollment

        app = template.application
        applicant = User.objects.create_user(
            username=f"{PREFIX.lower()}.{tag.lower()}.{index}.{ts}"[:150],
            email=f"{PREFIX.lower()}.{tag.lower()}.{index}.{ts}@example.test",
            password=PASSWORD,
            first_name=app.first_name or "Pipeline",
            last_name=tag.title(),
            is_applicant=True,
            is_student=False,
            is_active=True,
        )
        new_app = Application.objects.create(
            applicant=applicant,
            batch=app.batch,
            campus=app.campus,
            academic_level=app.academic_level,
            first_name=app.first_name or "Pipeline",
            last_name=tag.title(),
            date_of_birth=app.date_of_birth or date(2000, 1, 1),
            gender=app.gender or "Female",
            nationality=app.nationality or "Ugandan",
            phone=app.phone or "+256700000001",
            email=applicant.email,
            next_of_kin_name=app.next_of_kin_name or "Kin",
            next_of_kin_contact=app.next_of_kin_contact or "+256700000002",
            next_of_kin_relationship=app.next_of_kin_relationship or "Parent",
            olevel_year=app.olevel_year or 2018,
            olevel_index_number=f"{PREFIX}/{tag}/2018",
            olevel_school=app.olevel_school or "Test School",
            has_olevel=True,
            has_alevel=False,
            status="accepted",
            application_fee_paid=True,
            application_reference=f"{PREFIX}-{tag}-{ts}-{index}"[:50],
            source=app.source,
        )
        if template.admitted_program_id:
            ApplicationProgramChoice.objects.create(
                application=new_app,
                program=template.admitted_program,
                choice_order=1,
            )

        now = timezone.now()
        student_id = f"8{reg_no[-9:]}"[:50]
        if AdmittedStudent.objects.filter(student_id=student_id).exists():
            student_id = f"8{index:02d}{reg_no[-7:]}"[:50]

        student = AdmittedStudent.objects.create(
            application=new_app,
            student_id=student_id,
            reg_no=reg_no,
            study_mode=template.study_mode or "D",
            admitted_program=template.admitted_program,
            admitted_batch=template.admitted_batch,
            admitted_campus=template.admitted_campus,
            is_admitted=True,
            admission_notes=f"Pipeline QA — {label}",
            admitted_by=admin,
            intended_program_batch=template.intended_program_batch,
            admission_fee_paid=True,
            admission_fee_paid_at=now,
            registration_tuition_pct_met=True,
            registration_tuition_pct_at=now,
            accounts_registration_cleared=True,
            accounts_registration_cleared_at=now,
            accounts_registration_cleared_by=admin,
            physical_documents_verified=True,
            physical_documents_verified_at=now,
            physical_documents_verified_by=admin,
        )

        try:
            enr = template.programme_enrollment
            StudentProgrammeEnrollment.objects.update_or_create(
                student=student,
                defaults={
                    "program": enr.program,
                    "program_batch": enr.program_batch,
                    "curriculum_version": enr.curriculum_version,
                    "current_year_of_study": enr.current_year_of_study or 1,
                    "current_term_number": enr.current_term_number or 1,
                    "entry_year_of_study": 1,
                    "entry_term_number": 1,
                    "status": "enrolled",
                    "enrolled_by": admin,
                    "enrolled_at": now,
                    "notes": f"EXMPL pipeline seed ({tag}).",
                },
            )
        except Exception:
            pass
        return student
