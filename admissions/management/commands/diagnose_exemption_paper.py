"""Show why a paper is missing from a student's eligible exemption list.

  python manage.py diagnose_exemption_paper --reg-no 26/2/328/W/2127 --code ENG1101
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from admissions.exemption_services import (
    MAX_EXEMPTION_TERMS,
    MAX_EXEMPTION_YEARS,
    _resolve_enrollment_curriculum_version,
    exemption_terms_already_committed,
    list_eligible_exemption_courses,
    list_programme_curriculum_for_review,
    term_open_for_new_exemption,
)
from admissions.models import AdmittedStudent, AdmissionChangeRequest
from Programs.models import ProgramCurriculumLine, StudentCurriculumOverride


class Command(BaseCommand):
    help = "Explain why a course code is not eligible for exemption."

    def add_arguments(self, parser):
        parser.add_argument("--reg-no", required=True)
        parser.add_argument("--code", required=True, help="e.g. ENG1101")

    def handle(self, *args, **options):
        reg = (options["reg_no"] or "").strip()
        code = (options["code"] or "").strip().upper().replace(" ", "")
        student = (
            AdmittedStudent.objects.filter(Q(reg_no__iexact=reg) | Q(student_id__iexact=reg))
            .select_related("admitted_program", "programme_enrollment", "application")
            .first()
        )
        if student is None:
            raise CommandError(f"Student not found: {reg}")

        enrollment, version = _resolve_enrollment_curriculum_version(student)
        name = getattr(student, "full_name", "") or ""
        self.stdout.write(f"{student.reg_no} {name} pk={student.pk}")
        self.stdout.write(f"  programme={getattr(student.admitted_program, 'name', None)}")
        self.stdout.write(f"  enrollment={getattr(enrollment, 'pk', None)} version={getattr(version, 'pk', None)}")

        draft = student.exemption_form_draft or {}
        papers = draft.get("papers") or []
        draft_hits = [
            p
            for p in papers
            if str(p.get("course_code") or "").upper().replace(" ", "") == code
            or str(p.get("curriculum_line_id") or "")
        ]
        self.stdout.write(f"  draft papers={len(papers)}")
        for p in papers:
            self.stdout.write(
                f"    draft code={p.get('course_code')} line_id={p.get('curriculum_line_id')} "
                f"Y{p.get('year_of_study')}T{p.get('term_number')}"
            )

        used = exemption_terms_already_committed(student)
        self.stdout.write(
            f"  committed terms={sorted(used)} (cap {MAX_EXEMPTION_YEARS} years / {MAX_EXEMPTION_TERMS} terms)"
        )

        eligible = list_eligible_exemption_courses(student)
        elig_hits = [
            c for c in eligible if str(c.get("course_code") or "").upper().replace(" ", "") == code
        ]
        self.stdout.write(f"  eligible list={len(eligible)}; {code} in eligible={bool(elig_hits)}")
        for c in elig_hits:
            self.stdout.write(f"    eligible id={c['id']} {c['course_code']} Y{c['year_of_study']}T{c['term_number']}")

        full = list_programme_curriculum_for_review(student)
        full_hits = [
            c for c in full if str(c.get("course_code") or "").upper().replace(" ", "") == code
        ]
        self.stdout.write(f"  full curriculum hits for {code}: {len(full_hits)}")
        for c in full_hits:
            open_term = term_open_for_new_exemption(used, c.get("year_of_study"), c.get("term_number"))
            self.stdout.write(
                f"    id={c['id']} {c['course_code']} Y{c['year_of_study']}T{c['term_number']} "
                f"already_exempted={c.get('already_exempted')} term_open={open_term}"
            )

        if enrollment is not None and full_hits:
            ovs = StudentCurriculumOverride.objects.filter(
                enrollment=enrollment,
                curriculum_line_id__in=[c["id"] for c in full_hits],
            )
            for o in ovs:
                self.stdout.write(f"  override line={o.curriculum_line_id} type={o.override_type}")

        pending = AdmissionChangeRequest.objects.filter(
            admitted_student=student, change_type="exemption", status="pending"
        )
        for req in pending:
            self.stdout.write(f"  pending CR #{req.id}")
            for line in req.exemption_lines.all():
                self.stdout.write(
                    f"    pending paper {line.course_code} line={line.curriculum_line_id}"
                )

        catalog_lines = ProgramCurriculumLine.objects.filter(
            is_active=True,
            catalog_course__code__iexact=options["code"].strip(),
        ).select_related("catalog_course", "curriculum_version", "program")[:20]
        self.stdout.write(f"  catalog active lines named {options['code']}: {catalog_lines.count()}")
        for line in catalog_lines:
            self.stdout.write(
                f"    line={line.id} prog={getattr(line.program, 'name', None)} "
                f"ver={line.curriculum_version_id} Y{line.year_of_study}T{line.term_number}"
            )

        if not full_hits:
            self.stdout.write(
                self.style.WARNING(
                    f"{code} is not on this student's current curriculum version. "
                    "The draft may have a stale curriculum_line_id, or the code is from another programme."
                )
            )
        elif full_hits and all(c.get("already_exempted") for c in full_hits):
            self.stdout.write(self.style.WARNING(f"{code} is already marked exempted/transferred."))
        elif full_hits and not elig_hits:
            self.stdout.write(
                self.style.WARNING(
                    f"{code} is on the curriculum but blocked (term/year cap, pending request, or override)."
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS(f"{code} looks eligible. Check the draft line id vs eligible id."))
