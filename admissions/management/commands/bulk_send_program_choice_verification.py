"""
Bulk email applicants asking them to confirm programme(s) of choice.

Default filters (affected cohort):
  - created_at date from 2026-04-16 through 2026-05-14 (inclusive)
  - status in: submitted, under_review, revoked, accepted, approved
  - optional: only applications on known bulk-cloned programme templates

Safety:
  - Dry-run by default (lists recipients, sends nothing).
  - Pass --send to deliver via SendGrid (same as other admission emails).

Examples::

    python manage.py bulk_send_program_choice_verification --dry-run
    python manage.py bulk_send_program_choice_verification --dry-run --no-cloned-only
    python manage.py bulk_send_program_choice_verification --send --limit 5
    python manage.py bulk_send_program_choice_verification --send
"""
from __future__ import annotations

import csv
import time
from datetime import date, datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from admissions.models import Application
from admissions.utils.program_choice_integrity import application_ids_with_suspect_program_choices
from admissions.utils.program_choice_verification_email import (
    build_program_choice_verification_email,
)
from ndu_portal.send_grid import send_configurable_email

DEFAULT_STATUSES = (
    "submitted",
    "under_review",
    "revoked",
    "accepted",
    "approved",
)

class Command(BaseCommand):
    help = (
        "Bulk email applicants to confirm programme(s) of choice "
        "(dry-run by default; use --send to deliver)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--send",
            action="store_true",
            help="Actually send emails (default: dry-run only).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Explicit dry-run (default when --send is omitted).",
        )
        parser.add_argument(
            "--date-from",
            default="2026-04-16",
            help="Include applications created on or after this date (YYYY-MM-DD).",
        )
        parser.add_argument(
            "--date-to",
            default="2026-05-14",
            help="Include applications created on or before this date (YYYY-MM-DD).",
        )
        parser.add_argument(
            "--status",
            action="append",
            dest="statuses",
            help=f"Application status (repeatable). Default: {', '.join(DEFAULT_STATUSES)}",
        )
        parser.add_argument(
            "--cloned-only",
            action="store_true",
            default=True,
            help="Only applications on bulk-cloned programme templates (default: on).",
        )
        parser.add_argument(
            "--no-cloned-only",
            action="store_false",
            dest="cloned_only",
            help="Include all applications in date/status range, not only cloned templates.",
        )
        parser.add_argument(
            "--application-ids-csv",
            default=None,
            help="Optional CSV with application_id column to restrict recipients.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Send to at most N applications (for testing).",
        )
        parser.add_argument(
            "--delay-seconds",
            type=float,
            default=0.5,
            help="Pause between SendGrid calls when --send (default: 0.5).",
        )
        parser.add_argument(
            "--report-csv",
            default=None,
            help="Write dry-run or send report to this CSV path.",
        )

    def handle(self, *args, **options):
        do_send = bool(options["send"])
        if not do_send and not options["dry_run"]:
            self.stdout.write(
                self.style.WARNING("Dry-run mode (pass --send to deliver emails).")
            )

        date_from = self._parse_date(options["date_from"], "date-from")
        date_to = self._parse_date(options["date_to"], "date-to")
        if date_from > date_to:
            raise CommandError("date-from must be on or before date-to.")

        statuses = [s.strip().lower() for s in (options["statuses"] or list(DEFAULT_STATUSES))]
        status_q = Q()
        for s in statuses:
            status_q |= Q(status__iexact=s)

        qs = (
            Application.objects.filter(status_q)
            .filter(created_at__date__gte=date_from, created_at__date__lte=date_to)
            .exclude(email__isnull=True)
            .exclude(email="")
            .order_by("id")
        )

        if options["cloned_only"]:
            cloned_ids = application_ids_with_suspect_program_choices()
            qs = qs.filter(id__in=cloned_ids)
            self.stdout.write(f"Cloned-template application IDs: {len(cloned_ids)}")

        if options["application_ids_csv"]:
            allowed = self._load_ids_csv(options["application_ids_csv"])
            qs = qs.filter(id__in=allowed)
            self.stdout.write(f"Restricted to {len(allowed)} IDs from CSV")

        if options["limit"]:
            qs = qs[: options["limit"]]

        applications = list(qs)
        if not applications:
            self.stdout.write(self.style.WARNING("No matching applications."))
            return

        self.stdout.write(
            f"Recipients: {len(applications)} | "
            f"dates {date_from} .. {date_to} | statuses {statuses} | "
            f"cloned_only={options['cloned_only']} | mode={'SEND' if do_send else 'DRY-RUN'}"
        )

        report_rows = []
        sent = failed = skipped = 0

        for app in applications:
            email = (app.email or "").strip()
            if not email:
                skipped += 1
                continue

            subject, body = build_program_choice_verification_email(app)
            row = {
                "application_id": app.id,
                "email": email,
                "first_name": app.first_name,
                "last_name": app.last_name,
                "status": app.status,
                "created_at": app.created_at.isoformat() if app.created_at else "",
                "mode": "send" if do_send else "dry-run",
                "result": "",
            }

            if do_send:
                ok = send_configurable_email(email, subject, body)
                row["result"] = "sent" if ok else "failed"
                if ok:
                    sent += 1
                else:
                    failed += 1
                time.sleep(max(0.0, float(options["delay_seconds"])))
            else:
                row["result"] = "would_send"
                sent += 1

            report_rows.append(row)

        if options["report_csv"]:
            self._write_report(options["report_csv"], report_rows)

        self.stdout.write("")
        if do_send:
            self.stdout.write(self.style.SUCCESS(f"Sent: {sent}"))
            if failed:
                self.stdout.write(self.style.ERROR(f"Failed: {failed}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Would send: {sent}"))
        if skipped:
            self.stdout.write(self.style.WARNING(f"Skipped (no email): {skipped}"))

        if not do_send and applications:
            sample = applications[:5]
            self.stdout.write("\nSample recipients:")
            for app in sample:
                self.stdout.write(f"  {app.id} | {app.email} | {app.status} | {app.first_name} {app.last_name}")

    def _parse_date(self, value: str, label: str) -> date:
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date()
        except ValueError as exc:
            raise CommandError(f"Invalid {label}: use YYYY-MM-DD") from exc

    def _load_ids_csv(self, path: str) -> set[int]:
        p = Path(path)
        if not p.is_file():
            raise CommandError(f"CSV not found: {path}")
        ids = set()
        with p.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames:
                raise CommandError("CSV has no header row")
            key = None
            for candidate in ("application_id", "id", "applicationid"):
                if candidate in reader.fieldnames:
                    key = candidate
                    break
            if key is None:
                key = reader.fieldnames[0]
            for row in reader:
                raw = (row.get(key) or "").strip()
                if raw.isdigit():
                    ids.add(int(raw))
        if not ids:
            raise CommandError(f"No application IDs found in {path}")
        return ids

    def _write_report(self, path: str, rows: list[dict]) -> None:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        fields = [
            "application_id",
            "email",
            "first_name",
            "last_name",
            "status",
            "created_at",
            "mode",
            "result",
        ]
        with out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        self.stdout.write(self.style.SUCCESS(f"Report: {out.resolve()}"))
