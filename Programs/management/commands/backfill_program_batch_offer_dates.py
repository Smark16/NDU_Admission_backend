"""
DEPRECATED: cohort offer dates are no longer backfilled from academic dates.

Use ``clear_program_batch_offer_dates`` instead — offer timing lives on Intakes.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Deprecated. Use clear_program_batch_offer_dates — intake owns offer windows."
    )

    def handle(self, *args, **options):
        self.stderr.write(
            self.style.ERROR(
                "backfill_program_batch_offer_dates is deprecated. "
                "Run: python manage.py clear_program_batch_offer_dates --apply"
            )
        )
