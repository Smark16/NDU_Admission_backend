"""
Clear cohort-level ``offer_start_date`` / ``offer_end_date`` on ProgramBatch.

Offer timing is controlled on admission Intakes. Leaving cohort dates null lets
admit pickers inherit the intake window.

Usage::

    python manage.py clear_program_batch_offer_dates --dry-run
    python manage.py clear_program_batch_offer_dates --apply
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from Programs.models import ProgramBatch


class Command(BaseCommand):
    help = "Clear ProgramBatch offer dates so intake owns offer timing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print counts only (default if --apply not passed).",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write null offer dates to the database.",
        )

    def handle(self, *args, **options):
        apply = bool(options["apply"])
        dry_run = bool(options["dry_run"]) or not apply
        qs = ProgramBatch.objects.filter(
            Q(offer_start_date__isnull=False) | Q(offer_end_date__isnull=False)
        )
        count = qs.count()
        self.stdout.write(f"ProgramBatch rows with offer dates set: {count}")
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — no changes written. Pass --apply to clear."))
            return
        with transaction.atomic():
            updated = qs.update(offer_start_date=None, offer_end_date=None)
        self.stdout.write(self.style.SUCCESS(f"Cleared offer dates on {updated} cohort(s)."))
