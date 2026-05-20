"""
List applications whose programme choices were changed by staff via the admin API.

Reads `audit.AuditLog` entries with action ``program_choice_admin_change``.
Events are only recorded after deploying the logging change; earlier edits are not listed.

Usage::

    python manage.py list_admin_programme_changes
    python manage.py list_admin_programme_changes --date 2026-05-16
    python manage.py list_admin_programme_changes --json
    python manage.py list_admin_programme_changes --output today_staff_programme_changes.csv
"""
from __future__ import annotations

import csv
import json
from argparse import ArgumentParser
from datetime import date, datetime, timedelta
from pathlib import Path

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from audit.models import AuditLog
from admissions.models import Application
from admissions.utils.application_programs_display import ordered_programs_for_application


ACTION = "program_choice_admin_change"


def programme_names_from_audit_description(desc: str) -> list[str]:
    """Snapshot programme names staff saved (see ChangeApplicationProgramme audit text)."""
    if not desc:
        return []
    marker = "Programmes:"
    if marker not in desc:
        return []
    after = desc.split(marker, 1)[1].strip()
    prog_segment = after.split(";", 1)[0].strip()
    return [x.strip() for x in prog_segment.split(",") if x.strip()]


class Command(BaseCommand):
    help = "List applications updated by staff Change Programme (today or --date)."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--date",
            default=None,
            help="Calendar date in YYYY-MM-DD (default: today in the active timezone).",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Print JSON instead of a table.",
        )
        parser.add_argument(
            "--output",
            "-o",
            default=None,
            help="Write names and choices as CSV (UTF-8 with BOM for Excel) to this path.",
        )

    def handle(self, *args, **options):
        if options["json"] and options["output"]:
            raise CommandError("Use either --json or --output, not both.")

        if options["date"]:
            try:
                day = date.fromisoformat(str(options["date"]))
            except ValueError as exc:
                self.stderr.write("Invalid --date; use YYYY-MM-DD.")
                raise SystemExit(1) from exc
        else:
            day = timezone.localdate()

        start = timezone.make_aware(
            datetime.combine(day, datetime.min.time()),
            timezone.get_current_timezone(),
        )
        end = start + timedelta(days=1)

        app_ct = ContentType.objects.get_for_model(Application)
        logs = (
            AuditLog.objects.filter(
                action=ACTION,
                content_type=app_ct,
                timestamp__gte=start,
                timestamp__lt=end,
            )
            .select_related("user")
            .order_by("timestamp", "id")
        )

        logs_list = list(logs)
        app_ids = sorted(
            {log.object_id for log in logs_list if log.object_id is not None}
        )

        apps = {
            a.pk: a
            for a in Application.objects.filter(pk__in=app_ids).select_related("campus").prefetch_related(
                "program_choices__program", "program_choices__program__faculty"
            )
        }

        rows_out: list[dict] = []
        for log in logs_list:
            aid = log.object_id
            app = apps.get(aid) if aid else None

            from_desc = programme_names_from_audit_description(log.description)
            if from_desc:
                names = from_desc
            elif app:
                names = [p.name for p in ordered_programs_for_application(app)]
            else:
                names = []

            c1 = names[0] if len(names) > 0 else ""
            c2 = names[1] if len(names) > 1 else ""
            c3 = names[2] if len(names) > 2 else ""

            last_name = first_name = status = applicant_email = ""
            campus_name = ""
            if app:
                last_name = app.last_name or ""
                first_name = app.first_name or ""
                status = app.status or ""
                applicant_email = app.email or ""
                if app.campus:
                    campus_name = app.campus.name or ""

            staff = (
                getattr(log.user, "email", None)
                or getattr(log.user, "username", None)
                or str(log.user_id or "")
            )

            rows_out.append(
                {
                    "audit_id": log.pk,
                    "application_id": aid,
                    "updated_at": log.timestamp.isoformat(),
                    "staff": staff,
                    "last_name": last_name,
                    "first_name": first_name,
                    "applicant_email": applicant_email,
                    "application_status": status,
                    "campus": campus_name,
                    "program_choice_1": c1,
                    "program_choice_2": c2,
                    "program_choice_3": c3,
                    "programmes_joined": " | ".join(names),
                    "audit_description": log.description,
                }
            )

        if options["output"]:
            path = Path(options["output"]).expanduser()
            fieldnames = [
                "updated_at",
                "staff",
                "application_id",
                "last_name",
                "first_name",
                "applicant_email",
                "application_status",
                "campus",
                "program_choice_1",
                "program_choice_2",
                "program_choice_3",
                "programmes_joined",
                "audit_description",
            ]
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=fieldnames)
                w.writeheader()
                for r in rows_out:
                    w.writerow({k: r[k] for k in fieldnames})
            self.stdout.write(
                f"Wrote {len(rows_out)} row(s) to {path.resolve()}\n"
            )
            return

        if options["json"]:
            self.stdout.write(json.dumps(rows_out, indent=2))
            return

        self.stdout.write(
            f"Staff programme changes on {day.isoformat()} ({start.tzinfo}): {len(rows_out)} event(s)\n"
        )
        if not rows_out:
            self.stdout.write(
                "(No audit rows. Logging only starts after deploy; use a date when staff used Change Programme.)\n"
            )
            return

        for r in rows_out:
            self.stdout.write(
                f"  app_id={r['application_id']} at {r['updated_at']} by {r['staff']}"
                f" | {r['last_name']}, {r['first_name']} | {r['applicant_email']}\n"
                f"    choices: {r['programmes_joined'] or '(none parsed)'}\n"
            )
