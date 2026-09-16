"""
Seed admitted students with known tuition-payment percentages for e-voting import QA.

  python manage.py seed_voter_import_qa
  python manage.py seed_voter_import_qa --reset

Portal login: registration number / NDU@1234

Percentages are of a 1,000,000 UGX current-term tuition bill:
  20, 40, 50, 60, 80, 100  (on each available campus)

Import from ERP uses RegistrationSettings.min_tuition_payment_percentage
(the Student course registration portal gate). Change that setting, then import again.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import Campus, User
from admissions.models import (
    AcademicLevel,
    AdmittedStudent,
    Application,
    ApplicationProgramChoice,
    Batch,
)
from admissions.student_accounts import DEFAULT_STUDENT_PASSWORD, ensure_student_portal_account
from admissions.utils.batch_offer_filters import batch_offer_window_q
from payments.models import RegistrationSettings, StudentTuitionPayment
from payments.registration_eligibility import student_meets_min_tuition_pct
from payments.student_payment_allocation import tuition_registration_totals
from payments.tuition_pct_cache import refresh_student_tuition_pct_cache
from Programs.models import Program, ProgramBatch, Semester, StudentProgrammeEnrollment


PREFIX = "VOTEQA"
LETTER_PREFIX = "VOTEQA-LTR"
TUITION_AMOUNT = Decimal("1000000.00")
PERCENTAGES = (20, 40, 50, 60, 80, 100)
FIRST_NAMES = ["Aisha", "Brian", "Cathy", "Daniel", "Eva", "Francis"]
LAST_NAMES = ["Nambi", "Okello", "Nakato", "Mugisha", "Akello", "Ssebunya"]

# Alternate ERP formats (letter stream + Inservice mode I)
# YY/1|2|3/A|B|C/NNN/MODE/NNN|NNNN|NNNNN
LETTER_FORMAT_STUDENTS = (
    # Explicit cases requested for import testing
    {"tag": "1B5", "reg_no": "26/1/B/110/D/20572", "campus_digit": "1", "pct": 100},
    {"tag": "2B5", "reg_no": "26/2/B/110/D/20572", "campus_digit": "2", "pct": 100},
    {"tag": "3A5", "reg_no": "26/3/A/110/D/20572", "campus_digit": "3", "pct": 100},
    # Extra coverage: letter A/C + serial length 3 / 4 / 5
    {"tag": "1C3", "reg_no": "26/1/C/110/D/205", "campus_digit": "1", "pct": 100},
    {"tag": "2A4", "reg_no": "26/2/A/110/D/2057", "campus_digit": "2", "pct": 100},
    {"tag": "3C5", "reg_no": "26/3/C/110/W/12345", "campus_digit": "3", "pct": 100},
    # Inservice (I) — classic + letter stream
    {"tag": "2I4", "reg_no": "26/2/110/I/3445", "campus_digit": "2", "pct": 100},
    {"tag": "2BI4", "reg_no": "26/2/B/110/I/5566", "campus_digit": "2", "pct": 100},
)


class Command(BaseCommand):
    help = (
        "Create VOTEQA students at 20/40/50/60/80/100% tuition for voter-import testing, "
        "plus letter-block reg nos (YY/campus/A|B|C/...) for format-rejection tests."
    )

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete previous VOTEQA students first.")
        parser.add_argument("--program-id", type=int, default=None)
        parser.add_argument(
            "--letter-only",
            action="store_true",
            help="Only seed letter-format reg nos (skip classic VOTEQA % ladder).",
        )

    def handle(self, *args, **options):
        if options["reset"]:
            self._reset_previous()

        batch, program, academic_level, admin_user, campuses = self._lookups(options["program_id"])
        ipb, semester = self._ensure_cohort(program)
        rule = self._ensure_tuition_rule(program, ipb, semester, admin_user)
        campus_by_digit = self._campus_by_digit(campuses)

        created = []
        with transaction.atomic():
            if not options["letter_only"]:
                for campus_index, campus in enumerate(campuses):
                    digit = self._campus_digit(campus)
                    for i, pct in enumerate(PERCENTAGES):
                        created.append(
                            self._upsert_student(
                                campus=campus,
                                campus_digit=digit,
                                campus_index=campus_index,
                                pct=pct,
                                name_index=i,
                                batch=batch,
                                program=program,
                                academic_level=academic_level,
                                admin_user=admin_user,
                                ipb=ipb,
                                semester=semester,
                                rule=rule,
                            )
                        )

            for i, spec in enumerate(LETTER_FORMAT_STUDENTS):
                campus = campus_by_digit.get(spec["campus_digit"]) or campuses[0]
                created.append(
                    self._upsert_letter_student(
                        spec=spec,
                        name_index=i,
                        campus=campus,
                        batch=batch,
                        program=program,
                        academic_level=academic_level,
                        admin_user=admin_user,
                        ipb=ipb,
                        semester=semester,
                        rule=rule,
                    )
                )

        settings = RegistrationSettings.get_settings()
        threshold = float(settings.min_tuition_payment_percentage or 0)
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(created)} VOTEQA student(s)."))
        self.stdout.write(
            f"ERP course-registration threshold: {threshold}% "
            f"(skip_tuition_check={settings.skip_tuition_check})"
        )
        self.stdout.write(f"Current-term tuition bill used: UGX {TUITION_AMOUNT:,.0f}")
        self.stdout.write(f"Portal password: {DEFAULT_STUDENT_PASSWORD}")
        self.stdout.write("")
        self.stdout.write(
            f"{'Reg no / login':<28} {'Campus':<18} {'Paid %':<8} {'Meets now?':<12} Paid / Required"
        )
        for row in created:
            student = row["student"]
            totals = tuition_registration_totals(student, current_term_only=True)
            meets = student_meets_min_tuition_pct(student, threshold)
            refresh_student_tuition_pct_cache(student)
            self.stdout.write(
                f"{row['reg_no']:<28} {row['campus']:<18} {row['pct']:<8} "
                f"{'YES - import' if meets else 'no':<12} "
                f"{float(totals['total_paid_on_tuition']):,.0f} / "
                f"{float(totals['total_required']):,.0f}"
            )

        self.stdout.write("")
        self.stdout.write("How to test:")
        self.stdout.write("  1. HORIZON > Finance / Registration settings > set Minimum tuition % to 50 (or 40 / 60).")
        self.stdout.write("  2. In e-voting admin > Student Management > Import from ERP.")
        self.stdout.write("  3. Only students at or above that % are added. Change the % and import again.")
        self.stdout.write(
            "  4. Letter-format rows (…/A|B|C/…) should appear in ERP eligible list but fail myvote parse_regno on import."
        )
    def _lookups(self, program_id):
        batch = (
            Batch.objects.filter(is_active=True).filter(batch_offer_window_q()).order_by("-id").first()
            or Batch.objects.order_by("-id").first()
        )
        if not batch:
            raise CommandError("No admissions Batch found. Run ERP seed_data / seed_test_data first.")

        if program_id:
            program = Program.objects.filter(pk=program_id).first()
            if not program:
                raise CommandError(f"No programme with id={program_id}.")
        else:
            program = (
                Program.objects.filter(is_active=True, faculty__isnull=False).order_by("id").first()
                or Program.objects.filter(is_active=True).order_by("id").first()
            )
        if not program:
            raise CommandError("No Programme found.")

        academic_level = program.academic_level or AcademicLevel.objects.order_by("id").first()
        if not academic_level:
            raise CommandError("No AcademicLevel found.")

        admin_user = User.objects.filter(is_superuser=True).order_by("id").first() or User.objects.order_by("id").first()
        if not admin_user:
            raise CommandError("No User found.")

        campuses = list(Campus.objects.order_by("id")[:3])
        if not campuses:
            raise CommandError("No Campus found.")
        return batch, program, academic_level, admin_user, campuses

    def _campus_digit(self, campus: Campus) -> str:
        code = (campus.code or "").upper()
        name = (campus.name or "").upper()
        if code in {"KLA", "KAMPALA"} or "KAMPALA" in name:
            return "2"
        if code in {"3", "CAM3"} or "CAMPUS 3" in name or "ARUA" in name or "MBARARA" in name:
            return "3"
        return "1"

    def _campus_by_digit(self, campuses: list[Campus]) -> dict[str, Campus]:
        by_digit: dict[str, Campus] = {}
        for campus in campuses:
            digit = self._campus_digit(campus)
            by_digit.setdefault(digit, campus)
        # Campus digit 3 may not exist in ERP yet — fall back to main so the reg still imports from ERP eligible list.
        if "3" not in by_digit and campuses:
            by_digit["3"] = by_digit.get("1") or campuses[0]
        if "1" not in by_digit and campuses:
            by_digit["1"] = campuses[0]
        if "2" not in by_digit and campuses:
            by_digit["2"] = campuses[-1]
        return by_digit

    def _ensure_cohort(self, program: Program):
        today = timezone.now().date()
        ipb = (
            ProgramBatch.objects.filter(program=program, is_active=True)
            .order_by("-start_date", "name")
            .first()
        )
        if not ipb:
            ipb, _ = ProgramBatch.objects.get_or_create(
                program=program,
                name="VOTEQA Cohort",
                defaults={
                    "academic_year": "2026/2027",
                    "start_date": today - timedelta(days=30),
                    "end_date": today + timedelta(days=365),
                    "is_active": True,
                },
            )
        semester = (
            ipb.semesters.filter(year_of_study=1, term_number=1).first()
            or ipb.semesters.order_by("order", "id").first()
        )
        if not semester:
            semester = Semester.objects.create(
                program_batch=ipb,
                name="Year 1 Semester 1",
                order=1,
                year_of_study=1,
                term_number=1,
                start_date=today - timedelta(days=30),
                end_date=today + timedelta(days=150),
                is_active=True,
            )
        elif semester.year_of_study is None or semester.term_number is None:
            semester.year_of_study = semester.year_of_study or 1
            semester.term_number = semester.term_number or 1
            semester.save(update_fields=["year_of_study", "term_number", "updated_at"])
        return ipb, semester

    def _ensure_tuition_rule(self, program, ipb, semester, admin_user):
        from payments.batch_semester_fee_helpers import get_or_create_tuition_fee_plan, tuition_head

        plan = get_or_create_tuition_fee_plan(program)
        head = tuition_head()
        rule = (
            plan.rules.filter(program_batch=ipb, semester=semester, fee_head=head).first()
            or plan.rules.filter(program_batch=ipb, fee_head=head).first()
        )
        if rule:
            if (rule.amount or 0) <= 0:
                rule.amount = TUITION_AMOUNT
                rule.currency = "UGX"
                rule.is_active = True
                rule.save(update_fields=["amount", "currency", "is_active", "updated_at"])
            return rule
        from payments.models import FeePlanRule

        return FeePlanRule.objects.create(
            fee_plan=plan,
            fee_head=head,
            trigger_stage="semester_start",
            program=program,
            program_batch=ipb,
            semester=semester,
            amount=TUITION_AMOUNT,
            currency="UGX",
            payable_year_of_study=1,
            payable_term_number=1,
            billing_date=timezone.now().date() - timedelta(days=7),
            is_active=True,
            order=1,
        )

    def _upsert_student(
        self,
        *,
        campus,
        campus_digit,
        campus_index,
        pct,
        name_index,
        batch,
        program,
        academic_level,
        admin_user,
        ipb,
        semester,
        rule,
    ):
        student_id = f"{PREFIX}-{campus_digit}-{pct}"
        seq = 900 + campus_index * 10 + (pct // 10)
        reg_no = f"26/{campus_digit}/328/D/{seq:03d}"
        first = FIRST_NAMES[name_index % len(FIRST_NAMES)]
        last = LAST_NAMES[name_index % len(LAST_NAMES)]
        email = f"{PREFIX.lower()}.{campus_digit}.{pct}@example.test"
        now = timezone.now()

        admission = AdmittedStudent.objects.filter(student_id=student_id).first()
        if admission is None:
            applicant = User.objects.create_user(
                username=f"{PREFIX.lower()}.{campus_digit}.{pct}"[:150],
                email=email,
                password=DEFAULT_STUDENT_PASSWORD,
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
                middle_name=f"{pct} percent",
                date_of_birth=date(2002, 1, 15),
                gender="Female" if name_index % 2 else "Male",
                nationality="Ugandan",
                phone=f"+25670{campus_digit}00{pct:02d}00",
                email=email,
                next_of_kin_name=f"{last} Next of Kin",
                next_of_kin_contact="+256700000333",
                next_of_kin_relationship="Parent",
                olevel_year=2020,
                olevel_index_number=f"{PREFIX}/{pct}/2020",
                olevel_school="VOTEQA Secondary",
                has_olevel=True,
                has_alevel=False,
                alevel_year=0,
                alevel_index_number="",
                alevel_school="",
                alevel_combination="",
                status="accepted",
                application_fee_paid=True,
                application_reference=f"{PREFIX}-{campus_digit}-{pct}"[:50],
                source=Application.SOURCE_DIRECT,
            )
            ApplicationProgramChoice.objects.create(application=app, program=program, choice_order=1)
            admission = AdmittedStudent.objects.create(
                application=app,
                student_id=student_id,
                reg_no=reg_no,
                study_mode="D",
                admitted_program=program,
                admitted_batch=batch,
                admitted_campus=campus,
                intended_program_batch=ipb,
                is_admitted=True,
                admission_fee_paid=True,
                admission_fee_paid_at=now,
                admitted_by=admin_user,
                admission_notes=f"VOTEQA voter import — {pct}% tuition paid.",
            )
        else:
            admission.reg_no = reg_no
            admission.admitted_campus = campus
            admission.admitted_program = program
            admission.intended_program_batch = ipb
            admission.is_admitted = True
            admission.admission_fee_paid = True
            admission.save()

        StudentProgrammeEnrollment.objects.update_or_create(
            student=admission,
            defaults={
                "program": program,
                "program_batch": ipb,
                "current_year_of_study": 1,
                "current_term_number": 1,
                "entry_year_of_study": 1,
                "entry_term_number": 1,
                "status": "enrolled",
                "enrolled_by": admin_user,
                "enrolled_at": now,
                "notes": f"{PREFIX} Y1T1 {pct}%",
            },
        )

        paid = (TUITION_AMOUNT * Decimal(pct) / Decimal("100")).quantize(Decimal("1.00"))
        StudentTuitionPayment.objects.update_or_create(
            student=admission,
            transaction_id=f"{PREFIX}-{campus_digit}-{pct}",
            defaults={
                "fee_plan_rule": rule,
                "semester": semester,
                "source": "scheduled",
                "amount": paid,
                "currency": "UGX",
                "payment_method": "cash",
                "status": "completed",
                "payment_reference": f"{PREFIX}-{pct}",
                "receipt_number": f"VOTEQA-RCP-{campus_digit}-{pct}",
                "paid_at": now,
                "is_waived": False,
            },
        )

        ensure_student_portal_account(admission)
        user = admission.student_user
        if user is not None:
            user.set_password(DEFAULT_STUDENT_PASSWORD)
            user.must_change_password = False
            user.is_active = True
            user.is_student = True
            user.save(update_fields=["password", "must_change_password", "is_active", "is_student"])

        return {
            "student": admission,
            "reg_no": admission.reg_no,
            "campus": campus.name,
            "pct": pct,
        }

    def _upsert_letter_student(
        self,
        *,
        spec,
        name_index,
        campus,
        batch,
        program,
        academic_level,
        admin_user,
        ipb,
        semester,
        rule,
    ):
        tag = spec["tag"]
        reg_no = spec["reg_no"]
        pct = int(spec["pct"])
        campus_digit = spec["campus_digit"]
        student_id = f"{LETTER_PREFIX}-{tag}"
        first = FIRST_NAMES[name_index % len(FIRST_NAMES)]
        last = LAST_NAMES[name_index % len(LAST_NAMES)]
        email = f"{LETTER_PREFIX.lower()}.{tag.lower()}@example.test"
        username = f"{LETTER_PREFIX.lower()}.{tag.lower()}"[:150]
        now = timezone.now()

        admission = AdmittedStudent.objects.filter(student_id=student_id).first()
        if admission is None:
            # Reg may already exist from a prior manual insert — reuse/update that row.
            admission = AdmittedStudent.objects.filter(reg_no__iexact=reg_no).first()

        if admission is None:
            applicant = User.objects.create_user(
                username=username,
                email=email,
                password=DEFAULT_STUDENT_PASSWORD,
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
                middle_name=f"letter {tag}",
                date_of_birth=date(2002, 3, 20),
                gender="Female" if name_index % 2 else "Male",
                nationality="Ugandan",
                phone=f"+25671{campus_digit}00{name_index:02d}00",
                email=email,
                next_of_kin_name=f"{last} Next of Kin",
                next_of_kin_contact="+256700000444",
                next_of_kin_relationship="Parent",
                olevel_year=2020,
                olevel_index_number=f"{LETTER_PREFIX}/{tag}/2020",
                olevel_school="VOTEQA Letter Secondary",
                has_olevel=True,
                has_alevel=False,
                alevel_year=0,
                alevel_index_number="",
                alevel_school="",
                alevel_combination="",
                status="accepted",
                application_fee_paid=True,
                application_reference=f"{LETTER_PREFIX}-{tag}"[:50],
                source=Application.SOURCE_DIRECT,
            )
            ApplicationProgramChoice.objects.create(application=app, program=program, choice_order=1)
            admission = AdmittedStudent.objects.create(
                application=app,
                student_id=student_id,
                reg_no=reg_no,
                study_mode="D" if "/D/" in reg_no.upper() else "W",
                admitted_program=program,
                admitted_batch=batch,
                admitted_campus=campus,
                intended_program_batch=ipb,
                is_admitted=True,
                admission_fee_paid=True,
                admission_fee_paid_at=now,
                admitted_by=admin_user,
                admission_notes=f"VOTEQA letter-format import probe — {reg_no}",
            )
        else:
            admission.student_id = student_id
            admission.reg_no = reg_no
            admission.admitted_campus = campus
            admission.admitted_program = program
            admission.intended_program_batch = ipb
            admission.is_admitted = True
            admission.admission_fee_paid = True
            admission.save()

        StudentProgrammeEnrollment.objects.update_or_create(
            student=admission,
            defaults={
                "program": program,
                "program_batch": ipb,
                "current_year_of_study": 1,
                "current_term_number": 1,
                "entry_year_of_study": 1,
                "entry_term_number": 1,
                "status": "enrolled",
                "enrolled_by": admin_user,
                "enrolled_at": now,
                "notes": f"{LETTER_PREFIX} {reg_no}",
            },
        )

        paid = (TUITION_AMOUNT * Decimal(pct) / Decimal("100")).quantize(Decimal("1.00"))
        StudentTuitionPayment.objects.update_or_create(
            student=admission,
            transaction_id=f"{LETTER_PREFIX}-{tag}",
            defaults={
                "fee_plan_rule": rule,
                "semester": semester,
                "source": "scheduled",
                "amount": paid,
                "currency": "UGX",
                "payment_method": "cash",
                "status": "completed",
                "payment_reference": f"{LETTER_PREFIX}-{tag}",
                "receipt_number": f"VOTEQA-LTR-RCP-{tag}",
                "paid_at": now,
                "is_waived": False,
            },
        )

        ensure_student_portal_account(admission)
        user = admission.student_user
        if user is not None:
            user.set_password(DEFAULT_STUDENT_PASSWORD)
            user.must_change_password = False
            user.is_active = True
            user.is_student = True
            user.save(update_fields=["password", "must_change_password", "is_active", "is_student"])

        return {
            "student": admission,
            "reg_no": admission.reg_no,
            "campus": campus.name,
            "pct": pct,
        }

    def _reset_previous(self):
        qs = AdmittedStudent.objects.filter(
            Q(student_id__startswith=f"{PREFIX}-") | Q(student_id__startswith=f"{LETTER_PREFIX}-")
        )
        n = qs.count()
        applicant_ids = list(qs.values_list("application__applicant_id", flat=True))
        app_ids = list(qs.values_list("application_id", flat=True))
        StudentTuitionPayment.objects.filter(
            Q(transaction_id__startswith=f"{PREFIX}-")
            | Q(transaction_id__startswith=f"{LETTER_PREFIX}-")
        ).delete()
        qs.delete()
        Application.objects.filter(pk__in=app_ids).delete()
        User.objects.filter(pk__in=[i for i in applicant_ids if i]).delete()
        User.objects.filter(username__startswith=f"{PREFIX.lower()}.").delete()
        User.objects.filter(username__startswith=f"{LETTER_PREFIX.lower()}.").delete()
        self.stdout.write(self.style.WARNING(f"Removed {n} previous {PREFIX} student(s)."))
