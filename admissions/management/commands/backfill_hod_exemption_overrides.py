"""Create curriculum overrides for HOD-approved exemption papers missing from the tracker."""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from admissions.exemption_services import (
    apply_hod_exemption_overrides,
    apply_stored_exemption_promotion,
)
from admissions.models import AdmissionChangeRequest, ExemptionRequestLine


class Command(BaseCommand):
    help = (
        "Apply StudentCurriculumOverride rows for HOD-approved exemption papers "
        "so students see exempted courses before Dean/AR finalization."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--request-id",
            type=int,
            default=None,
            help="Only sync this exemption change-request id.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be synced without saving.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        request_id = options["request_id"]

        qs = (
            AdmissionChangeRequest.objects.filter(
                change_type="exemption",
                hod_status="approved",
            )
            .prefetch_related("exemption_lines")
            .order_by("id")
        )
        if request_id is not None:
            qs = qs.filter(pk=request_id)

        checked = 0
        synced_requests = 0
        overrides = 0
        promotions = 0

        with transaction.atomic():
            for req in qs:
                checked += 1
                has_hod_approved = req.exemption_lines.filter(
                    decision=ExemptionRequestLine.DECISION_APPROVED,
                    curriculum_line_id__isnull=False,
                ).exists()
                if not has_hod_approved and not (
                    req.exemption_promotion_year and req.exemption_promotion_term
                ):
                    continue
                decided_by = req.hod_reviewed_by
                if dry_run:
                    count = req.exemption_lines.filter(
                        decision=ExemptionRequestLine.DECISION_APPROVED,
                        curriculum_line_id__isnull=False,
                    ).count()
                    promo = bool(
                        req.exemption_promotion_year
                        and req.exemption_promotion_term
                    )
                    self.stdout.write(
                        f"Req #{req.id}: would sync up to {count} override(s)"
                        + (", apply stored promotion" if promo else "")
                        + "."
                    )
                    synced_requests += 1
                    overrides += count
                    if promo:
                        promotions += 1
                    continue
                n = 0
                if has_hod_approved:
                    n = apply_hod_exemption_overrides(req, decided_by=decided_by)
                promoted = apply_stored_exemption_promotion(req, decided_by=decided_by)
                if n or promoted:
                    synced_requests += 1
                    overrides += n
                    if promoted:
                        promotions += 1
                    parts = []
                    if n:
                        parts.append(f"{n} override(s)")
                    if promoted:
                        parts.append("promotion applied")
                    self.stdout.write(f"Req #{req.id}: synced {', '.join(parts)}.")

            if dry_run:
                transaction.set_rollback(True)

        suffix = " (dry run)" if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"Checked {checked} request(s); synced {synced_requests} "
                f"with {overrides} override(s) and {promotions} promotion(s){suffix}."
            )
        )
