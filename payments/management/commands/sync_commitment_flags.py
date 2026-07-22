from django.core.management.base import BaseCommand

from payments.commitment_queryset import sync_admission_fee_paid_flags


class Command(BaseCommand):
    help = (
        "Set admission_fee_paid=True for admitted students who already meet the "
        "commitment threshold via portal/SchoolPay but still have the flag false. "
        "Makes bonafide commitment filters fast and accurate."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="How many unpaid-flag students to evaluate per query batch.",
        )
        parser.add_argument(
            "--max",
            type=int,
            default=None,
            help="Optional cap on candidates (for a dry trial run).",
        )

    def handle(self, *args, **options):
        result = sync_admission_fee_paid_flags(
            batch_size=options["batch_size"],
            max_students=options["max"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Commitment flag sync done. candidates={result['candidates']} "
                f"updated={result['updated']}"
            )
        )
