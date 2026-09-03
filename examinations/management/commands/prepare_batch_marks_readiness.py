"""
Prepare marks-entry readiness for a programme batch.

Actions (all off by default; combine flags as needed):
  --seed-policies          Ensure default assessment policy / grade scale exist
  --open-windows           Create/activate semester-scoped MarksEntryWindow rows
  --stamp-registration     Set registration_date on enrolled, non-revoked enrollments missing it
  --report-lecturers       List courses with enrollments but no lecturers

Examples:
  python manage.py prepare_batch_marks_readiness --batch "LLB-377-Main" --report-lecturers
  python manage.py prepare_batch_marks_readiness --batch "LLB-377-Main" --seed-policies --open-windows --dry-run
  python manage.py prepare_batch_marks_readiness --batch "LLB-377-Main" --stamp-registration --dry-run
  python manage.py prepare_batch_marks_readiness --batch "LLB-377-Main" --stamp-registration --semester-id 42
"""
from __future__ import annotations

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from examinations.models import MarksEntryWindow
from examinations.services.batch_marks_audit import (
    course_units_for_batch,
    enrollments_for_batch,
    resolve_program_batches,
    semesters_for_batch,
)


class Command(BaseCommand):
    help = "Fix common marks-entry readiness gaps for a ProgramBatch (windows, policies, registration)."

    def add_arguments(self, parser):
        parser.add_argument("--batch", default="")
        parser.add_argument("--batch-id", type=int, default=None)
        parser.add_argument("--seed-policies", action="store_true")
        parser.add_argument(
            "--open-windows",
            action="store_true",
            help="Ensure an active semester MarksEntryWindow exists for each semester on the batch.",
        )
        parser.add_argument(
            "--window-name",
            default="",
            help="Optional name prefix for created windows (default: '<batch> marks entry').",
        )
        parser.add_argument(
            "--stamp-registration",
            action="store_true",
            help="Stamp registration_date=now on enrollments missing it (enrolled status, not revoked).",
        )
        parser.add_argument(
            "--semester-id",
            type=int,
            default=None,
            help="Limit stamp/open-windows to one semester id.",
        )
        parser.add_argument("--report-lecturers", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        try:
            batches = resolve_program_batches(
                batch=options.get("batch") or None,
                batch_id=options.get("batch_id"),
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        dry = bool(options.get("dry_run"))
        any_action = any(
            [
                options.get("seed_policies"),
                options.get("open_windows"),
                options.get("stamp_registration"),
                options.get("report_lecturers"),
            ]
        )
        if not any_action:
            raise CommandError(
                "Pass at least one of: --seed-policies --open-windows "
                "--stamp-registration --report-lecturers"
            )

        if options.get("seed_policies"):
            if dry:
                self.stdout.write("[dry-run] Would run seed_examination_defaults")
            else:
                call_command("seed_examination_defaults")

        semester_id = options.get("semester_id")

        for batch in batches:
            label = f"#{batch.id} {batch.program.short_form} — {batch.name}"
            self.stdout.write("")
            self.stdout.write(self.style.MIGRATE_HEADING(label))

            if options.get("report_lecturers"):
                for cu in course_units_for_batch(batch):
                    if semester_id and cu.semester_id != semester_id:
                        continue
                    lecturers = cu.lecturers.count()
                    enrolled = cu.student_enrollments.filter(
                        status__in=("enrolled", "completed", "failed")
                    ).count()
                    if enrolled and lecturers == 0:
                        self.stdout.write(
                            self.style.WARNING(
                                f"  No lecturers: {cu.code} — {cu.name} "
                                f"(cu=#{cu.id}, enrolled={enrolled}, sem={cu.semester_id})"
                            )
                        )

            if options.get("open_windows"):
                semis = list(semesters_for_batch(batch))
                if semester_id:
                    semis = [s for s in semis if s.id == semester_id]
                if not semis:
                    self.stdout.write(self.style.WARNING("  No semesters to open windows for."))
                base_name = (options.get("window_name") or "").strip() or f"{batch.name} marks entry"
                for sem in semis:
                    existing = (
                        MarksEntryWindow.objects.filter(
                            program_batch=batch,
                            semester=sem,
                            course_unit__isnull=True,
                        )
                        .order_by("-is_active", "-updated_at")
                        .first()
                    )
                    if existing and existing.is_active:
                        self.stdout.write(
                            f"  Window already open: #{existing.id} for {sem.name}"
                        )
                        continue
                    if dry:
                        action = "activate" if existing else "create"
                        self.stdout.write(
                            f"  [dry-run] Would {action} window for semester {sem.name} (#{sem.id})"
                        )
                        continue
                    with transaction.atomic():
                        if existing:
                            existing.is_active = True
                            existing.opens_at = existing.opens_at or timezone.now()
                            existing.closes_at = None
                            existing.closed_at = None
                            existing.closed_by = None
                            existing.name = existing.name or base_name
                            existing.save()
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f"  Activated window #{existing.id} for {sem.name}"
                                )
                            )
                        else:
                            w = MarksEntryWindow.objects.create(
                                name=f"{base_name} — {sem.name}",
                                program_batch=batch,
                                semester=sem,
                                opens_at=timezone.now(),
                                closes_at=None,
                                is_active=True,
                                notes="Opened by prepare_batch_marks_readiness",
                            )
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f"  Created window #{w.id} for {sem.name}"
                                )
                            )

            if options.get("stamp_registration"):
                qs = enrollments_for_batch(batch).filter(
                    registration_date__isnull=True,
                    status="enrolled",
                ).exclude(student__application__is_revoked=True)
                if semester_id:
                    qs = qs.filter(course_unit__semester_id=semester_id)
                count = qs.count()
                self.stdout.write(
                    f"  Unregistered enrolled (non-revoked) to stamp: {count}"
                    + (f" (semester_id={semester_id})" if semester_id else "")
                )
                if dry:
                    self.stdout.write("  [dry-run] No registration_date updates.")
                elif count:
                    now = timezone.now()
                    updated = qs.update(registration_date=now)
                    self.stdout.write(
                        self.style.SUCCESS(f"  Stamped registration_date on {updated} enrollment(s).")
                    )

        if dry:
            self.stdout.write(self.style.WARNING("Dry run complete."))
