"""
Compare portal tuition (STK) payments vs TuitionLedger from SchoolPay transaction sync.

Usage:
  python manage.py check_schoolpay_sync_coverage
  python manage.py check_schoolpay_sync_coverage --days 30
  python manage.py check_schoolpay_sync_coverage --student-id 1011774262
  python manage.py check_schoolpay_sync_coverage --pull-today
"""
from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from admissions.models import AdmittedStudent
from payments.models import StudentTuitionPayment, TuitionLedger


class Command(BaseCommand):
    help = (
        "Check whether portal mobile-money tuition payments also appear in "
        "TuitionLedger (transaction sync). Helps answer SAGE/sync coverage."
    )

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=14, help="Look back N days (default 14)")
        parser.add_argument("--student-id", type=str, default="", help="Filter by SchoolPay student_id")
        parser.add_argument(
            "--pull-today",
            action="store_true",
            help="Fetch today's transactions from SchoolPay API before comparing",
        )

    def handle(self, *args, **options):
        days = max(1, int(options["days"]))
        since = timezone.now() - timedelta(days=days)
        student_id = (options["student_id"] or "").strip()

        if options["pull_today"]:
            self._pull_today()

        portal_qs = StudentTuitionPayment.objects.filter(
            source="scheduled",
            payment_method="mobile_money",
            created_at__gte=since,
        ).select_related("student")
        if student_id:
            portal_qs = portal_qs.filter(student__student_id=student_id)

        portal = list(portal_qs.order_by("-created_at")[:200])
        self.stdout.write(self.style.NOTICE(f"\n=== Portal tuition STK (last {days} days) ==="))
        self.stdout.write(f"Count: {len(portal)}\n")

        in_sync = 0
        portal_only = 0
        for p in portal:
            sid = p.student.student_id if p.student_id else "?"
            receipt = (p.receipt_number or "").strip()
            ledger = None
            if receipt:
                ledger = TuitionLedger.objects.filter(schoolpay_receipt_number=receipt).first()
            if not ledger and p.payment_reference:
                ledger = TuitionLedger.objects.filter(
                    source_channel_transaction_id=p.payment_reference
                ).first()

            matched = ledger is not None
            if matched:
                in_sync += 1
            else:
                portal_only += 1

            status = self.style.SUCCESS("IN SYNC") if matched else self.style.WARNING("PORTAL ONLY")
            self.stdout.write(
                f"  [{status}] {p.created_at:%Y-%m-%d %H:%M} | student={sid} | "
                f"UGX {p.amount} | status={p.status} | receipt={receipt or '-'} | "
                f"ref={p.payment_reference or '-'}"
            )
            if ledger:
                self.stdout.write(
                    f"           ledger: code={ledger.student_payment_code} | "
                    f"channel={ledger.source_payment_channel} | "
                    f"detail={ (ledger.source_channel_trans_detail or '')[:60]}"
                )

        self.stdout.write(
            f"\nSummary: {in_sync} also in TuitionLedger (sync/SAGE path), "
            f"{portal_only} portal-only (likely NOT in Sage via sync)\n"
        )

        ledger_qs = TuitionLedger.objects.filter(payment_date_time__gte=since)
        if student_id:
            ledger_qs = ledger_qs.filter(student_payment_code=student_id)

        self.stdout.write(self.style.NOTICE(f"=== TuitionLedger / sync sample (last {days} days) ==="))
        self.stdout.write(f"Count: {ledger_qs.count()}\n")

        channels: dict[str, int] = {}
        no_student = 0
        for row in ledger_qs.order_by("-payment_date_time")[:500]:
            ch = (row.source_payment_channel or "unknown").strip() or "unknown"
            channels[ch] = channels.get(ch, 0) + 1
            if not row.student_id:
                no_student += 1

        self.stdout.write("Payment channels (sample):")
        for ch, n in sorted(channels.items(), key=lambda x: -x[1]):
            self.stdout.write(f"  {ch}: {n}")
        self.stdout.write(f"Ledger rows with no matched student: {no_student}\n")

        self.stdout.write(self.style.NOTICE("=== How to read this ==="))
        self.stdout.write(
            "If portal STK payments are mostly PORTAL ONLY, Sage (via transaction sync) "
            "will not see them. Official tuition for Sage = pay with student payment code "
            "at agent/USSD, then run transaction sync / manual-reconcile.\n"
        )

    def _pull_today(self):
        from payments.utils.Transaction_sync import fetch_transactions_by_date, reconcile_transactions

        today = timezone.now().date().strftime("%Y-%m-%d")
        self.stdout.write(f"Pulling SchoolPay transactions for {today}...")
        try:
            data = fetch_transactions_by_date(today)
            n = reconcile_transactions(data)
            self.stdout.write(self.style.SUCCESS(f"Synced {n} new ledger row(s).\n"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Sync failed: {e}\n"))
