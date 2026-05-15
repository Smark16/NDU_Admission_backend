"""
Export applications whose programme choices match known bulk-assignment templates.

Read-only: writes a CSV file only; does not modify the database.

Usage (server, venv activated)::

    python manage.py export_cloned_program_applications
    python manage.py export_cloned_program_applications --output /tmp/affected_applications.csv
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from datetime import date, datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from admissions.models import Application, ApplicationProgramChoice
from Programs.models import Program

# Bulk templates identified on production (May 2026).
CLONED_SIGNATURES = {
    (28, 29, 30),
    (162, 163, 164),
    (181, 190, 195),
    (154, 153, 210),
    (31, 77, 76),
}

TEMPLATE_LABELS = {
    (28, 29, 30): "BEng Civil/Electrical (Day/Weekend)",
    (162, 163, 164): "BEng Civil/Electrical/Geomatics (Main)",
    (181, 190, 195): "Diploma Civil/Electrical/Mechanical (Main)",
    (154, 153, 210): "HEC Business/Biological/Business (Main)",
    (31, 77, 76): "BEng Geomatics + Software Eng",
}


class Command(BaseCommand):
    help = "Export CSV of applications on cloned programme-choice templates (read-only)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            "-o",
            default=None,
            help="Output CSV path (default: cloned_program_applications_YYYYMMDD_HHMMSS.csv in cwd).",
        )
        parser.add_argument(
            "--order-field",
            default=None,
            help="Ordering field on ApplicationProgramChoice (default: auto: choice_order or preference).",
        )
        parser.add_argument(
            "--date-from",
            default=None,
            help="Only applications created on/after YYYY-MM-DD (optional).",
        )
        parser.add_argument(
            "--date-to",
            default=None,
            help="Only applications created on/before YYYY-MM-DD (optional).",
        )

    def _resolve_order_field(self, explicit: str | None) -> str:
        if explicit:
            return explicit
        for name in ("choice_order", "preference", "rank", "order"):
            try:
                ApplicationProgramChoice._meta.get_field(name)
            except Exception:
                continue
            return name
        raise RuntimeError(
            "ApplicationProgramChoice has no choice_order/preference field."
        )

    def _parse_date(self, value: str, label: str) -> date:
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date()
        except ValueError as exc:
            raise CommandError(f"Invalid {label}: use YYYY-MM-DD") from exc

    def handle(self, *args, **options):
        order_field = self._resolve_order_field(options["order_field"])
        date_from = (
            self._parse_date(options["date_from"], "date-from")
            if options["date_from"]
            else None
        )
        date_to = (
            self._parse_date(options["date_to"], "date-to") if options["date_to"] else None
        )
        if date_from and date_to and date_from > date_to:
            raise CommandError("date-from must be on or before date-to.")

        out_path = options["output"]
        if not out_path:
            stamp = timezone.now().strftime("%Y%m%d_%H%M%S")
            out_path = f"cloned_program_applications_{stamp}.csv"
        out_path = Path(out_path)

        by_app = defaultdict(list)
        for aid, pid, ord_val in ApplicationProgramChoice.objects.values_list(
            "application_id", "program_id", order_field
        ):
            by_app[aid].append((ord_val, pid))

        program_names = dict(Program.objects.values_list("id", "name"))

        rows = []
        for app_id, pairs in by_app.items():
            sig = tuple(pid for _, pid in sorted(pairs))
            if sig not in CLONED_SIGNATURES:
                continue
            try:
                app = Application.objects.select_related("batch", "campus", "academic_level").get(
                    pk=app_id
                )
            except Application.DoesNotExist:
                continue

            if date_from and app.created_at.date() < date_from:
                continue
            if date_to and app.created_at.date() > date_to:
                continue

            ordered = sorted(pairs, key=lambda x: x[0])
            choice_lines = []
            for ord_val, pid in ordered:
                choice_lines.append(
                    f"{ord_val}. [{pid}] {program_names.get(pid, '?')}"
                )

            rows.append(
                {
                    "application_id": app.id,
                    "first_name": app.first_name,
                    "last_name": app.last_name,
                    "email": app.email,
                    "phone": app.phone or "",
                    "status": app.status,
                    "batch": app.batch.name if app.batch_id else "",
                    "campus": app.campus.name if app.campus_id else "",
                    "academic_level": app.academic_level.name if app.academic_level_id else "",
                    "template_key": str(sig),
                    "template_label": TEMPLATE_LABELS.get(sig, "unknown"),
                    "program_ids": ", ".join(str(pid) for _, pid in ordered),
                    "programmes": " | ".join(choice_lines),
                    "created_at": app.created_at.isoformat() if app.created_at else "",
                }
            )

        rows.sort(key=lambda r: (r["template_label"], r["last_name"], r["first_name"]))

        fieldnames = [
            "application_id",
            "first_name",
            "last_name",
            "email",
            "phone",
            "status",
            "batch",
            "campus",
            "academic_level",
            "template_label",
            "template_key",
            "program_ids",
            "programmes",
            "created_at",
        ]

        self.stdout.write(f"Using order field: {order_field}")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        self.stdout.write(self.style.SUCCESS(f"Wrote {len(rows)} rows to {out_path.resolve()}"))
