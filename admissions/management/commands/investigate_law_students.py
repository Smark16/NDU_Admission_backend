"""
Investigate Faculty of Law students by registration number.

Examples (on the server):
  python manage.py investigate_law_students
  python manage.py investigate_law_students --csv /tmp/law_students.csv
  python manage.py investigate_law_students --check-file /tmp/expected_reg_nos.txt
  python manage.py investigate_law_students --reg-no 2024/NDU/LLB/001 --reg-no 2024/NDU/LLB/002
"""
from __future__ import annotations

import csv
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db.models import Count, Q

from admissions.models import AdmittedStudent, Faculty


def _law_faculty_qs():
    return Faculty.objects.filter(
        Q(name__icontains="Law") | Q(code__icontains="LAW")
    ).order_by("name")


def _law_students_qs():
    law_ids = list(_law_faculty_qs().values_list("pk", flat=True))
    return (
        AdmittedStudent.objects.filter(
            is_admitted=True,
            admitted_program__faculty_id__in=law_ids,
        )
        .select_related(
            "application",
            "admitted_program",
            "admitted_program__faculty",
            "admitted_campus",
            "admitted_batch",
            "intended_program_batch",
        )
        .order_by("reg_no")
    )


def _norm_reg(value: str) -> str:
    return (value or "").strip().upper()


