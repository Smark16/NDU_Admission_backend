"""
Label existing confirmations as applicant vs staff using audit log.

Legacy rows with a timestamp but empty confirmed_by are updated:
- staff if audit has program_choice_admin_change on that application
- applicant otherwise (assumed portal confirm before we tracked source)

Usage::

    python manage.py backfill_program_choice_confirmed_by --dry-run
    python manage.py backfill_program_choice_confirmed_by --apply
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from admissions.models import Application
from admissions.utils.program_choices import (
    PROGRAM_CHOICE_CONFIRMED_BY_APPLICANT,
    PROGRAM_CHOICE_CONFIRMED_BY_STAFF,
)
from audit.models import AuditLog

ACTION = "program_choice_admin_change"


class Command(BaseCommand):
    help = "Backfill program_choices_confirmed_by from audit history."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        dry = options["dry_run"] or not options["apply"]
        qs = Application.objects.filter(program_choices_confirmed_at__isnull=False).filter(
            program_choices_confirmed_by=""
        )
        staff_app_ids_int = set(
            AuditLog.objects.filter(action=ACTION, object_id__isnull=False).values_list(
                "object_id", flat=True
            )
        )

        to_staff = []
        to_applicant = []
        for app in qs.iterator():
            if app.id in staff_app_ids_int:
                to_staff.append(app)
            else:
                to_applicant.append(app)

        self.stdout.write(f"Legacy confirmed rows: {qs.count()}")
        self.stdout.write(f"  -> staff (had admin programme change in audit): {len(to_staff)}")
        self.stdout.write(f"  -> applicant (no staff change in audit): {len(to_applicant)}")

        if dry:
            self.stdout.write(self.style.WARNING("Dry run only; pass --apply to write."))
            for app in to_staff[:15]:
                self.stdout.write(f"  staff: {app.id} {app.first_name} {app.last_name}")
            return

        with transaction.atomic():
            for app in to_staff:
                app.program_choices_confirmed_by = PROGRAM_CHOICE_CONFIRMED_BY_STAFF
                app.save(update_fields=["program_choices_confirmed_by"])
            for app in to_applicant:
                app.program_choices_confirmed_by = PROGRAM_CHOICE_CONFIRMED_BY_APPLICANT
                app.save(update_fields=["program_choices_confirmed_by"])

        self.stdout.write(self.style.SUCCESS("Backfill complete."))
