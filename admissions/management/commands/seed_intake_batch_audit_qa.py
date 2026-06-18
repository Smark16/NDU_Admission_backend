"""
Local QA: mirror intake programmes missing programme batches (prod ids 152, 126).

  python manage.py seed_intake_batch_audit_qa
  python manage.py seed_intake_batch_audit_qa --audit-only
  python manage.py seed_intake_batch_audit_qa --fix-missing-batches
  python manage.py seed_intake_batch_audit_qa --reset
"""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from Programs.models import Program, ProgramBatch
from admissions.models import AcademicLevel, Batch, Faculty
from accounts.models import Campus
from Programs.program_batch_resolution import program_batch_in_active_offer_window_q

TAG = "[QA-INTAKE-BATCH]"
INTAKE_CODE = "QA-AUG-2026"

PROGRAMS = [
    {
        "code": "177-KLA",
        "short_form": "Cert Admin Law",
        "name": "Certificate in Administrative Law",
        "level": "Certificate",
        "batch_name": "Main AUG 2026",
        "seed_batch": False,
    },
    {
        "code": "536",
        "short_form": "MSc Constr PM Wknd",
        "name": "Master of Science in Construction and Project Management-Weekend",
        "level": "Postgraduate",
        "batch_name": "AUG 2026",
        "seed_batch": False,
    },
    {
        "code": "536-UP",
        "short_form": "MSc Constr PM UP",
        "name": "Master of Science in Construction and Project Management-Weekend (UP)",
        "level": "Postgraduate",
        "batch_name": "AUG 2026",
        "seed_batch": True,
    },
    {
        "code": "QA-BBA-OK",
        "short_form": "QA BBA Control",
        "name": f"{TAG} BBA (control — has batch)",
        "level": "Undergraduate",
        "batch_name": "AUG 2026",
        "seed_batch": True,
    },
]


def run_intake_audit(stdout, style) -> tuple[int, int, int]:
    """Return (ok, missing, no_offer) for active intakes."""
    today = timezone.now().date()
    window_q = program_batch_in_active_offer_window_q(today=today, admission_batch=None)
    total_missing = 0

    for intake in Batch.objects.filter(is_active=True).order_by("-created_at"):
        programs = intake.programs.filter(is_active=True).order_by("name")
        ok = missing = no_offer = 0
        problems = []

        for p in programs:
            batches = ProgramBatch.objects.filter(program_id=p.id)
            if not batches.exists():
                missing += 1
                problems.append((p.id, p.code, p.name, "MISSING BATCH"))
            elif not batches.filter(is_active=True).filter(window_q).exists():
                no_offer += 1
                problems.append((p.id, p.code, p.name, "NOT IN OFFER"))
            else:
                ok += 1

        stdout.write("=" * 90)
        stdout.write(f"{intake.name} (id={intake.id})")
        stdout.write(
            f"total={programs.count()} | OK={ok} | MISSING BATCH={missing} | NOT IN OFFER={no_offer}"
        )
        if missing == 0 and no_offer == 0:
            stdout.write(style.SUCCESS("RESULT: All programmes on this intake have active batches in offer."))
        else:
            stdout.write("Still need action:")
            for pid, code, name, status in problems:
                stdout.write(f"  [{pid}] {status} | {code} | {name}")
        stdout.write("")
        total_missing += missing + no_offer

    return ok, missing, total_missing


