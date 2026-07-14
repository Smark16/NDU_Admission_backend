#!/usr/bin/env python
"""
Generate CSV to bulk-create programme batches for programmes on an active
admission intake that have no ProgramBatch yet.

Usage (on server):
  cd ~/NDU_Admission_backend
  source venv/bin/activate
  python scripts/generate_intake_missing_batches_csv.py
  python scripts/generate_intake_missing_batches_csv.py --intake-id 1 --output /tmp/missing_batches.csv
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import date
from pathlib import Path

import django

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ndu_portal.settings")
django.setup()

from admissions.models import Batch  # noqa: E402
from Programs.models import ProgramBatch  # noqa: E402

HEADERS = [
    "batch_id",
    "program_code",
    "program_name",
    "batch_name",
    "academic_year",
    "start_date",
    "end_date",
    "offer_start_date",
    "offer_end_date",
    "is_active",
]


def suggest_batch_name(program) -> str:
    code = (program.code or "").upper()
    name = (program.name or "").upper()
    if "INSERV" in code or "INSERVICE" in name:
        return "Inservice AUG 2026"
    if "-MAIN" in code or " MAIN" in name:
        return "Main AUG 2026"
    if "WKEND" in code or "WEEKEND" in name:
        return "AUG 2026"
    if "DAY" in code or "-DAY" in code:
        return "Day AUG 2026"
    if "PHD" in name or "DOCTOR OF PHILOSOPHY" in name:
        return "Year 1"
    if "CERTIFICATE" in name:
        return "Main AUG 2026"
    if "DIPLOMA" in name or "MASTER" in name or "POST" in name:
        return "AUG 2026"
    return "AUG 2026"


def default_dates(intake: Batch) -> dict[str, str]:
    offer_start = intake.application_start_date or intake.admission_start_date or date(2026, 3, 30)
    offer_end = intake.admission_end_date or intake.application_end_date or date(2026, 12, 31)
    start = date(offer_start.year, 8, 1) if offer_start.month <= 8 else offer_start
    end = date(start.year + 1, 7, 31)
    acad_year = (intake.academic_year or "").strip() or f"{start.year - 1}/{start.year}"
    return {
        "academic_year": acad_year,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "offer_start_date": offer_start.isoformat(),
        "offer_end_date": offer_end.isoformat(),
    }


def missing_programs_for_intake(intake: Batch):
    for program in intake.programs.filter(is_active=True).order_by("name"):
        if ProgramBatch.objects.filter(program_id=program.id).exists():
            continue
        yield program


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake-id", type=int, default=None, help="Admissions.Batch id (default: active intakes)")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "scripts" / "aug2026_missing_program_batches_generated.csv",
    )
    args = parser.parse_args()

    if args.intake_id:
        intakes = Batch.objects.filter(pk=args.intake_id)
    else:
        intakes = Batch.objects.filter(is_active=True).order_by("-created_at")

    if not intakes.exists():
        print("No intake found.", file=sys.stderr)
        sys.exit(1)

    rows: list[list[str]] = []
    for intake in intakes:
        dates = default_dates(intake)
        for program in missing_programs_for_intake(intake):
            rows.append(
                [
                    "",
                    program.code or "",
                    program.name or "",
                    suggest_batch_name(program),
                    dates["academic_year"],
                    dates["start_date"],
                    dates["end_date"],
                    dates["offer_start_date"],
                    dates["offer_end_date"],
                    "TRUE",
                ]
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADERS)
        writer.writerows(rows)

    print(f"Wrote {len(rows)} row(s) to {args.output}")
    if not rows:
        print("All programmes on the intake already have batches.")


if __name__ == "__main__":
    main()
