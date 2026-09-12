"""
Reverse SPE promotions that ran before Accounts billed.

New rule: HOD only stores the target; SPE moves when Accounts bills.
This repairs students already moved while accounts_status is still pending.

Keeps exemption_promotion_year/term on the CR so Accounts Create charges
re-applies the promotion.

  python manage.py reverse_premature_exemption_promotions           # dry-run
  python manage.py reverse_premature_exemption_promotions --apply
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from admissions.models import AdmissionChangeRequest
from admissions.exemption_services import (
    exemption_promotion_applied,
    exemption_promotion_proposed,
    reverse_exemption_promotion_if_applied,
)


class Command(BaseCommand):
    help = (
        "Move students back from HOD-applied exemption promotions until Accounts bills. "
        "Dry-run by default; pass --apply to write."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually reverse SPE positions (default is dry-run).",
        )
        parser.add_argument(
            "--cr-id",
            type=int,
            default=None,
            help="Limit to one change request id.",
        )

    def handle(self, *args, **options):
        apply = bool(options["apply"])
        cr_id = options.get("cr_id")

        qs = (
            AdmissionChangeRequest.objects.filter(change_type="exemption")
            .exclude(accounts_status__in=("billed", "confirmed"))
            .exclude(exemption_promotion_year__isnull=True)
            .exclude(exemption_promotion_term__isnull=True)
            .select_related(
                "admitted_student",
                "admitted_student__programme_enrollment",
            )
            .order_by("id")
        )
        if cr_id:
            qs = qs.filter(pk=cr_id)

        candidates = []
        skipped_no_from = []
        skipped_not_at_target = []

        for cr in qs:
            if not exemption_promotion_proposed(cr):
                continue
            if not exemption_promotion_applied(cr):
                skipped_not_at_target.append(cr)
                continue
            if (
                cr.exemption_promotion_from_year is None
                or cr.exemption_promotion_from_term is None
            ):
                skipped_no_from.append(cr)
                continue
            candidates.append(cr)

        self.stdout.write(
            self.style.NOTICE(
                f"{'APPLY' if apply else 'DRY-RUN'}: "
                f"{len(candidates)} to reverse, "
                f"{len(skipped_not_at_target)} already waiting (not at target), "
                f"{len(skipped_no_from)} missing from-year/term (manual)."
            )
        )

        for cr in skipped_no_from:
            s = cr.admitted_student
            self.stdout.write(
                self.style.WARNING(
                    f"  SKIP CR {cr.id} {s.reg_no} — promoted to "
                    f"Y{cr.exemption_promotion_year}T{cr.exemption_promotion_term} "
                    f"but from_year/term not recorded"
                )
            )

        reversed_n = 0
        errors = 0
        for cr in candidates:
            s = cr.admitted_student
            enr = getattr(s, "programme_enrollment", None)
            label = (
                f"CR {cr.id} {s.reg_no} "
                f"Y{cr.exemption_promotion_from_year}T{cr.exemption_promotion_from_term} "
                f"<- Y{cr.exemption_promotion_year}T{cr.exemption_promotion_term}"
            )
            if not apply:
                self.stdout.write(f"  would reverse {label}")
                continue
            try:
                with transaction.atomic():
                    ok = reverse_exemption_promotion_if_applied(cr)
                    if not ok:
                        self.stdout.write(self.style.WARNING(f"  no-op {label}"))
                        continue
                    note = (
                        f"[{timezone.now():%Y-%m-%d %H:%M}] Premature exemption promotion "
                        f"reversed pending Accounts billing "
                        f"(back to Y{cr.exemption_promotion_from_year}"
                        f"T{cr.exemption_promotion_from_term}; "
                        f"target Y{cr.exemption_promotion_year}"
                        f"T{cr.exemption_promotion_term} kept for Accounts)."
                    )
                    cr.review_notes = "\n".join(
                        filter(None, [cr.review_notes, note])
                    )[:20000]
                    cr.save(update_fields=["review_notes", "updated_at"])
                    enr.refresh_from_db()
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  reversed {label} "
                            f"now Y{enr.current_year_of_study}T{enr.current_term_number} "
                            f"entry Y{enr.entry_year_of_study}T{enr.entry_term_number}"
                        )
                    )
                    reversed_n += 1
            except Exception as exc:
                errors += 1
                self.stdout.write(self.style.ERROR(f"  FAIL {label}: {exc}"))

        if not apply:
            self.stdout.write(
                self.style.WARNING("Dry-run only. Re-run with --apply to write changes.")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Done. Reversed {reversed_n}, errors {errors}."
                )
            )
