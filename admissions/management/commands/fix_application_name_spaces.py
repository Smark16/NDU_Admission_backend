"""Trim and collapse whitespace in application name fields."""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from admissions.models import Application
from admissions.utils.person_name import normalize_name_part


NAME_FIELDS = ("title", "first_name", "middle_name", "last_name", "next_of_kin_name")


class Command(BaseCommand):
    help = "Fix extra spaces in application name fields (e.g. double space when middle name is blank)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report changes without writing.",
        )
        parser.add_argument(
            "--reg-no",
            dest="reg_no",
            help="Fix one admitted student's application only.",
        )

    def handle(self, *args, **options):
        dry = bool(options.get("dry_run"))
        reg_no = (options.get("reg_no") or "").strip()

        qs = Application.objects.all().order_by("id")
        if reg_no:
            qs = qs.filter(admittedstudent__reg_no__iexact=reg_no)

        updated = 0
        samples: list[str] = []

        with transaction.atomic():
            for app in qs.iterator(chunk_size=500):
                changes: dict[str, str] = {}
                for field in NAME_FIELDS:
                    raw = getattr(app, field, None) or ""
                    if not raw:
                        continue
                    normalized = normalize_name_part(raw)
                    if normalized != raw:
                        changes[field] = normalized

                if not changes:
                    continue

                updated += 1
                before = app.full_name if hasattr(app, "full_name") else ""
                if len(samples) < 20:
                    for field, val in changes.items():
                        old = getattr(app, field)
                        samples.append(f"  app={app.pk} {field}: {old!r} → {val!r}")
                    after_parts = [
                        changes.get("first_name", app.first_name),
                        changes.get("middle_name", app.middle_name),
                        changes.get("last_name", app.last_name),
                    ]
                    from admissions.utils.person_name import format_person_name

                    after = format_person_name(*after_parts)
                    if before != after:
                        samples.append(f"    display: {before!r} → {after!r}")

                if not dry:
                    for field, val in changes.items():
                        setattr(app, field, val)
                    app.save(update_fields=[*changes.keys(), "updated_at"])

            if dry:
                transaction.set_rollback(True)

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. applications_updated={updated}"
                + (" (dry-run)" if dry else "")
            )
        )
        for line in samples:
            self.stdout.write(line)
