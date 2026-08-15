"""Pull SchoolPay transactions (including supplementary fees) into TuitionLedger."""
from __future__ import annotations

from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from payments.utils.Transaction_sync import pull_schoolpay_range


class Command(BaseCommand):
    help = (
        "Fetch SchoolPay wallet payments for a date range (max 31 days per request) "
        "and save them to TuitionLedger. Use this when a student paid on SchoolPay "
        "but Bonafide still shows no payment history."
    )

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="from_date", help="YYYY-MM-DD (default: 90 days ago)")
        parser.add_argument("--to", dest="to_date", help="YYYY-MM-DD (default: today)")

    def handle(self, *args, **options):
        today = timezone.now().date()
        to_raw = (options.get("to_date") or "").strip()
        from_raw = (options.get("from_date") or "").strip()
        end = datetime.strptime(to_raw, "%Y-%m-%d").date() if to_raw else today
        start = (
            datetime.strptime(from_raw, "%Y-%m-%d").date()
            if from_raw
            else end - timedelta(days=90)
        )
        if start > end:
            self.stderr.write("--from must be on or before --to")
            return

        total = 0
        cursor = start
        while cursor <= end:
            chunk_end = min(cursor + timedelta(days=30), end)
            from_s = cursor.strftime("%Y-%m-%d")
            to_s = chunk_end.strftime("%Y-%m-%d")
            self.stdout.write(f"Pulling {from_s} .. {to_s} ...")
            n = pull_schoolpay_range(from_s, to_s)
            total += n
            self.stdout.write(f"  {n} new receipt(s)")
            cursor = chunk_end + timedelta(days=1)

        self.stdout.write(self.style.SUCCESS(f"Done. {total} new TuitionLedger row(s)."))
