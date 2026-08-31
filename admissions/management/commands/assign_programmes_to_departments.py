"""Suggest / apply programme → academic department links.

HoD department scoping requires ``Program.department``. Live often has departments
and heads configured but programmes still unassigned.

Examples::

    python manage.py assign_programmes_to_departments --dry-run
    python manage.py assign_programmes_to_departments --dry-run --faculty FSC
    python manage.py assign_programmes_to_departments --apply --faculty FSC
"""
from __future__ import annotations

import re

from django.core.management.base import BaseCommand
from django.db import transaction

from admissions.models import AcademicDepartment, Faculty
from Programs.models import Program


def _norm(value: str) -> str:
    text = (value or "").lower().replace("&", "and")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


# Keyword hints → department code (within the programme's faculty only).
# First matching rule wins. Keep faculty-agnostic keywords specific enough
# to avoid cross-faculty false matches.
KEYWORD_TO_DEPT_CODE: list[tuple[str, str]] = [
    # Computing / IT
    ("software engineering", "COMP"),
    ("business computing", "COMP"),
    ("information technology", "COMP"),
    ("computer science", "COMP"),
    ("computing", "COMP"),
    ("information systems", "COMP"),
    ("network", "COMP"),
    ("cyber", "COMP"),
    # Science / sports
    ("sports science", "SPORT"),
    ("physical education", "SPORT"),
    ("biology", "SCI"),
    ("chemistry", "SCI"),
    ("physics", "SCI"),
    ("mathematics", "SCI"),
    ("science", "SCI"),
    # Business
    ("accounting", "ACCFIN"),
    ("finance", "ACCFIN"),
    ("commerce", "ACCFIN"),
    ("business administration", "MGECON"),
    ("procurement", "MGECON"),
    ("human resource", "MGECON"),
    ("economics", "MGECON"),
    ("management", "MGECON"),
    ("entrepreneur", "MGECON"),
    # Education & humanities
    ("with education", "EDUC"),
    ("of education", "EDUC"),
    ("bachelor of education", "EDUC"),
    ("diploma in education", "EDUC"),
    ("higher education certificate", "HEC"),
    ("hec", "HEC"),
    ("journalism", "COMLANG"),
    ("mass communication", "COMLANG"),
    ("communication", "COMLANG"),
    ("languages", "COMLANG"),
    ("english", "COMLANG"),
    ("religious", "REL"),
    ("biblical", "REL"),
    ("theology", "REL"),
    ("christian", "REL"),
    ("divinity", "REL"),
    ("development studies", "SOCSCI"),
    ("public administration", "SOCSCI"),
    ("social work", "SOCSCI"),
    ("social sciences", "SOCSCI"),
    ("community development", "SOCSCI"),
    ("guidance and counselling", "SOCSCI"),
    ("counsel", "SOCSCI"),
    # Health
    ("clinical medicine", "CMCH"),
    ("community health", "CMCH"),
    ("nursing", "CMCH"),
    ("midwifery", "CMCH"),
    ("public health", "CMCH"),
    # Engineering
    ("civil engineering", "CIV"),
    ("geomatic", "GEO"),
    ("survey", "GEO"),
    ("electrical", "ELEC"),
    ("mechanical", "MECH"),
    ("biomedical engineering", "CIV"),  # often under engineering faculty; adjust if wrong
    # Environment / agri
    ("agriculture", "AGRI"),
    ("agribusiness", "AGRI"),
    ("environment", "ENV"),
    ("forestry", "ENV"),
]


# Short-form / code prefixes → department code
CODE_PREFIX_TO_DEPT: list[tuple[str, str]] = [
    ("bse", "COMP"),
    ("bbc", "COMP"),
    ("bit", "COMP"),
    ("bcs", "COMP"),
    ("bis", "COMP"),
    ("bba", "MGECON"),
    ("com", "ACCFIN"),
    ("baf", "ACCFIN"),
    ("bac", "ACCFIN"),
    ("baed", "EDUC"),
    ("bsced", "EDUC"),
    ("bed", "EDUC"),
    ("hec", "HEC"),
    ("bjm", "COMLANG"),
    ("bjmc", "COMLANG"),
    ("bads", "SOCSCI"),
    ("bpam", "SOCSCI"),
    ("bcd", "SOCSCI"),
    ("bsw", "SOCSCI"),
    ("bsl", "REL"),
    ("bie", "CIV"),
]


