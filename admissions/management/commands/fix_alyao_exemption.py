"""
One-off correction for Ms. Alyao Jacqueline (26/2/508/W/2543) — the first real
application of the new Exemption Fee and Promotion System.

Background: her course exemption was approved manually by the HOD outside the
normal AdmissionChangeRequest workflow. Accounts then typed two raw ad-hoc
charges totalling UGX 3,240,000 — about 2.4x the correct amount — and those
charges ignored billing dates entirely (both fixed already, separately). Her
physical "Application Form for Exemption" lists 9 papers at the standard
UGX 150,000/paper rate (she attained the credit at Uganda Management
Institute, 2019/2020 — not an alumna of this university), for a correct total
of UGX 1,350,000. Once curriculum overrides are applied, Year 1 semester
tuition is dropped/prorated automatically (functional fees stay); the HOD's
decision was for her to begin at Year 2 Term 1.

This command:
  1. Creates the AdmissionChangeRequest (exemption, approved) that should have
     existed from the start, with the 9 ExemptionRequestLine rows from her form.
  2. Applies the curriculum exemption overrides (same effect as a normal HOD
     approval via admissions.exemption_services.apply_exemption_overrides).
  3. Waives the two incorrect ad-hoc charges (ids configurable via
     --old-charge-ids, default 54 55).
  4. Reissues the correct exemption fee (9 x 150,000 = 1,350,000 UGX) split
     across Year 2 Term 1 / Year 2 Term 2 for her program batch.
  5. Advances her StudentProgrammeEnrollment to Year 2 Term 1 (and records
     entry_year_of_study/entry_term_number if this is her first advancement).

Always run with --dry-run first and read the output carefully — in particular
the curriculum-line matching report — before running for real. This command
is intentionally idempotent: re-running it after a successful apply reuses
the existing AdmissionChangeRequest instead of creating a duplicate, and will
not double-waive or double-charge.

Usage:
    python manage.py fix_alyao_exemption --dry-run
    python manage.py fix_alyao_exemption
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
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

# Transcribed from the physical "Application Form for Exemption". Score
# columns from the form were not available when this command was written —
# fill them in below (or via Django admin afterwards on the ExemptionRequestLine
# rows) if they need to appear on record.
PAPERS: list[tuple[str, str]] = [
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


def _normalize_code(code: str) -> str:
    return code.strip().upper().replace(" ", "").replace("-", "")


class Command(BaseCommand):
    help = "One-off correction of Ms. Alyao Jacqueline's course exemption billing + academic position."

    def add_arguments(self, parser):
        parser.add_argument("--reg-no", default=REG_NO_DEFAULT)
        parser.add_argument(
            "--old-charge-ids",
            default="54,55",
            help="Comma-separated StudentTuitionPayment ids to waive (default: 54,55).",
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

        # ------------------------------------------------------------------
        # Resolve curriculum lines by course code (best-effort match).
        # ------------------------------------------------------------------
        from Programs.models import ProgramCurriculumLine, resolve_program_default_curriculum_version

        version = enrollment.curriculum_version
        if version is None and enrollment.program_batch_id:
            version = enrollment.program_batch.curriculum_version
        if version is None:
            version = resolve_program_default_curriculum_version(enrollment.program)

        by_code = {}
        if version is not None:
            for line in ProgramCurriculumLine.objects.filter(
                curriculum_version=version, program_id=enrollment.program_id
            ).select_related("catalog_course"):
                if line.catalog_course:
                    by_code[_normalize_code(line.catalog_course.code)] = line

        matched_lines: dict[str, object] = {}
        unmatched_codes: list[str] = []
        w("\nCourse code -> curriculum line match report:")
        for code, _score in PAPERS:
            line = by_code.get(_normalize_code(code))
            if line:
                matched_lines[code] = line
                w(f"  {code:<12} matched -> Y{line.year_of_study}T{line.term_number} (line id={line.id})")
            else:
                unmatched_codes.append(code)
                w(f"  {code:<12} NOT MATCHED — cannot approve until mapped to curriculum")

        if unmatched_codes and not dry_run:
            raise CommandError(
                "These paper codes are not on the student's curriculum version: "
                f"{', '.join(unmatched_codes)}. Fix curriculum codes/mapping, then re-run. "
                "(Dry-run still reports; real apply requires every paper matched.)"
            )

        rate = exemption_course_fee_rate_for(IS_ALUMNUS)
        total = rate * len(PAPERS)
        w(f"\nPricing: {'alumni' if IS_ALUMNUS else 'standard'} rate UGX {rate:,}/paper "
          f"x {len(PAPERS)} papers = UGX {total:,}")

        # ------------------------------------------------------------------
        # Old (incorrect) charges to waive.
        # ------------------------------------------------------------------
        old_charges = list(StudentTuitionPayment.objects.filter(student=student, id__in=old_charge_ids))
        found_ids = {c.id for c in old_charges}
        missing_ids = [i for i in old_charge_ids if i not in found_ids]
        if missing_ids:
            w(f"\nWARNING: old charge id(s) not found on this student: {missing_ids}")
        old_total = sum((Decimal(str(c.amount)) for c in old_charges if not c.is_waived), Decimal("0"))
        w(f"\nOld charges to waive ({len(old_charges)} found):")
        for c in old_charges:
            w(f"  #{c.id} amount={c.amount} status={c.status} is_waived={c.is_waived} label={c.label!r}")
        w(f"  total unwaived old amount: UGX {old_total:,}")

        existing = (
            AdmissionChangeRequest.objects.filter(
                admitted_student=student,
                change_type="exemption",
                exemption_attained_at=ATTAINED_AT,
            )
            .prefetch_related("exemption_lines")
            .first()
        )
        if existing:
            w(f"\nExisting exemption change request #{existing.id} (status={existing.status}) found for "
              "this attained-at institution — will reuse it instead of creating a duplicate.")

        if dry_run:
            w("\nDRY RUN — no changes were saved. Re-run without --dry-run to apply.")
            return

        with transaction.atomic():
            decided_by = User.objects.filter(is_superuser=True).order_by("id").first()

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
                        f"correct UGX {total:,})."
                    ),
                    exemption_attained_at=ATTAINED_AT,
                    exemption_academic_years=ACADEMIC_YEARS,
                    exemption_is_alumnus=IS_ALUMNUS,
                    form_fee_paid_at=timezone.now(),
                )
                for code, score in PAPERS:
                    line = matched_lines.get(code)
                    ExemptionRequestLine.objects.create(
                        change_request=change_request,
                        curriculum_line=line,
                        course_code=code,
                        course_name=(line.catalog_course.name if line and line.catalog_course else ""),
                        year_of_study=getattr(line, "year_of_study", None),
                        term_number=getattr(line, "term_number", None),
                        score_obtained=score,
                        # Per-paper decisions are required for apply_exemption_overrides().
                        decision=ExemptionRequestLine.DECISION_APPROVED,
                        decision_note="Backfilled: HOD approved on physical form.",
                    )
                self.stdout.write(f"Created AdmissionChangeRequest #{change_request.id} with {len(PAPERS)} lines.")
            else:
                # Ensure reused request is approved and every paper is matched + approved.
                if change_request.status != "approved":
                    change_request.status = "approved"
                    change_request.reviewed_by = decided_by
                    change_request.reviewed_at = timezone.now()
                    change_request.save(
                        update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"]
                    )
                existing_by_code = {
                    _normalize_code(l.course_code): l
                    for l in change_request.exemption_lines.all()
                    if l.course_code
                }
                for code, score in PAPERS:
                    curr = matched_lines.get(code)
                    row = existing_by_code.get(_normalize_code(code))
                    if row is None:
                        ExemptionRequestLine.objects.create(
                            change_request=change_request,
                            curriculum_line=curr,
                            course_code=code,
                            course_name=(
                                curr.catalog_course.name if curr and curr.catalog_course else ""
                            ),
                            year_of_study=getattr(curr, "year_of_study", None),
                            term_number=getattr(curr, "term_number", None),
                            score_obtained=score,
                            decision=ExemptionRequestLine.DECISION_APPROVED,
                            decision_note="Backfilled: HOD approved on physical form.",
                        )
                        continue
                    row.curriculum_line = curr
                    row.course_name = (
                        curr.catalog_course.name if curr and curr.catalog_course else row.course_name
                    )
                    row.year_of_study = getattr(curr, "year_of_study", None)
                    row.term_number = getattr(curr, "term_number", None)
                    if score and not row.score_obtained:
                        row.score_obtained = score
                    row.decision = ExemptionRequestLine.DECISION_APPROVED
                    if not row.decision_note:
                        row.decision_note = "Backfilled: HOD approved on physical form."
                    row.save()
                self.stdout.write(
                    f"Reused AdmissionChangeRequest #{change_request.id}; "
                    "ensured all papers are approved and curriculum-linked."
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

            # Reissue the correct exemption fee, split across Year 2 Term 1 / Term 2.
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
                    label_base=f"Course exemption — {len(PAPERS)} papers ({ATTAINED_AT})",
                    amount=total,
                    currency="UGX",
                    notes=f"Exemption change request #{change_request.id}; corrected retroactively by fix_alyao_exemption.",
                    semesters=semesters,
                    charged_by=decided_by,
                )
                self.stdout.write(
                    f"Created {len(created)} correct exemption charge(s) totalling UGX {total:,} "
                    f"across {[f'Y{s.year_of_study}T{s.term_number}' for s in semesters]}."
                )

            # Advance her curriculum position — the HOD's decision was made
            # out-of-band, so this applies it directly rather than requiring
            # suggest_promotion_after_exemption() to independently agree.
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

        self.stdout.write(self.style.SUCCESS("\nDone. Alyao Jacqueline's exemption billing has been corrected."))


def exemption_course_fee_rate_for(is_alumnus: bool) -> Decimal:
    """Standalone helper so the report section above can print the rate before any DB writes."""
    from admissions.exemption_services import EXEMPTION_COURSE_FEE_ALUMNI_UGX, EXEMPTION_COURSE_FEE_STANDARD_UGX

    return EXEMPTION_COURSE_FEE_ALUMNI_UGX if is_alumnus else EXEMPTION_COURSE_FEE_STANDARD_UGX
