"""Re-sync exemption request-level stage fields from per-paper line decisions."""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from admissions.exemption_services import ensure_exemption_request_stages_synced
from admissions.models import AdmissionChangeRequest


class Command(BaseCommand):
    help = (
        "Align hod_status / dean_status / ar_status on every exemption request "
        "with per-paper HOD, Dean, and AR decisions."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report mismatches without saving.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        qs = (
            AdmissionChangeRequest.objects.filter(change_type="exemption")
            .prefetch_related("exemption_lines")
            .order_by("id")
        )
        checked = 0
        repaired = 0
        with transaction.atomic():
            for req in qs:
                checked += 1
                before = (req.hod_status, req.dean_status, req.ar_status, req.status)
                ensure_exemption_request_stages_synced(req, save=not dry_run)
                after = (req.hod_status, req.dean_status, req.ar_status, req.status)
                if before != after:
                    repaired += 1
                    self.stdout.write(
                        f"Req #{req.id}: {before[0]}/{before[1]}/{before[2]} "
                        f"-> {after[0]}/{after[1]}/{after[2]}"
                    )
            if dry_run:
                transaction.set_rollback(True)

        suffix = " (dry run)" if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"Checked {checked} exemption request(s); repaired {repaired}{suffix}."
            )
        )
