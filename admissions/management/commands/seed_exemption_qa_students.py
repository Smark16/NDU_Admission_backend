"""
Seed admitted students for Course Exemption QA.

Also creates Ndejje curriculum papers + exam grade bands so the student form
can be filled (pick units, map letter grades to marks, submit).

  python manage.py seed_exemption_qa_students
  python manage.py seed_exemption_qa_students --reset
  python manage.py seed_exemption_qa_students --curriculum-only

Portal login is the registration number / NDU@1234.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import User, Campus
from admissions.models import (
    AcademicLevel,
    AdmittedStudent,
    Application,
    ApplicationProgramChoice,
    Batch,
)
from admissions.student_accounts import DEFAULT_STUDENT_PASSWORD, ensure_student_portal_account
from admissions.utils.batch_offer_filters import batch_offer_window_q
from Programs.models import (
    CourseCatalogUnit,
    Program,
    ProgramBatch,
    ProgramCurriculumLine,
    StudentProgrammeEnrollment,
    ensure_program_default_curriculum_version,
)


PREFIX = "EXMQA"

# key, label, year, term, fee_paid, accounts_cleared, docs_ok
PERSONAS = (
    ("y1_awaiting_accounts", "Y1T1 — awaiting Accounts", 1, 1, True, False, False),
    ("y1_awaiting_ar", "Y1T1 — Accounts done, AR docs pending", 1, 1, True, True, False),
    ("y1_ready", "Y1T1 — ready to apply (Accounts + AR)", 1, 1, True, True, True),
    ("y1_ready", "Y1T1 — ready to apply (Accounts + AR)", 1, 1, True, True, True),
    ("y2_awaiting_accounts", "Continuing — awaiting Accounts", 2, 1, True, False, False),
    ("y2_ready", "Continuing — ready (Accounts only, no AR needed)", 2, 1, True, True, False),
)

FIRST_NAMES = ["Amina", "Brian", "Carol", "David", "Esther", "Fred"]
LAST_NAMES = ["Nalubega", "Otim", "Namutebi", "Mugisha", "Achieng", "Ssemakula"]

# Papers for the exemption picker (max 4 terms on an application).
EXEMPTION_PAPERS = (
    ("EXMQA101", "Introduction to University Studies", 1, 1),
    ("EXMQA102", "Communication Skills", 1, 1),
    ("EXMQA111", "Foundations of the Major", 1, 2),
    ("EXMQA112", "Quantitative Methods I", 1, 2),
    ("EXMQA201", "Intermediate Studies", 2, 1),
    ("EXMQA202", "Research Methods", 2, 1),
    ("EXMQA211", "Advanced Topics", 2, 2),
    ("EXMQA212", "Project Planning", 2, 2),
)

GRADE_BANDS = (
    ("A", 80, 100, 5.0),
    ("B+", 75, 79.9, 4.5),
    ("B", 70, 74.9, 4.0),
    ("C+", 65, 69.9, 3.5),
    ("C", 60, 64.9, 3.0),
    ("D+", 55, 59.9, 2.5),
    ("D", 50, 54.9, 2.0),
    ("F", 0, 49.9, 0.0),
)


class Command(BaseCommand):
    help = (
        "Create EXMQA students plus curriculum units and grade bands so the "
        "exemption form can be filled and submitted."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete previous EXMQA students first.",
        )
        parser.add_argument(
            "--curriculum-only",
            action="store_true",
            help=(
                "Do not create new students. Attach curriculum papers + grade "
                "bands to existing EXMQA/LISTQA programmes (and enrollments)."
            ),
        )
        parser.add_argument(
            "--skip-portal-account",
            action="store_true",
            help="Do not create student portal users.",
        )
        parser.add_argument(
            "--program-id",
            type=int,
            default=None,
            help="Admit into / attach curriculum to this programme PK.",
        )

    def handle(self, *args, **options):
        bands_n = self._ensure_grade_scale()
        self.stdout.write(self.style.SUCCESS(f"Grade scale ready ({bands_n} bands). Use A–C+ (60%+)."))

        if options["curriculum_only"]:
            self._attach_curriculum_only(options["program_id"])
            return

        if options["reset"]:
            self._reset_previous()

        batch, campus, program, academic_level, admin_user = self._lookups(options["program_id"])
        version = self._ensure_curriculum(program)
        ipb = self._ensure_program_batch(program, version)

        ts = timezone.now().strftime("%Y%m%d%H%M%S")
        created = []
        with transaction.atomic():
            for i, persona in enumerate(PERSONAS):
                created.append(
                    self._create_one(
                        index=i,
                        ts=ts,
                        persona=persona,
                        batch=batch,
                        campus=campus,
                        program=program,
                        academic_level=academic_level,
                        admin_user=admin_user,
                        ipb=ipb,
                        version=version,
                        skip_portal=options["skip_portal_account"],
                    )
                )

        self.stdout.write(self.style.SUCCESS(f"Created {len(created)} EXMQA students."))
        self.stdout.write(f"Programme: {program.code} — {program.name}")
        self.stdout.write(f"Curriculum papers: {len(EXEMPTION_PAPERS)}")
        self.stdout.write("Student portal password: " + DEFAULT_STUDENT_PASSWORD)
        self.stdout.write("")
        self.stdout.write(f"{'Persona':<48} {'Reg no / login':<28} Can apply?")
        for row in created:
            self.stdout.write(
                f"{row['label']:<48} {row['reg_no']:<28} "
                f"{'YES' if row['can_apply'] else 'no'}"
            )
        self.stdout.write("")
        self.stdout.write("Test path:")
        self.stdout.write("  1. Log in as a YES student (reg no / NDU@1234).")
        self.stdout.write("  2. Dashboard → Exemptions → pick EXMQA papers, grade A/B, submit and pay.")
        self._print_exmqa_logins()

    def _attach_curriculum_only(self, program_id):
        from Programs.curriculum_inheritance import curriculum_owner_program

        programs = []
        if program_id:
            program = (
                Program.objects.filter(pk=program_id).first()
            )
            if not program:
                raise CommandError(f"No programme with id={program_id}.")
            programs = [program]
        else:
            qs = AdmittedStudent.objects.filter(
                is_admitted=True,
            ).filter(
                Q(reg_no__startswith=PREFIX + "-") | Q(reg_no__startswith="LISTQA-")
            )
            seen = set()
            for student in qs.select_related("admitted_program", "programme_enrollment"):
                prog = student.admitted_program
                if prog and prog.pk not in seen:
                    seen.add(prog.pk)
                    programs.append(prog)
            # Also seed papers onto programmes that have students but no units,
            # so a non-EXMQA login is not stuck with an empty picker.
            for prog in Program.objects.filter(is_active=True):
                if prog.pk in seen:
                    continue
                if not AdmittedStudent.objects.filter(
                    is_admitted=True, admitted_program=prog
                ).exists():
                    continue
                owner = curriculum_owner_program(prog) or prog
                has_lines = ProgramCurriculumLine.objects.filter(
                    is_active=True,
                ).filter(
                    Q(curriculum_version__program=owner) | Q(program=owner)
                ).exists()
                if not has_lines:
                    seen.add(prog.pk)
                    programs.append(prog)
                    self.stdout.write(
                        self.style.WARNING(
                            f"Empty curriculum — attaching EXMQA papers to {prog.code} ({prog.name})."
                        )
                    )
            if not programs:
                program = Program.objects.filter(is_active=True).order_by("id").first()
                if not program:
                    raise CommandError("No active Programme found.")
                programs = [program]
                self.stdout.write(
                    self.style.WARNING(
                        "No EXMQA/LISTQA students found — attaching papers to the first active programme."
                    )
                )

        admin_user = (
            User.objects.filter(is_superuser=True).order_by("id").first()
            or User.objects.order_by("id").first()
        )
        now = timezone.now()
        for program in programs:
            version = self._ensure_curriculum(program)
            ipb = self._ensure_program_batch(program, version)
            students = AdmittedStudent.objects.filter(
                is_admitted=True,
                admitted_program=program,
            ).filter(
                Q(reg_no__startswith=PREFIX + "-") | Q(reg_no__startswith="LISTQA-")
            )
            n = 0
            for student in students.select_related("programme_enrollment"):
                year, term = 1, 1
                try:
                    enr = student.programme_enrollment
                    year = int(enr.current_year_of_study or 1)
                    term = int(enr.current_term_number or 1)
                except Exception:
                    enr = None
                StudentProgrammeEnrollment.objects.update_or_create(
                    student=student,
                    defaults={
                        "program": program,
                        "program_batch": ipb,
                        "curriculum_version": version,
                        "current_year_of_study": year,
                        "current_term_number": term,
                        "entry_year_of_study": 1,
                        "entry_term_number": 1,
                        "status": "enrolled",
                        "enrolled_by": admin_user,
                        "enrolled_at": now,
                        "notes": "EXMQA curriculum attached for exemption form QA.",
                    },
                )
                n += 1
            self.stdout.write(
                self.style.SUCCESS(
                    f"{program.code}: {len(EXEMPTION_PAPERS)} papers, "
                    f"pinned on {n} EXMQA/LISTQA enrollment(s)."
                )
            )
        self._print_exmqa_logins()
        self.stdout.write("Reload Course Exemption — units and grade letters should appear.")

    def _print_exmqa_logins(self):
        from admissions.exemption_services import (
            list_eligible_exemption_courses,
            student_may_apply_course_exemption,
        )

        rows = (
            AdmittedStudent.objects.filter(
                is_admitted=True, reg_no__startswith=f"{PREFIX}-"
            )
            .select_related(
                "admitted_program",
                "student_user",
                "programme_enrollment",
                "programme_enrollment__curriculum_version",
            )
            .order_by("id")
        )
        if not rows:
            return
        self.stdout.write("")
        self.stdout.write(f"Portal password for all EXMQA students: {DEFAULT_STUDENT_PASSWORD}")
        self.stdout.write(f"{'Username (reg no)':<36} {'units':<8} apply")
        for student in rows:
            user = student.student_user
            if user is not None:
                user.set_password(DEFAULT_STUDENT_PASSWORD)
                user.must_change_password = False
                user.is_active = True
                user.is_student = True
                user.save(update_fields=["password", "must_change_password", "is_active", "is_student"])
            try:
                n = len(list_eligible_exemption_courses(student))
            except Exception as exc:
                n = f"ERR:{exc}"
            can = student_may_apply_course_exemption(student)
            self.stdout.write(
                f"{student.reg_no:<36} {str(n):<8} {'YES' if can else 'no'}"
            )

    def _ensure_grade_scale(self) -> int:
        from examinations.models import GradeBand, GradeScale

        scale, _ = GradeScale.objects.update_or_create(
            name="Standard letter grades",
            defaults={"is_active": True, "academic_level": None},
        )
        for order, (letter, lo, hi, gp) in enumerate(GRADE_BANDS):
            GradeBand.objects.update_or_create(
                grade_scale=scale,
                letter=letter,
                defaults={
                    "min_mark": Decimal(str(lo)),
                    "max_mark": Decimal(str(hi)),
                    "grade_point": Decimal(str(gp)),
                    "order": order,
                },
            )
        # Empty active scales (often level-specific) would hide bands in the form.
        for other in GradeScale.objects.filter(is_active=True).exclude(pk=scale.pk):
            if other.bands.exists():
                continue
            for order, (letter, lo, hi, gp) in enumerate(GRADE_BANDS):
                GradeBand.objects.update_or_create(
                    grade_scale=other,
                    letter=letter,
                    defaults={
                        "min_mark": Decimal(str(lo)),
                        "max_mark": Decimal(str(hi)),
                        "grade_point": Decimal(str(gp)),
                        "order": order,
                    },
                )
            self.stdout.write(
                self.style.WARNING(f"Filled missing bands on grade scale: {other.name}")
            )
        return scale.bands.count()

    def _ensure_curriculum(self, program: Program):
        from Programs.curriculum_inheritance import curriculum_owner_program

        owner = curriculum_owner_program(program) or program
        versions = list(owner.curriculum_versions.filter(is_active=True))
        default = ensure_program_default_curriculum_version(owner)
        if default is None:
            raise CommandError(f"Could not create a curriculum version for {owner.code}.")
        if default not in versions:
            versions.append(default)
        for version in versions:
            if not version.is_active:
                version.is_active = True
                version.save(update_fields=["is_active", "updated_at"])
            for sort, (code, title, year, term) in enumerate(EXEMPTION_PAPERS, start=1):
                cat, _ = CourseCatalogUnit.objects.get_or_create(
                    code=code,
                    defaults={
                        "title": title,
                        "credit_units": Decimal("3.00"),
                        "lecture_hours": 45,
                        "is_active": True,
                    },
                )
                if not cat.is_active:
                    cat.is_active = True
                    cat.save(update_fields=["is_active", "updated_at"])
                line, _ = ProgramCurriculumLine.objects.get_or_create(
                    curriculum_version=version,
                    catalog_course=cat,
                    year_of_study=year,
                    term_number=term,
                    defaults={
                        "program": owner,
                        "course_type": "mandatory",
                        "sort_order": sort,
                        "is_active": True,
                    },
                )
                if not line.is_active or line.program_id != owner.pk:
                    line.is_active = True
                    line.program = owner
                    line.sort_order = sort
                    line.save(
                        update_fields=["is_active", "program", "sort_order", "updated_at"]
                    )
        return default

    def _ensure_program_batch(self, program: Program, version):
        ipb = (
            ProgramBatch.objects.filter(program=program, is_active=True)
            .order_by("-start_date", "name")
            .first()
        )
        if ipb:
            if ipb.curriculum_version_id is None:
                ipb.curriculum_version = version
                ipb.save(update_fields=["curriculum_version", "updated_at"])
            return ipb
        today = timezone.now().date()
        ipb, _ = ProgramBatch.objects.get_or_create(
            program=program,
            name="EXMQA Test Cohort",
            defaults={
                "academic_year": "2026/2027",
                "start_date": today - timedelta(days=30),
                "end_date": today + timedelta(days=365),
                "curriculum_version": version,
                "is_active": True,
            },
        )
        return ipb

    def _lookups(self, program_id):
        batch = (
            Batch.objects.filter(is_active=True)
            .filter(batch_offer_window_q())
            .order_by("-id")
            .first()
            or Batch.objects.order_by("-id").first()
        )
        if not batch:
            raise CommandError("No admissions Batch found.")
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

    def _reset_previous(self):
        qs = AdmittedStudent.objects.filter(reg_no__startswith=f"{PREFIX}-")
        n = qs.count()
        applicant_ids = list(qs.values_list("application__applicant_id", flat=True))
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
        persona,
        batch,
        campus,
        program,
        academic_level,
        admin_user,
        ipb,
        version,
        skip_portal,
    ):
        key, label, year, term, fee_paid, accounts_cleared, docs_ok = persona
        first = FIRST_NAMES[index % len(FIRST_NAMES)]
        last = LAST_NAMES[index % len(LAST_NAMES)]
        suffix = f"{ts}{index:02d}"
        email = f"{PREFIX.lower()}.{key}.{suffix}@example.test"
        username = f"{PREFIX.lower()}.{key}.{suffix}"[:150]

        applicant = User.objects.create_user(
            username=username,
            email=email,
            password="ExmQa@123",
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
            middle_name=key.replace("_", " "),
            date_of_birth=date(2000, 6, 1) + timedelta(days=index),
            gender="Female" if index % 2 else "Male",
            nationality="Ugandan",
            phone=f"+2567{suffix[-8:]}",
            email=email,
            next_of_kin_name=f"{last} Next of Kin",
            next_of_kin_contact="+256700000222",
            next_of_kin_relationship="Parent",
            olevel_year=2018,
            olevel_index_number=f"{PREFIX}/{suffix}/2018",
            olevel_school="EXMQA Secondary School",
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
            application=app, program=program, choice_order=1
        )

        now = timezone.now()
        tag = key.replace("_", "")[:8].upper()
        reg_no = f"{PREFIX}-{tag}-{suffix[-8:]}"[:100]
        student_id = f"7{suffix[-9:]}"[:50]
        if AdmittedStudent.objects.filter(student_id=student_id).exists():
            student_id = f"7{suffix[-8:]}{index}"[:50]

        admission = AdmittedStudent.objects.create(
            application=app,
            student_id=student_id,
            reg_no=reg_no,
            study_mode="D",
            admitted_program=program,
            admitted_batch=batch,
            admitted_campus=campus,
            is_admitted=True,
            admission_notes=f"Seeded for exemption QA ({label}).",
            admitted_by=admin_user,
            intended_program_batch=ipb,
            admission_fee_paid=fee_paid,
            admission_fee_paid_at=now if fee_paid else None,
            registration_tuition_pct_met=True,
            registration_tuition_pct_at=now,
            accounts_registration_cleared=accounts_cleared,
            accounts_registration_cleared_at=now if accounts_cleared else None,
            accounts_registration_cleared_by=admin_user if accounts_cleared else None,
            physical_documents_verified=docs_ok,
            physical_documents_verified_at=now if docs_ok else None,
            physical_documents_verified_by=admin_user if docs_ok else None,
        )

        StudentProgrammeEnrollment.objects.update_or_create(
            student=admission,
            defaults={
                "program": program,
                "program_batch": ipb,
                "curriculum_version": version,
                "current_year_of_study": year,
                "current_term_number": term,
                "entry_year_of_study": 1,
                "entry_term_number": 1,
                "status": "enrolled",
                "enrolled_by": admin_user,
                "enrolled_at": now,
                "notes": f"EXMQA seed Y{year}T{term}.",
            },
        )

        if not skip_portal:
            ensure_student_portal_account(admission)
            user = admission.student_user
            if user is not None:
                user.must_change_password = False
                user.save(update_fields=["must_change_password"])

        y1t1 = year == 1 and term == 1
        can_apply = accounts_cleared and (docs_ok if y1t1 else True)
        return {
            "key": key,
            "label": label,
            "reg_no": admission.reg_no,
            "can_apply": can_apply,
        }
