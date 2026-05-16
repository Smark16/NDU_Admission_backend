"""
Set ``offer_start_date`` / ``offer_end_date`` on programme cohorts that lack them.

Inferred from each batch's ``start_date`` and ``end_date`` (see
``Programs.batch_offer_defaults``).

Usage (server)::

    python manage.py backfill_program_batch_offer_dates --dry-run
    python manage.py backfill_program_batch_offer_dates --apply
    python manage.py backfill_program_batch_offer_dates --apply --program-id 42
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from Programs.batch_offer_defaults import (
    infer_program_batch_offer_dates,
    offer_dates_missing_or_partial,
)
from Programs.models import ProgramBatch


class Command(BaseCommand):
    help = "Backfill ProgramBatch offer_start_date / offer_end_date for admit pickers."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print changes only (default if --apply not passed).",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write offer dates to the database.",
        )
        parser.add_argument(
            "--program-id",
            type=int,
            default=None,
            help="Limit to one programme primary key.",
        )
        parser.add_argument(
            "--batch-id",
            type=int,
            default=None,
            help="Limit to one ProgramBatch primary key.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite offer dates even when both are already set.",
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        dry_run = options["dry_run"] or not apply

        qs = ProgramBatch.objects.select_related("program").order_by(
            "program__code", "name", "pk"
        )
        if options["program_id"]:
            qs = qs.filter(program_id=options["program_id"])
        if options["batch_id"]:
            qs = qs.filter(pk=options["batch_id"])

        to_update = []
        for batch in qs:
            if options["force"]:
                to_update.append(batch)
                continue
            if offer_dates_missing_or_partial(
                batch.offer_start_date, batch.offer_end_date
            ):
                to_update.append(batch)

        if not to_update:
            self.stdout.write("No batches need offer date backfill.")
            return

        self.stdout.write(
            f"{'DRY RUN — ' if dry_run else ''}"
            f"{len(to_update)} batch(es) to update:\n"
        )

        updated = 0
        for batch in to_update:
            offer_start, offer_end = infer_program_batch_offer_dates(
                batch.start_date, batch.end_date
            )
            prog = batch.program.code or batch.program.short_form or batch.program_id
            self.stdout.write(
                f"  id={batch.pk} {prog} | {batch.name!r}\n"
                f"    offer: {batch.offer_start_date} .. {batch.offer_end_date}\n"
                f"    ->    {offer_start} .. {offer_end}\n"
            )
            if dry_run:
                continue
            with transaction.atomic():
                batch.offer_start_date = offer_start
                batch.offer_end_date = offer_end
                batch.save(
                    update_fields=[
                        "offer_start_date",
                        "offer_end_date",
                        "updated_at",
                    ]
                )
            updated += 1

        if dry_run:
            self.stdout.write("\nRe-run with --apply to save.")
        else:
            self.stdout.write(self.style.SUCCESS(f"\nUpdated {updated} batch(es)."))
