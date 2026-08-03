"""Import halls/rooms/beds from Halls of Residence Excel/CSV (idempotent on room code)."""
from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from hostel.import_rooms import import_hostel_file, import_room_rows, load_rows_from_csv, load_rows_from_xlsx


class Command(BaseCommand):
    help = "Import hostel rooms/beds from .xlsx or .csv (idempotent on room code)."

    def add_arguments(self, parser):
        parser.add_argument(
            "path",
            nargs="?",
            default="",
            help="Path to Halls of Residence .xlsx or .csv",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and report without writing.",
        )

    def handle(self, *args, **options):
        path = options["path"]
        if not path:
            candidates = [
                Path(__file__).resolve().parents[3] / "Halls of Residence details-2026.xlsx",
                Path(__file__).resolve().parents[2].parent
                / "Halls of Residence details-2026.xlsx",
                Path.cwd() / "Halls of Residence details-2026.xlsx",
                Path.cwd().parent / "Halls of Residence details-2026.xlsx",
            ]
            for c in candidates:
                if c.is_file():
                    path = str(c)
                    break
        if not path or not Path(path).is_file():
            raise CommandError(
                "File not found. Pass path to .xlsx or .csv "
                "(or upload via Hostel → Inventory in the ERP)."
            )

        p = Path(path)
        try:
            if p.suffix.lower() == ".csv":
                rows = load_rows_from_csv(path)
                stats = import_room_rows(rows, dry_run=options["dry_run"])
            else:
                stats = import_hostel_file(
                    path, filename=p.name, dry_run=options["dry_run"]
                )
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(f"Imported from {path}"))
        for k, v in stats.items():
            self.stdout.write(f"  {k}: {v}")
