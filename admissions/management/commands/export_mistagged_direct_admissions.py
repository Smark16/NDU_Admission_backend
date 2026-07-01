"""
Export direct-admission records mis-tagged as online (is_direct_entry=False).

These are typically created via direct_admission_entry with source=direct_entry
but without is_direct_entry / application_fee_paid flags set.

Usage::

    python manage.py export_mistagged_direct_admissions
    python manage.py export_mistagged_direct_admissions --csv /tmp/direct_admission_audit.csv
    python manage.py export_mistagged_direct_admissions --stdout
"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db.models import Count

from admissions.models import AdmittedStudent, Application


def mistagged_direct_admission_qs():
    return (
        Application.objects.filter(
            is_direct_entry=False,
            application_fee_paid=False,
            status__in=["Admitted", "admitted"],
            source="direct_entry",
        )
        .select_related("batch", "campus", "academic_level")
        .order_by("-created_at")
    )


def row_for_application(app: Application) -> dict:
    admission = (
        AdmittedStudent.objects.filter(application=app)
        .select_related("admitted_by", "admitted_program")
        .order_by("-id")
        .first()
    )
    admitted_by = admission.admitted_by if admission else None
    program = admission.admitted_program.name if admission and admission.admitted_program else ""

    return {
        "application_id": app.id,
        "first_name": app.first_name,
        "last_name": app.last_name,
        "email": app.email,
        "phone": app.phone or "",
        "status": app.status,
        "source": app.source,
        "is_direct_entry": app.is_direct_entry,
        "application_fee_paid": app.application_fee_paid,
        "batch": app.batch.name if app.batch_id else "",
        "campus": app.campus.name if app.campus_id else "",
        "academic_level": app.academic_level.name if app.academic_level_id else "",
        "program": program,
        "submitted_at": app.created_at.strftime("%Y-%m-%d %H:%M") if app.created_at else "",
        "admitted_by_name": admitted_by.get_full_name() if admitted_by else "",
        "admitted_by_email": admitted_by.email if admitted_by else "",
        "reg_no": admission.reg_no if admission else "",
    }


class Command(BaseCommand):
    help = "Export mis-tagged direct admission entries (names + admitting staff)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            type=str,
            default="",
            help="Write CSV to this path (default: reports/mistagged_direct_admissions_<timestamp>.csv)",
        )
        parser.add_argument(
            "--stdout",
            action="store_true",
            help="Print table to stdout instead of writing a file",
        )

    def handle(self, *args, **options):
        qs = mistagged_direct_admission_qs()
        rows = [row_for_application(app) for app in qs]

        self.stdout.write(f"Found {len(rows)} mis-tagged direct admission record(s).\n")

        if not rows:
            return

        by_staff = (
            AdmittedStudent.objects.filter(application__in=qs)
            .values(
                "admitted_by__email",
                "admitted_by__first_name",
                "admitted_by__last_name",
            )
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        self.stdout.write("Admitted by (summary):")
        for row in by_staff:
            email = row["admitted_by__email"] or "(unknown)"
            name = f"{row['admitted_by__first_name'] or ''} {row['admitted_by__last_name'] or ''}".strip()
            self.stdout.write(f"  {row['count']:>3}  {name}  <{email}>")

        fieldnames = list(rows[0].keys())

        if options["stdout"]:
            self.stdout.write("")
            self.stdout.write(
                "\t".join(
                    [
                        "ID",
                        "Name",
                        "Email",
                        "Submitted",
                        "Admitted by",
                    ]
                )
            )
            for r in rows:
                self.stdout.write(
                    "\t".join(
                        [
                            str(r["application_id"]),
                            f"{r['first_name']} {r['last_name']}".strip(),
                            r["email"],
                            r["submitted_at"],
                            r["admitted_by_email"] or r["admitted_by_name"] or "—",
                        ]
                    )
                )
            return

        csv_path = options["csv"]
        if not csv_path:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            csv_path = f"reports/mistagged_direct_admissions_{ts}.csv"

        path = Path(csv_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        self.stdout.write(self.style.SUCCESS(f"CSV written to {path.resolve()}"))
