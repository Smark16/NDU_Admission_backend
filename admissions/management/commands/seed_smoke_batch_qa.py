"""
Local QA: ensure two labelled ProgramBatch rows on a programme, optionally add a demo admitted student.

From ``NDU_Admission_backend`` (with ``DJANGO_SETTINGS_MODULE`` set as usual):

  python manage.py seed_smoke_batch_qa
  python manage.py seed_smoke_batch_qa --program-id 3
  python manage.py seed_smoke_batch_qa --dry-run
  python manage.py seed_smoke_batch_qa --with-demo-student --program-id 3
  python manage.py seed_smoke_batch_qa --with-demo-student --program-id 3 --omit-intended-batch
"""
from __future__ import annotations

from datetime import timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from Programs.models import Program, ProgramBatch

COHORT_A = "[QA] Smoke cohort A"
COHORT_B = "[QA] Smoke cohort B"


class Command(BaseCommand):
    help = "Create/update two QA ProgramBatch rows on a programme; optionally run create_demo_student."

    def add_arguments(self, parser):
        parser.add_argument(
            "--program-id",
            type=int,
            default=None,
            help="Programme PK (default: first active programme by id).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print actions only; do not write to the database.",
        )
        parser.add_argument(
            "--with-demo-student",
            action="store_true",
            help="After batches exist, run create_demo_student for the same programme.",
        )
        parser.add_argument(
            "--omit-intended-batch",
            action="store_true",
            help="Pass to create_demo_student: leave intended_program_batch null.",
        )

    def handle(self, *args, **options):
        dry = options["dry_run"]
        pid = options["program_id"]
        today = timezone.now().date()

        if pid:
            program = Program.objects.filter(pk=pid).first()
            if not program:
                raise CommandError(f"No programme with id={pid}.")
        else:
            program = Program.objects.filter(is_active=True).order_by("id").first()
            if not program:
                program = Program.objects.order_by("id").first()
            if not program:
                raise CommandError("No Programme found.")

        self.stdout.write(f"Programme: {program.id} — {program.short_form} / {program.name}")

        plan = [
            {
                "name": COHORT_A,
                "start_date": today,
                "academic_year": f"{today.year}/{today.year + 1}",
            },
            {
                "name": COHORT_B,
                "start_date": today - timedelta(days=400),
                "academic_year": f"{today.year - 1}/{today.year}",
            },
        ]

        for row in plan:
            if dry:
                self.stdout.write(
                    self.style.WARNING(
                        f"  [dry-run] would update_or_create ProgramBatch name={row['name']!r} "
                        f"start_date={row['start_date']}"
                    )
                )
                continue
            obj, created = ProgramBatch.objects.update_or_create(
                program=program,
                name=row["name"],
                defaults={
                    "start_date": row["start_date"],
                    "academic_year": row["academic_year"],
                    "end_date": None,
                    "offer_start_date": None,
                    "offer_end_date": None,
                    "is_active": True,
                    "curriculum_version": None,
                },
            )
            action = "created" if created else "updated"
            self.stdout.write(self.style.SUCCESS(f"  {action}: ProgramBatch id={obj.id} name={obj.name!r}"))

        if dry:
            self.stdout.write(self.style.WARNING("Dry run complete — no database changes."))
            return

        self.stdout.write("Try in browser or API:")
        self.stdout.write(f"  GET /api/admissions/program_batches_options/{program.id}/")

        if options["with_demo_student"]:
            kwargs = {"program_id": program.id}
            if options["omit_intended_batch"]:
                kwargs["omit_intended_batch"] = True
            call_command("create_demo_student", **kwargs)