class Command(BaseCommand):
    help = "Seed local QA intake/programmes for batch-offer audit testing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--audit-only",
            action="store_true",
            help="Skip seeding; only run the intake vs programme-batch audit.",
        )
        parser.add_argument(
            "--fix-missing-batches",
            action="store_true",
            help="Create programme batches for QA programmes on the intake that have none.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Remove QA intake and programmes (names/codes tagged with QA prefix).",
        )

    def handle(self, *args, **options):
        if options["reset"]:
            self._reset()
            return

        if not options["audit_only"]:
            self._seed()

        if options["fix_missing_batches"]:
            self._fix_missing_batches()

        run_intake_audit(self.stdout, self.style)

    def _get_admin(self):
        User = get_user_model()
        user = User.objects.filter(is_superuser=True).order_by("id").first()
        if user is None:
            user = User.objects.order_by("id").first()
        if user is None:
            raise SystemExit("No user found — create a superuser first (createsuperuser).")
        return user

    def _get_or_create_level(self, name: str) -> AcademicLevel:
        level, _ = AcademicLevel.objects.get_or_create(name=name, defaults={"is_active": True})
        return level

    def _seed(self):
        admin = self._get_admin()
        today = timezone.now().date()

        campus, _ = Campus.objects.get_or_create(
            code=f"{TAG}-MAIN",
            defaults={"name": f"{TAG} Main Campus"},
        )
        faculty, _ = Faculty.objects.get_or_create(
            code=f"{TAG}-LAW",
            defaults={"name": f"{TAG} Law Faculty", "is_active": True},
        )
        faculty.campuses.add(campus)

        level_cache = {name: self._get_or_create_level(name) for name in {p["level"] for p in PROGRAMS}}

        program_ids = []
        for spec in PROGRAMS:
            program, created = Program.objects.update_or_create(
                code=spec["code"],
                defaults={
                    "name": spec["name"] if not spec["name"].startswith(TAG) else spec["name"],
                    "short_form": spec["short_form"],
                    "faculty": faculty,
                    "academic_level": level_cache[spec["level"]],
                    "min_years": 1 if spec["level"] == "Certificate" else 2,
                    "max_years": 1 if spec["level"] == "Certificate" else 2,
                    "is_active": True,
                },
            )
            program.campuses.add(campus)
            program_ids.append(program.id)
            action = "created" if created else "updated"
            self.stdout.write(self.style.SUCCESS(f"  {action} programme [{program.id}] {program.code}"))

            if spec["seed_batch"]:
                self._ensure_batch(program, spec["batch_name"], today)

        intake, created = Batch.objects.update_or_create(
            code=INTAKE_CODE,
            defaults={
                "name": f"{TAG} AUG 2026 INTAKE",
                "academic_year": "2025/2026",
                "application_start_date": today - timedelta(days=30),
                "application_end_date": today + timedelta(days=180),
                "admission_start_date": today - timedelta(days=25),
                "admission_end_date": today + timedelta(days=185),
                "offer_start_date": None,
                "offer_end_date": None,
                "is_active": True,
                "created_by": admin,
            },
        )
        intake.programs.set(Program.objects.filter(id__in=program_ids))
        action = "created" if created else "updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"  {action} intake [{intake.id}] {intake.name} with {len(program_ids)} programme(s)"
            )
        )
        self.stdout.write(
            "Expected before --fix-missing-batches: 2 MISSING (177-KLA, 536); 2 OK (536-UP, QA-BBA-OK)"
        )
        self.stdout.write("")

    def _ensure_batch(self, program: Program, batch_name: str, today: date) -> ProgramBatch:
        offer_start = today - timedelta(days=30)
        offer_end = today + timedelta(days=180)
        start = date(today.year, 8, 1) if today.month <= 8 else today
        end = date(start.year + 1, 7, 31)
        batch, created = ProgramBatch.objects.update_or_create(
            program=program,
            name=batch_name,
            defaults={
                "academic_year": "2025/2026",
                "start_date": start,
                "end_date": end,
                "offer_start_date": offer_start,
                "offer_end_date": offer_end,
                "is_active": True,
            },
        )
        action = "created" if created else "updated"
        self.stdout.write(f"    {action} ProgramBatch id={batch.id} for {program.code}")
        return batch

    def _fix_missing_batches(self):
        today = timezone.now().date()
        specs_by_code = {s["code"]: s for s in PROGRAMS}
        fixed = 0

        for intake in Batch.objects.filter(code=INTAKE_CODE, is_active=True):
            for program in intake.programs.filter(is_active=True):
                if ProgramBatch.objects.filter(program_id=program.id).exists():
                    continue
                spec = specs_by_code.get(program.code)
                batch_name = spec["batch_name"] if spec else "AUG 2026"
                self._ensure_batch(program, batch_name, today)
                fixed += 1

        self.stdout.write(self.style.SUCCESS(f"Created {fixed} missing programme batch(es)."))
        self.stdout.write("")

    def _reset(self):
        deleted_batches = ProgramBatch.objects.filter(
            program__code__in=[s["code"] for s in PROGRAMS]
        ).delete()
        deleted_programs = Program.objects.filter(
            code__in=[s["code"] for s in PROGRAMS]
        ).delete()
        deleted_intakes = Batch.objects.filter(code=INTAKE_CODE).delete()
        self.stdout.write(
            self.style.WARNING(
                f"Removed QA data — intakes={deleted_intakes[0]}, "
                f"programmes={deleted_programs[0]}, programme_batches={deleted_batches[0]}"
            )
        )
