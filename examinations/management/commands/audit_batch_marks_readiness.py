"""
Audit marks-entry readiness for a programme batch (e.g. LLB-377-Main).

Examples:
  python manage.py audit_batch_marks_readiness --batch "LLB-377-Main"
  python manage.py audit_batch_marks_readiness --batch "LLB-377-Main" --csv /tmp/llb377_marks_audit.csv
  python manage.py audit_batch_marks_readiness --batch-id 123
"""
from __future__ import annotations

import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from examinations.services.batch_marks_audit import (
    audit_program_batch,
    course_rows_as_dicts,
    format_summary_text,
    resolve_program_batches,
)


class Command(BaseCommand):
    help = "Audit marks-entry readiness for a ProgramBatch (students, registration, results, windows, policies)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch",
            default="",
            help='ProgramBatch name or label fragment (e.g. "LLB-377-Main").',
        )
        parser.add_argument(
            "--batch-id",
            type=int,
            default=None,
            help="ProgramBatch primary key.",
        )
        parser.add_argument(
            "--csv",
            dest="csv_path",
            default="",
            help="Write per-course audit rows to this CSV path.",
        )

    def handle(self, *args, **options):
        try:
            batches = resolve_program_batches(
                batch=options.get("batch") or None,
                batch_id=options.get("batch_id"),
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        if len(batches) > 1:
            self.stdout.write(
                self.style.WARNING(
                    f"Matched {len(batches)} batches — auditing all. Narrow with --batch-id if needed:"
                )
            )
            for b in batches:
                self.stdout.write(
                    f"  #{b.id} {b.program.short_form or b.program.code} — {b.name}"
                )

        all_rows: list[dict] = []
        for batch in batches:
            summary = audit_program_batch(batch)
            self.stdout.write("")
            self.stdout.write(format_summary_text(summary))
            self.stdout.write("")
            all_rows.extend(course_rows_as_dicts(summary))

        csv_path = (options.get("csv_path") or "").strip()
        if csv_path:
            path = Path(csv_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            fieldnames = list(all_rows[0].keys()) if all_rows else [
                "batch_id",
                "batch_name",
                "program",
                "course_unit_id",
                "code",
                "name",
            ]
            with path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(all_rows)
            self.stdout.write(self.style.SUCCESS(f"Wrote {len(all_rows)} course row(s) to {path}"))
