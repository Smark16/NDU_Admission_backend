"""Install the Ndejje CR80 student ID PDF and map fields to portal data."""

from __future__ import annotations

import shutil
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from accounts.models import SystemSettings
from admissions.id_card_default_layout import (
    NDEJJE_CR80_STUDENT_FIELD_POSITIONS,
    NDEJJE_STUDENT_ID_TEMPLATE_KEY,
    NDEJJE_STUDENT_ID_TEMPLATE_NAME,
)
from admissions.models import IdCardPdfTemplate

WORKSPACE_PDF_NAMES = ("Students ID new.pdf", "students_id_new.pdf")


class Command(BaseCommand):
    help = (
        "Copy the Ndejje student ID PDF into media, map photo/name/number/course/"
        "expiry/QR to live student fields, and set it as the active print template."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--pdf",
            default="",
            help="Path to the ID artwork PDF (default: Students ID new.pdf in the workspace).",
        )

    def handle(self, *args, **options):
        pdf_path = self._resolve_pdf(str(options.get("pdf") or "").strip())
        dest_dir = Path(settings.MEDIA_ROOT) / "id_card_templates"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / "students_id_new.pdf"
        shutil.copyfile(pdf_path, dest)

        row, created = IdCardPdfTemplate.objects.get_or_create(
            key=NDEJJE_STUDENT_ID_TEMPLATE_KEY,
            defaults={
                "name": NDEJJE_STUDENT_ID_TEMPLATE_NAME,
                "audience": IdCardPdfTemplate.AUDIENCE_STUDENT,
                "field_positions": dict(NDEJJE_CR80_STUDENT_FIELD_POSITIONS),
                "institution": "Ndejje University",
                "front_title": "NDEJJE UNIVERSITY",
            },
        )
        with dest.open("rb") as fh:
            row.template_pdf.save("students_id_new.pdf", File(fh), save=False)
        row.name = NDEJJE_STUDENT_ID_TEMPLATE_NAME
        row.audience = IdCardPdfTemplate.AUDIENCE_STUDENT
        row.field_positions = dict(NDEJJE_CR80_STUDENT_FIELD_POSITIONS)
        row.institution = row.institution or "Ndejje University"
        row.front_title = row.front_title or "NDEJJE UNIVERSITY"
        row.save()

        updated = SystemSettings.objects.filter(pk=1).update(
            active_id_card_template=NDEJJE_STUDENT_ID_TEMPLATE_KEY
        )
        if not updated:
            self.stdout.write(
                self.style.WARNING(
                    "System settings row was not updated; set the active student ID template in the UI."
                )
            )

        action = "Created" if created else "Updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} template {row.key} (id={row.id}) from {pdf_path}. "
                "Print now overlays live student photo, name, student number, course, expiry, and QR."
            )
        )

    def _resolve_pdf(self, explicit: str) -> Path:
        candidates = []
        if explicit:
            candidates.append(Path(explicit))
        backend_root = Path(settings.BASE_DIR)
        workspace = backend_root.parent
        assets = Path(__file__).resolve().parents[2] / "id_card_assets" / "students_id_new.pdf"
        candidates.append(assets)
        for name in WORKSPACE_PDF_NAMES:
            candidates.append(workspace / name)
        for path in candidates:
            if path.is_file():
                return path
        raise CommandError(
            "Could not find the student ID PDF. Put “Students ID new.pdf” in the "
            "NDU portal v2 folder or pass --pdf path."
        )
