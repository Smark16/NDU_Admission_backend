"""Load official Ndejje faculties and academic departments (idempotent)."""

from __future__ import annotations

import re

from django.core.management.base import BaseCommand
from django.db import transaction

from admissions.data.ndejje_academic_units import NDEJJE_ACADEMIC_UNITS
from admissions.models import AcademicDepartment, Faculty


def _norm(value: str) -> str:
    text = (value or "").lower().replace("&", "and")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


class Command(BaseCommand):
    help = "Create/update official Ndejje faculties and academic departments (local/ERP)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without writing.",
        )

    def handle(self, *args, **options):
        dry = bool(options["dry_run"])
        created_f = updated_f = created_d = updated_d = 0
        existing = list(Faculty.objects.all())

        def find_faculty(name: str, code: str) -> Faculty | None:
            want = _norm(name)
            for fac in existing:
                if _norm(fac.name) == want or _norm(fac.code) == _norm(code):
                    return fac
            return None

        with transaction.atomic():
            for item in NDEJJE_ACADEMIC_UNITS:
                fac = find_faculty(item["name"], item["code"])
                if fac is None:
                    created_f += 1
                    self.stdout.write(f"  Faculty CREATE  {item['code']}  {item['name']}")
                    if not dry:
                        fac = Faculty.objects.create(
                            name=item["name"],
                            code=item["code"],
                            is_active=True,
                        )
                        existing.append(fac)
                else:
                    fields = []
                    if fac.name != item["name"]:
                        fac.name = item["name"]
                        fields.append("name")
                    if fac.code != item["code"] and not Faculty.objects.filter(code=item["code"]).exclude(pk=fac.pk).exists():
                        fac.code = item["code"]
                        fields.append("code")
                    if not fac.is_active:
                        fac.is_active = True
                        fields.append("is_active")
                    if fields:
                        updated_f += 1
                        self.stdout.write(f"  Faculty UPDATE  {fac.code}  ({', '.join(fields)})")
                        if not dry:
                            fac.save(update_fields=fields + ["updated_at"])
                    else:
                        self.stdout.write(f"  Faculty OK      {fac.code}  {fac.name}")

                if fac is None:
                    continue

                for order, dept in enumerate(item["departments"], start=1):
                    qs = AcademicDepartment.objects.filter(faculty=fac)
                    row = qs.filter(name=dept["name"]).first() or qs.filter(code=dept["code"]).first()
                    if row is None:
                        created_d += 1
                        self.stdout.write(f"    Dept CREATE   {dept['code']}  {dept['name']}")
                        if not dry:
                            AcademicDepartment.objects.create(
                                faculty=fac,
                                name=dept["name"],
                                code=dept["code"],
                                sort_order=order,
                                is_active=True,
                            )
                    else:
                        fields = []
                        if row.name != dept["name"]:
                            row.name = dept["name"]
                            fields.append("name")
                        if row.code != dept["code"]:
                            clash = qs.filter(code=dept["code"]).exclude(pk=row.pk).exists()
                            if not clash:
                                row.code = dept["code"]
                                fields.append("code")
                        if row.sort_order != order:
                            row.sort_order = order
                            fields.append("sort_order")
                        if not row.is_active:
                            row.is_active = True
                            fields.append("is_active")
                        if fields:
                            updated_d += 1
                            self.stdout.write(f"    Dept UPDATE   {row.code}  ({', '.join(fields)})")
                            if not dry:
                                row.save(update_fields=fields + ["updated_at"])
                        else:
                            self.stdout.write(f"    Dept OK       {row.code}  {row.name}")

            if dry:
                transaction.set_rollback(True)

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Faculties +{created_f}/~{updated_f}, departments +{created_d}/~{updated_d}"
                + (" (dry-run)" if dry else "")
            )
        )