class Command(BaseCommand):
    help = "List / reconcile Faculty of Law students by reg_no."

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            dest="csv_path",
            default="",
            help="Write full Law student list to this CSV path.",
        )
        parser.add_argument(
            "--check-file",
            dest="check_file",
            default="",
            help="Text/CSV file of expected reg numbers (one per line, or first column).",
        )
        parser.add_argument(
            "--reg-no",
            action="append",
            dest="reg_nos",
            default=[],
            help="Expected reg number to check (repeatable).",
        )
        parser.add_argument(
            "--include-not-admitted",
            action="store_true",
            help="Include rows with is_admitted=False that still sit under Law faculty.",
        )

    def handle(self, *args, **options):
        faculties = list(_law_faculty_qs())
        self.stdout.write(self.style.NOTICE("=== Law faculty row(s) ==="))
        if not faculties:
            self.stdout.write(self.style.ERROR("No Faculty matching name/code ~ Law / LAW."))
            return
        for f in faculties:
            self.stdout.write(f"  id={f.pk}  code={f.code!r}  name={f.name!r}  active={f.is_active}")

        qs = _law_students_qs()
        if options["include_not_admitted"]:
            law_ids = [f.pk for f in faculties]
            qs = (
                AdmittedStudent.objects.filter(admitted_program__faculty_id__in=law_ids)
                .select_related(
                    "application",
                    "admitted_program",
                    "admitted_program__faculty",
                    "admitted_campus",
                    "admitted_batch",
                    "intended_program_batch",
                )
                .order_by("reg_no")
            )

        total = qs.count()
        self.stdout.write("")
        self.stdout.write(self.style.NOTICE(f"=== Law admitted students: {total} ==="))

        by_program = (
            qs.values("admitted_program__name", "admitted_program__code")
            .annotate(n=Count("id"))
            .order_by("-n", "admitted_program__name")
        )
        self.stdout.write("By programme:")
        for row in by_program:
            self.stdout.write(
                f"  {row['n']:4d}  {row['admitted_program__code'] or '—'}  "
                f"{row['admitted_program__name']}"
            )

        by_batch = (
            qs.values("admitted_batch__name", "admitted_batch__year")
            .annotate(n=Count("id"))
            .order_by("-n", "admitted_batch__name")
        )
        self.stdout.write("By intake batch:")
        for row in by_batch:
            self.stdout.write(
                f"  {row['n']:4d}  {row['admitted_batch__name']} ({row['admitted_batch__year']})"
            )

        registered = qs.filter(is_registered=True).count()
        self.stdout.write(
            f"Registered (is_registered=True): {registered} / {total}"
        )

        # Full list by reg_no
        self.stdout.write("")
        self.stdout.write(self.style.NOTICE("=== Registration numbers (sorted) ==="))
        rows = []
        for s in qs.iterator(chunk_size=500):
            name = ""
            try:
                name = (s.full_name or "").strip()
            except Exception:
                name = ""
            row = {
                "reg_no": s.reg_no,
                "name": name,
                "program": s.admitted_program.name if s.admitted_program_id else "",
                "program_code": getattr(s.admitted_program, "code", "") or "",
                "faculty": (
                    s.admitted_program.faculty.name
                    if s.admitted_program_id and s.admitted_program.faculty_id
                    else ""
                ),
                "campus": s.admitted_campus.name if s.admitted_campus_id else "",
                "batch": s.admitted_batch.name if s.admitted_batch_id else "",
                "study_mode": s.study_mode or "",
                "is_admitted": s.is_admitted,
                "is_registered": s.is_registered,
                "student_id": s.student_id or "",
            }
            rows.append(row)
            self.stdout.write(
                f"  {s.reg_no}\t{name}\t{row['program_code']}\t{row['batch']}\t"
                f"reg={'Y' if s.is_registered else 'N'}"
            )

        csv_path = (options.get("csv_path") or "").strip()
        if csv_path:
            path = Path(csv_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            fieldnames = list(rows[0].keys()) if rows else [
                "reg_no",
                "name",
                "program",
                "program_code",
                "faculty",
                "campus",
                "batch",
                "study_mode",
                "is_admitted",
                "is_registered",
                "student_id",
            ]
            with path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            self.stdout.write(self.style.SUCCESS(f"Wrote {len(rows)} rows → {path}"))

        expected = list(options.get("reg_nos") or [])
        check_file = (options.get("check_file") or "").strip()
        if check_file:
            expected.extend(self._load_reg_file(check_file))

        if expected:
            self._reconcile(expected, rows)

    def _load_reg_file(self, path: str) -> list[str]:
        text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
        out = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.lower().startswith("reg"):
                continue
            # CSV first column or plain line
            out.append(line.split(",")[0].strip().strip('"'))
        return out

    def _reconcile(self, expected: list[str], law_rows: list[dict]):
        self.stdout.write("")
        self.stdout.write(self.style.NOTICE("=== Reconcile expected reg numbers ==="))

        law_by_norm = {_norm_reg(r["reg_no"]): r for r in law_rows}
        expected_norm = []
        seen = set()
        for raw in expected:
            n = _norm_reg(raw)
            if not n or n in seen:
                continue
            seen.add(n)
            expected_norm.append((raw.strip(), n))

        in_law = []
        in_db_other_faculty = []
        missing = []

        for raw, n in expected_norm:
            if n in law_by_norm:
                in_law.append(law_by_norm[n])
                continue
            hit = (
                AdmittedStudent.objects.filter(reg_no__iexact=raw.strip())
                .select_related("admitted_program__faculty")
                .first()
            )
            if not hit:
                # try normalized exact on stored value
                hit = (
                    AdmittedStudent.objects.filter(reg_no__iexact=n)
                    .select_related("admitted_program__faculty")
                    .first()
                )
            if hit:
                fac = (
                    hit.admitted_program.faculty.name
                    if hit.admitted_program_id and hit.admitted_program.faculty_id
                    else "—"
                )
                in_db_other_faculty.append((hit.reg_no, fac, hit.admitted_program.name))
            else:
                missing.append(raw.strip())

        self.stdout.write(f"Expected unique: {len(expected_norm)}")
        self.stdout.write(self.style.SUCCESS(f"In Law faculty: {len(in_law)}"))
        self.stdout.write(
            self.style.WARNING(f"In DB but other faculty: {len(in_db_other_faculty)}")
        )
        self.stdout.write(self.style.ERROR(f"Not found in DB: {len(missing)}"))

        # Law students not on the expected list
        expected_set = {n for _, n in expected_norm}
        extras = [r for r in law_rows if _norm_reg(r["reg_no"]) not in expected_set]
        self.stdout.write(
            self.style.WARNING(f"Law in DB but NOT on your list: {len(extras)}")
        )

        if in_db_other_faculty:
            self.stdout.write("Other faculty:")
            for reg, fac, prog in in_db_other_faculty[:50]:
                self.stdout.write(f"  {reg}\t{fac}\t{prog}")
            if len(in_db_other_faculty) > 50:
                self.stdout.write(f"  ... +{len(in_db_other_faculty) - 50} more")

        if missing:
            self.stdout.write("Missing from DB:")
            for reg in missing[:100]:
                self.stdout.write(f"  {reg}")
            if len(missing) > 100:
                self.stdout.write(f"  ... +{len(missing) - 100} more")

        if extras:
            self.stdout.write("Extra Law students (on system, not on your list):")
            for r in extras[:100]:
                self.stdout.write(f"  {r['reg_no']}\t{r['name']}\t{r['program']}")
            if len(extras) > 100:
                self.stdout.write(f"  ... +{len(extras) - 100} more")
