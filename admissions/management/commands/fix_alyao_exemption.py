"""
One-off correction for Ms. Alyao Jacqueline (26/2/508/W/2543) — the first real
application of the new Exemption Fee and Promotion System.

Background: her course exemption was approved manually by the HOD outside the
normal AdmissionChangeRequest workflow. Accounts then typed two raw ad-hoc
charges totalling UGX 3,240,000 — about 2.4x the correct amount. Her physical
"Application Form for Exemption" lists 9 UMI papers at UGX 150,000/paper
(standard rate; not an alumna), total UGX 1,350,000. The HOD's decision was
for her to begin at Year 2 Term 1.

Important: form codes (HRM 4102 …) are from Uganda Management Institute, not
NDU catalog codes. Matching by form code alone will usually fail. Prefer:

    python manage.py migrate admissions
    python manage.py fix_alyao_exemption --dry-run --exempt-year 1
    python manage.py fix_alyao_exemption --exempt-year 1

Or map explicitly after reading the curriculum dump from --dry-run:

    python manage.py fix_alyao_exemption --map "HRM 4102=BHRM1101" --map "..."

Usage:
    python manage.py fix_alyao_exemption --dry-run --exempt-year 1
    python manage.py fix_alyao_exemption --exempt-year 1
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.utils import ProgrammingError
from django.utils import timezone

from admissions.exemption_services import apply_exemption_overrides, ensure_exemption_fee_heads
from admissions.models import AdmissionChangeRequest, AdmittedStudent, ExemptionRequestLine
from payments.adhoc_views import _create_split_adhoc_charges, _student_program_batch_id
from payments.models import StudentTuitionPayment

User = get_user_model()

REG_NO_DEFAULT = "26/2/508/W/2543"
ATTAINED_AT = "Uganda Management Institute"
ACADEMIC_YEARS = "2019/2020"
IS_ALUMNUS = False

# UMI codes from the physical form (labels / audit trail — not NDU codes).
FORM_PAPERS: list[tuple[str, str]] = [
    ("HRM 4102", ""),
    ("HRM 4103", ""),
    ("HRM 4104", ""),
    ("HRM 4105", ""),
    ("HRM 4106", ""),
    ("HRM 4201", ""),
    ("HRM 4202", ""),
    ("HRM 4203", ""),
    ("HRM 4204", ""),
]

TARGET_YEAR_OF_STUDY = 2
TARGET_TERM_NUMBER = 1
BILLABLE_PAPER_COUNT = len(FORM_PAPERS)


def _normalize_code(code: str) -> str:
    return code.strip().upper().replace(" ", "").replace("-", "")


def exemption_course_fee_rate_for(is_alumnus: bool) -> Decimal:
    from admissions.exemption_services import (
        EXEMPTION_COURSE_FEE_ALUMNI_UGX,
        EXEMPTION_COURSE_FEE_STANDARD_UGX,
    )

    return EXEMPTION_COURSE_FEE_ALUMNI_UGX if is_alumnus else EXEMPTION_COURSE_FEE_STANDARD_UGX


class Command(BaseCommand):
    help = "One-off correction of Ms. Alyao Jacqueline's course exemption billing + academic position."

    def add_arguments(self, parser):
        parser.add_argument("--reg-no", default=REG_NO_DEFAULT)
        parser.add_argument(
            "--old-charge-ids",
            default="54,55",
            help="Comma-separated StudentTuitionPayment ids to waive (default: 54,55).",
        )
        parser.add_argument(
            "--exempt-year",
            type=int,
            action="append",
            dest="exempt_years",
            default=[],
            help=(
                "Exempt ALL curriculum lines for this year_of_study (repeatable). "
                "Use when form codes are from another institution (e.g. UMI). "
                "Typical for Alyao: --exempt-year 1"
            ),
        )
        parser.add_argument(
            "--map",
            action="append",
            dest="code_maps",
            default=[],
            help='Map form code to NDU catalog code, e.g. --map "HRM 4102=BHRM1101" (repeatable).',
        )
        parser.add_argument(
            "--line-ids",
            default="",
            help="Comma-separated ProgramCurriculumLine ids to exempt (overrides auto match).",
        )
        parser.add_argument("--dry-run", action="store_true", help="Report only; do not save anything.")

    def handle(self, *args, **options):
        w = self.stdout.write
        dry_run = options["dry_run"]
        try:
            old_charge_ids = [int(x) for x in options["old_charge_ids"].split(",") if x.strip()]
        except ValueError as exc:
            raise CommandError("--old-charge-ids must be a comma-separated list of integers.") from exc

        student = (
            AdmittedStudent.objects.select_related(
                "admitted_program",
                "admitted_campus",
                "programme_enrollment",
                "programme_enrollment__program_batch",
                "programme_enrollment__program",
            )
            .filter(reg_no__iexact=options["reg_no"].strip())
            .first()
        )
        if student is None:
            raise CommandError(f"No student found with reg_no={options['reg_no']!r}")

        w("=" * 78)
        w(f"Student: {student.full_name}  (reg_no={student.reg_no}, pk={student.pk})")
        w("=" * 78)

        try:
            enrollment = student.programme_enrollment
        except Exception:
            enrollment = None
        if enrollment is None:
            raise CommandError("Student has no programme enrollment; cannot proceed.")

        w(
            f"Current curriculum position: Year {enrollment.current_year_of_study} "
            f"Term {enrollment.current_term_number}"
        )
        w(f"Target curriculum position:  Year {TARGET_YEAR_OF_STUDY} Term {TARGET_TERM_NUMBER}")

        from Programs.curriculum_inheritance import (
            curriculum_owner_program,
            resolve_effective_curriculum_version,
        )
        from Programs.models import ProgramCurriculumLine

        program = enrollment.program
        owner = curriculum_owner_program(program)
        batch = enrollment.program_batch if enrollment.program_batch_id else None
        pinned = enrollment.curriculum_version
        version = resolve_effective_curriculum_version(program, batch=batch)

        if version is None:
            raise CommandError("No curriculum version resolved for this student.")

        w(
            f"Programme: id={program.pk} {getattr(program, 'short_form', '') or program.name!r} "
            f"mode={getattr(program, 'curriculum_mode', '?')}"
        )
        if owner and owner.pk != program.pk:
            w(
                f"Curriculum owner (master): id={owner.pk} "
                f"{getattr(owner, 'short_form', '') or owner.name!r}"
            )
        if pinned and pinned.pk != version.pk:
            w(
                f"NOTE: enrollment pinned empty/local version id={pinned.pk} "
                f"{pinned.name!r}; using effective master version instead."
            )
        w(f"Curriculum version: id={version.pk} name={version.name!r}")

        owner_program_id = owner.pk if owner else enrollment.program_id
        curriculum_lines = list(
            ProgramCurriculumLine.objects.filter(
                curriculum_version=version,
                program_id=owner_program_id,
            )
            .select_related("catalog_course")
            .order_by("year_of_study", "term_number", "id")
        )
        by_code = {}
        for line in curriculum_lines:
            if line.catalog_course:
                by_code[_normalize_code(line.catalog_course.code)] = line

        w("\nNDU curriculum units on this version (use these codes/ids for --map / --line-ids):")
        if not curriculum_lines:
            w("  (none found)")
        for line in curriculum_lines:
            code = line.catalog_course.code if line.catalog_course else "?"
            title = line.catalog_course.title if line.catalog_course else ""
            w(f"  id={line.id:<6} Y{line.year_of_study}T{line.term_number}  {code:<16} {title}")

        # Build the set of curriculum lines to exempt.
        resolved: list[tuple[str, str, object]] = []  # (label_code, score, curriculum_line)

        line_ids_raw = (options.get("line_ids") or "").strip()
        if line_ids_raw:
            try:
                ids = [int(x) for x in line_ids_raw.split(",") if x.strip()]
            except ValueError as exc:
                raise CommandError("--line-ids must be comma-separated integers.") from exc
            by_id = {line.id: line for line in curriculum_lines}
            for i, lid in enumerate(ids):
                line = by_id.get(lid)
                if line is None:
                    raise CommandError(f"Curriculum line id={lid} is not on this student's curriculum.")
                form_code = FORM_PAPERS[i][0] if i < len(FORM_PAPERS) else (
                    line.catalog_course.code if line.catalog_course else f"LINE-{lid}"
                )
                resolved.append((form_code, "", line))
        elif options["exempt_years"]:
            years = set(options["exempt_years"])
            year_lines = [ln for ln in curriculum_lines if ln.year_of_study in years]
            if not year_lines:
                raise CommandError(
                    f"No curriculum lines found for year_of_study in {sorted(years)}."
                )
            w(
                f"\n--exempt-year {sorted(years)} selected {len(year_lines)} NDU unit(s) "
                f"(form listed {BILLABLE_PAPER_COUNT} UMI papers for billing)."
            )
            for i, line in enumerate(year_lines):
                ndu_code = line.catalog_course.code if line.catalog_course else f"LINE-{line.id}"
                form_code = FORM_PAPERS[i][0] if i < len(FORM_PAPERS) else ndu_code
                label = f"{ndu_code} (form: {form_code})" if i < len(FORM_PAPERS) else ndu_code
                resolved.append((label, "", line))
        else:
            code_maps = {}
            for raw in options.get("code_maps") or []:
                if "=" not in raw:
                    raise CommandError(f'Invalid --map {raw!r}; expected FORM=NDUCODE')
                left, right = raw.split("=", 1)
                code_maps[_normalize_code(left)] = right.strip()

            w("\nCourse code -> curriculum line match report:")
            for form_code, score in FORM_PAPERS:
                lookup = code_maps.get(_normalize_code(form_code), form_code)
                line = by_code.get(_normalize_code(lookup))
                if line:
                    resolved.append((form_code, score, line))
                    ndu = line.catalog_course.code if line.catalog_course else "?"
                    w(
                        f"  {form_code:<12} -> {ndu}  "
                        f"Y{line.year_of_study}T{line.term_number} (line id={line.id})"
                    )
                else:
                    w(
                        f"  {form_code:<12} NOT MATCHED "
                        f"(looked up as {lookup!r}). Form codes are usually UMI, not NDU."
                    )

        if not resolved:
            raise CommandError(
                "No curriculum lines resolved. Re-run with --exempt-year 1 "
                "(recommended for Alyao / full Year-1 exemption) or --map / --line-ids "
                "after reading the curriculum dump above. Also run: "
                "python manage.py migrate admissions"
            )

        w("\nResolved exemption units:")
        for label, _score, line in resolved:
            ndu = line.catalog_course.code if line.catalog_course else "?"
            w(f"  {label:<28} -> {ndu} Y{line.year_of_study}T{line.term_number} (id={line.id})")

        # Bill from the physical form (9 papers), not from how many NDU lines we link.
        rate = exemption_course_fee_rate_for(IS_ALUMNUS)
        total = rate * BILLABLE_PAPER_COUNT
        w(
            f"\nPricing: {'alumni' if IS_ALUMNUS else 'standard'} rate UGX {rate:,}/paper "
            f"x {BILLABLE_PAPER_COUNT} form papers = UGX {total:,} "
            f"(linked to {len(resolved)} NDU curriculum unit(s))"
        )

        old_charges = list(
            StudentTuitionPayment.objects.filter(student=student, id__in=old_charge_ids)
        )
        found_ids = {c.id for c in old_charges}
        missing_ids = [i for i in old_charge_ids if i not in found_ids]
        if missing_ids:
            w(f"\nWARNING: old charge id(s) not found on this student: {missing_ids}")
        old_total = sum(
            (Decimal(str(c.amount)) for c in old_charges if not c.is_waived), Decimal("0")
        )
        w(f"\nOld charges to waive ({len(old_charges)} found):")
        for c in old_charges:
            w(
                f"  #{c.id} amount={c.amount} status={c.status} is_waived={c.is_waived} "
                f"label={c.label!r}"
            )
        w(f"  total unwaived old amount: UGX {old_total:,}")

        existing = None
        try:
            existing = (
                AdmissionChangeRequest.objects.filter(
                    admitted_student=student,
                    change_type="exemption",
                    exemption_attained_at=ATTAINED_AT,
                )
                .prefetch_related("exemption_lines")
                .first()
            )
        except ProgrammingError as exc:
            raise CommandError(
                "Database is missing exemption columns (e.g. exemption_attained_at). "
                "Pull latest code and run:\n"
                "  python manage.py migrate admissions\n"
                "Then re-run this command.\n"
                f"Original error: {exc}"
            ) from exc

        if existing:
            w(
                f"\nExisting exemption change request #{existing.id} "
                f"(status={existing.status}) found — will reuse it."
            )

        if dry_run:
            w("\nDRY RUN — no changes were saved. Re-run without --dry-run to apply.")
            if not options["exempt_years"] and not line_ids_raw and not options.get("code_maps"):
                w(
                    "Hint: form HRM codes did not match NDU catalog. "
                    "Use:  python manage.py fix_alyao_exemption --dry-run --exempt-year 1"
                )
            return

        with transaction.atomic():
            decided_by = User.objects.filter(is_superuser=True).order_by("id").first()
            if decided_by is None:
                raise CommandError("No superuser found to attribute the backfill to.")

            change_request = existing
            if change_request is None:
                change_request = AdmissionChangeRequest.objects.create(
                    admitted_student=student,
                    requested_by=decided_by,
                    current_program=student.admitted_program,
                    current_campus=student.admitted_campus,
                    current_study_mode=student.study_mode,
                    change_type="exemption",
                    status="approved",
                    reason=(
                        "Retroactive record of a course exemption approved manually by the HOD/Dean "
                        "outside the system workflow. Backfilled by fix_alyao_exemption to correct billing."
                    ),
                    reviewed_by=decided_by,
                    reviewed_at=timezone.now(),
                    review_notes=(
                        "Backfilled from the physical exemption application form. Corrects an earlier "
                        f"billing error (raw ad-hoc charges totalling UGX {old_total:,} instead of the "
                        f"correct UGX {total:,}). Form papers were UMI codes; NDU curriculum links "
                        "applied via --exempt-year / --map / --line-ids."
                    ),
                    exemption_attained_at=ATTAINED_AT,
                    exemption_academic_years=ACADEMIC_YEARS,
                    exemption_is_alumnus=IS_ALUMNUS,
                    form_fee_paid_at=timezone.now(),
                )
                for label, score, line in resolved:
                    ExemptionRequestLine.objects.create(
                        change_request=change_request,
                        curriculum_line=line,
                        course_code=(
                            line.catalog_course.code if line.catalog_course else label
                        )[:40],
                        course_name=(
                            line.catalog_course.title if line and line.catalog_course else ""
                        ),
                        year_of_study=getattr(line, "year_of_study", None),
                        term_number=getattr(line, "term_number", None),
                        score_obtained=score,
                        decision=ExemptionRequestLine.DECISION_APPROVED,
                        decision_note=f"Backfilled from form paper {label}."[:255],
                    )
                self.stdout.write(
                    f"Created AdmissionChangeRequest #{change_request.id} with {len(resolved)} lines."
                )
            else:
                if change_request.status != "approved":
                    change_request.status = "approved"
                    change_request.reviewed_by = decided_by
                    change_request.reviewed_at = timezone.now()
                    change_request.save(
                        update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"]
                    )
                # Replace lines with the resolved set (idempotent refresh).
                change_request.exemption_lines.all().delete()
                for label, score, line in resolved:
                    ExemptionRequestLine.objects.create(
                        change_request=change_request,
                        curriculum_line=line,
                        course_code=(
                            line.catalog_course.code if line.catalog_course else label
                        )[:40],
                        course_name=(
                            line.catalog_course.title if line and line.catalog_course else ""
                        ),
                        year_of_study=getattr(line, "year_of_study", None),
                        term_number=getattr(line, "term_number", None),
                        score_obtained=score,
                        decision=ExemptionRequestLine.DECISION_APPROVED,
                        decision_note=f"Backfilled from form paper {label}."[:255],
                    )
                self.stdout.write(
                    f"Reused AdmissionChangeRequest #{change_request.id}; "
                    f"refreshed {len(resolved)} approved curriculum-linked lines."
                )

            created_overrides = apply_exemption_overrides(change_request, decided_by=decided_by)
            self.stdout.write(f"Applied {created_overrides} curriculum exemption override(s).")

            waived = 0
            for charge in old_charges:
                if charge.is_waived:
                    continue
                charge.is_waived = True
                charge.status = "waived"
                charge.waived_by = decided_by
                charge.waived_at = timezone.now()
                charge.notes = (
                    (charge.notes or "")
                    + f"\n[{timezone.now():%Y-%m-%d}] Waived by fix_alyao_exemption: incorrect manual "
                    f"amount, superseded by correctly computed charges under change request "
                    f"#{change_request.id}."
                ).strip()
                charge.save(
                    update_fields=[
                        "is_waived",
                        "status",
                        "waived_by",
                        "waived_at",
                        "notes",
                        "updated_at",
                    ]
                )
                waived += 1
            self.stdout.write(f"Waived {waived} old ad-hoc charge(s).")

            already_reissued = StudentTuitionPayment.objects.filter(
                student=student,
                source="ad_hoc",
                notes__icontains=f"change request #{change_request.id}",
                is_waived=False,
            ).exists()
            if already_reissued:
                self.stdout.write(
                    "Correct exemption charges already exist for this change request — skipping reissue."
                )
            else:
                from Programs.models import Semester

                program_batch_id = _student_program_batch_id(student)
                semesters = list(
                    Semester.objects.filter(
                        program_batch_id=program_batch_id,
                        year_of_study=TARGET_YEAR_OF_STUDY,
                        term_number__in=(1, 2),
                        is_active=True,
                    ).order_by("term_number")
                )
                if not semesters:
                    raise CommandError(
                        f"No active Year {TARGET_YEAR_OF_STUDY} semesters found for program_batch_id="
                        f"{program_batch_id}; cannot split the exemption charge. Create/activate those "
                        "semesters, then re-run."
                    )
                _, course_head = ensure_exemption_fee_heads()
                created = _create_split_adhoc_charges(
                    student=student,
                    fee_head=course_head,
                    label_base=(
                        f"Course exemption — {BILLABLE_PAPER_COUNT} papers ({ATTAINED_AT})"
                    ),
                    amount=total,
                    currency="UGX",
                    notes=(
                        f"Exemption change request #{change_request.id}; "
                        "corrected retroactively by fix_alyao_exemption."
                    ),
                    semesters=semesters,
                    charged_by=decided_by,
                )
                self.stdout.write(
                    f"Created {len(created)} correct exemption charge(s) totalling UGX {total:,} "
                    f"across {[f'Y{s.year_of_study}T{s.term_number}' for s in semesters]}."
                )

            if (
                enrollment.current_year_of_study,
                enrollment.current_term_number,
            ) != (TARGET_YEAR_OF_STUDY, TARGET_TERM_NUMBER):
                from admissions.exemption_services import advance_student_position_for_exemption

                result = advance_student_position_for_exemption(
                    change_request,
                    to_year=TARGET_YEAR_OF_STUDY,
                    to_term=TARGET_TERM_NUMBER,
                    decided_by=decided_by,
                )
                self.stdout.write(
                    f"Advanced position: Year {result['from_year_of_study']} Term "
                    f"{result['from_term_number']} -> Year {result['to_year_of_study']} Term "
                    f"{result['to_term_number']}."
                )
            else:
                self.stdout.write("Student is already at the target position — no advancement needed.")

        self.stdout.write(
            self.style.SUCCESS("\nDone. Alyao Jacqueline's exemption billing has been corrected.")
        )
