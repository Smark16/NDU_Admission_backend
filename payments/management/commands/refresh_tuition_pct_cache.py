from django.core.management.base import BaseCommand

from payments.tuition_pct_cache import backfill_bonafide_tuition_pct_cache


class Command(BaseCommand):
    help = (
        "Compute AdmittedStudent.registration_tuition_pct_met for bonafide students "
        "so /api/admissions/list_bonafide_students/?tuition_pct_met=… stays fast."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=200,
            help="How many students to evaluate per batch.",
        )
        parser.add_argument(
            "--max",
            type=int,
            default=None,
            help="Optional cap on students with payment activity to evaluate.",
        )

    def handle(self, *args, **options):
        result = backfill_bonafide_tuition_pct_cache(
            batch_size=options["batch_size"],
            max_students=options["max"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Tuition %% cache backfill done. "
                f"stamped_no_activity={result['stamped_no_activity']} "
                f"candidates={result['candidates']} "
                f"scanned={result['scanned']} "
                f"met={result['met']} unmet={result['unmet']}"
            )
        )
