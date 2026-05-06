"""
Seed ApplicationFee rows so the applicant portal can resolve fees (intake + nationality + academic level).

Usage:
  python manage.py seed_application_fees
  python manage.py seed_application_fees --all-batches
  python manage.py seed_application_fees --local-amount 50000 --international-amount 100000

Cloning the repo does not copy database rows — run this (or create fees in Fee Management) on new environments.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand

from admissions.models import AcademicLevel, Batch
from payments.models import ApplicationFee


class Command(BaseCommand):
    help = "Create ApplicationFee entries for admission batches (Local + International), linked to all active academic levels."

    def add_arguments(self, parser):
        parser.add_argument(
            "--all-batches",
            action="store_true",
            help="Include inactive batches as well (default: only is_active=True).",
        )
        parser.add_argument(
            "--local-amount",
            default="50000",
            help="UGX amount for Local applicants (default 50000).",
        )
        parser.add_argument(
            "--international-amount",
            default="100000",
            help="UGX amount for International applicants (default 100000).",
        )
        parser.add_argument(
            "--fee-type",
            default="Application Fee",
            help='fee_type field value (default "Application Fee").',
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print actions only; do not write to the database.",
        )

    def handle(self, *args, **options):
        active_only = not options["all_batches"]
        dry_run = options["dry_run"]
        fee_type = options["fee_type"]
        local_amt = Decimal(str(options["local_amount"]))
        intl_amt = Decimal(str(options["international_amount"]))

        qs = Batch.objects.all().order_by("-is_active", "-created_at")
        if active_only:
            qs = qs.filter(is_active=True)

        batches = list(qs)
        if not batches:
            self.stdout.write(self.style.WARNING("No batches found. Create an intake (Batch) first."))
            return

        levels = list(AcademicLevel.objects.filter(is_active=True).order_by("name"))
        if not levels:
            self.stdout.write(
                self.style.WARNING("No active AcademicLevel rows. Add levels in admin, then re-run.")
            )
            return

        created_count = 0
        updated_count = 0

        for batch in batches:
            for nationality_type, amount in (("Local", local_amt), ("International", intl_amt)):
                existing = (
                    ApplicationFee.objects.filter(admission_period=batch)
                    .filter(nationality_type__iexact=nationality_type)
                    .first()
                )

                if existing:
                    if dry_run:
                        self.stdout.write(
                            f"[dry-run] Would update fee pk={existing.pk} — {batch} / {nationality_type} / {amount} UGX"
                        )
                    else:
                        existing.fee_type = fee_type
                        existing.amount = amount
                        existing.is_active = True
                        existing.save(update_fields=["fee_type", "amount", "is_active"])
                        existing.academic_level.set(levels)
                        updated_count += 1
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"Updated fee pk={existing.pk} — {batch} / {nationality_type} / {amount} UGX"
                            )
                        )
                    continue

                if dry_run:
                    self.stdout.write(
                        f"[dry-run] Would create ApplicationFee {batch} / {nationality_type} / {amount} UGX + {len(levels)} levels"
                    )
                    continue

                fee = ApplicationFee.objects.create(
                    fee_type=fee_type,
                    nationality_type=nationality_type,
                    amount=amount,
                    admission_period=batch,
                    is_active=True,
                )
                fee.academic_level.set(levels)
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f"Created fee pk={fee.pk} — {batch} / {nationality_type} / {amount} UGX")
                )

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run finished — no database changes."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Done. Created: {created_count}, updated: {updated_count}."))