class Command(BaseCommand):
    help = (
        "Suggest or apply Program.department links from keyword/code heuristics "
        "(required before HoD department scoping works)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=True,
            help="Show suggestions only (default).",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write suggested department links.",
        )
        parser.add_argument(
            "--faculty",
            dest="faculty",
            help="Limit to faculty code (e.g. FSC, FBAM, FEH).",
        )
        parser.add_argument(
            "--only-missing",
            action="store_true",
            default=True,
            help="Only programmes with department=NULL (default).",
        )
        parser.add_argument(
            "--reassign",
            action="store_true",
            help="Also reconsider programmes that already have a department.",
        )

    def handle(self, *args, **options):
        apply = bool(options.get("apply"))
        dry = not apply
        faculty_code = (options.get("faculty") or "").strip()
        only_missing = not bool(options.get("reassign"))

        depts = list(
            AcademicDepartment.objects.filter(is_active=True).select_related("faculty")
        )
        dept_by_fac_code: dict[int, dict[str, AcademicDepartment]] = {}
        for d in depts:
            dept_by_fac_code.setdefault(d.faculty_id, {})[_norm(d.code)] = d
            # Also index by bare code upper for CODE_PREFIX map values
            dept_by_fac_code[d.faculty_id][d.code.upper()] = d

        qs = Program.objects.filter(is_active=True).select_related("faculty", "department")
        if only_missing:
            qs = qs.filter(department__isnull=True)
        if faculty_code:
            fac = Faculty.objects.filter(code__iexact=faculty_code).first()
            if fac is None:
                self.stderr.write(self.style.ERROR(f"No faculty with code={faculty_code!r}"))
                return
            qs = qs.filter(faculty=fac)

        programmes = list(qs.order_by("faculty__code", "name"))
        suggested = 0
        unmatched = 0
        applied = 0
        unmatched_rows: list[str] = []

        with transaction.atomic():
            for p in programmes:
                if not p.faculty_id:
                    unmatched += 1
                    unmatched_rows.append(f"  NO_FACULTY  {p.short_form or p.id}: {p.name}")
                    continue
                fac_map = dept_by_fac_code.get(p.faculty_id) or {}
                if not fac_map:
                    unmatched += 1
                    unmatched_rows.append(
                        f"  NO_DEPTS_IN_FACULTY  {p.faculty.code}  {p.short_form or p.id}: {p.name}"
                    )
                    continue

                dept = self._suggest_department(p, fac_map)
                if dept is None:
                    unmatched += 1
                    unmatched_rows.append(
                        f"  UNMATCHED  {p.faculty.code}  {p.short_form or p.id}: {p.name}"
                    )
                    continue

                suggested += 1
                line = (
                    f"  {p.faculty.code}  {p.short_form or p.id}  →  "
                    f"{dept.code} ({dept.name})"
                )
                self.stdout.write(line)
                if apply:
                    p.department = dept
                    p.save(update_fields=["department", "updated_at"])
                    applied += 1

            if dry:
                transaction.set_rollback(True)

        self.stdout.write("")
        if unmatched_rows:
            self.stdout.write(self.style.WARNING("Could not auto-map:"))
            for row in unmatched_rows[:80]:
                self.stdout.write(row)
            if len(unmatched_rows) > 80:
                self.stdout.write(f"  ... and {len(unmatched_rows) - 80} more")

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. suggested={suggested} unmatched={unmatched} "
                f"applied={applied if apply else 0}"
                + (" (dry-run — no writes)" if dry else "")
            )
        )
        if dry and suggested:
            self.stdout.write(
                "Review the list, then re-run with --apply to save. "
                "Assign remaining UNMATCHED programmes in Academic Departments UI."
            )

    def _suggest_department(self, program: Program, fac_map: dict[str, AcademicDepartment]):
        blob = _norm(f"{program.short_form or ''} {program.code or ''} {program.name or ''}")
        code_blob = _norm(f"{program.short_form or ''} {program.code or ''}")

        for prefix, dept_code in CODE_PREFIX_TO_DEPT:
            if code_blob.startswith(prefix) or f" {prefix} " in f" {code_blob} ":
                dept = fac_map.get(dept_code.upper()) or fac_map.get(_norm(dept_code))
                if dept is not None:
                    return dept

        for keyword, dept_code in KEYWORD_TO_DEPT_CODE:
            if _norm(keyword) in blob:
                dept = fac_map.get(dept_code.upper()) or fac_map.get(_norm(dept_code))
                if dept is not None:
                    return dept

        # Single-department faculty → assign everything there
        unique = list({d.pk: d for d in fac_map.values()}.values())
        if len(unique) == 1:
            return unique[0]
        return None
