"""Exemption change-request helpers: form fee gate + eligible curriculum lines."""
from __future__ import annotations

import time
from decimal import Decimal

from django.conf import settings
from django.db import OperationalError, transaction
from django.utils import timezone

from admissions.models import AdmittedStudent, AdmissionChangeRequest
from payments.models import FeeHead, StudentTuitionPayment
from payments.student_payment_allocation import build_finance_allocation

EXEMPTION_FORM_FEE_CODE = "EXEMPTION_FORM"
EXEMPTION_COURSE_FEE_CODE = "EXEMPTION_COURSE"
EXEMPTION_FORM_FEE_UGX = Decimal(
    str(getattr(settings, "EXEMPTION_FORM_FEE_UGX", "50000"))
)

# Per-paper exemption fee (Accounts):
#   - non-Ndejje: UGX 150,000 / paper
#   - Ndejje alumni (did undergrad here): UGX 100,000 / paper
# Both are settings-overridable so Finance can retune them without a deploy.
# Separately, semester TUITION (not functional) is replaced by
# (tuition / papers) × papers still taken — see prorate_tuition_for_course_exemptions.
EXEMPTION_COURSE_FEE_STANDARD_UGX = Decimal(
    str(getattr(settings, "EXEMPTION_COURSE_FEE_STANDARD_UGX", "150000"))
)
EXEMPTION_COURSE_FEE_ALUMNI_UGX = Decimal(
    str(getattr(settings, "EXEMPTION_COURSE_FEE_ALUMNI_UGX", "100000"))
)


def exemption_course_fee_rate(change_request: "AdmissionChangeRequest") -> Decimal:
    """UGX fee per exempted paper for this request, based on its alumni flag."""
    if getattr(change_request, "exemption_is_alumnus", False):
        return EXEMPTION_COURSE_FEE_ALUMNI_UGX
    return EXEMPTION_COURSE_FEE_STANDARD_UGX


def exemption_course_fee_total(change_request: "AdmissionChangeRequest") -> Decimal:
    """Rate × papers that will be / were approved on this request."""
    from admissions.models import ExemptionRequestLine

    qs = change_request.exemption_lines.all()
    if change_request.status == "pending":
        # Estimate before review: all requested papers.
        line_count = qs.count()
    else:
        line_count = qs.filter(decision=ExemptionRequestLine.DECISION_APPROVED).count()
    return exemption_course_fee_rate(change_request) * Decimal(line_count)


def ensure_exemption_fee_heads() -> tuple[FeeHead, FeeHead]:
    form_head, _ = FeeHead.objects.get_or_create(
        code=EXEMPTION_FORM_FEE_CODE,
        defaults={
            "name": "Exemption application form",
            "category": "service",
            "description": "One-time UGX fee to unlock the course exemption application form.",
            "is_active": True,
        },
    )
    course_head, _ = FeeHead.objects.get_or_create(
        code=EXEMPTION_COURSE_FEE_CODE,
        defaults={
            "name": "Course exemption fee",
            "category": "tuition",
            "description": "Per-course exemption fee billed by Accounts after Dean approval.",
            "is_active": True,
        },
    )
    return form_head, course_head


def _open_form_fee_charge(student: AdmittedStudent) -> StudentTuitionPayment | None:
    form_head, _ = ensure_exemption_fee_heads()
    return (
        StudentTuitionPayment.objects.filter(
            student=student,
            source="ad_hoc",
            fee_head=form_head,
            is_waived=False,
            status__in=("pending", "completed"),
        )
        .order_by("-created_at")
        .first()
    )


def form_fee_paid_for_charge(student: AdmittedStudent, charge: StudentTuitionPayment) -> bool:
    if charge.status == "completed":
        return True
    if charge.is_waived:
        return False
    alloc = build_finance_allocation(student)
    for line in alloc.demand_lines:
        if line.kind == "ad_hoc" and line.charge_id == charge.id:
            return line.status == "paid" or line.balance <= 0
    return False


def _ensure_form_fee_charge(student: AdmittedStudent, *, charged_by=None) -> StudentTuitionPayment:
    """Create the 50k form-fee charge if missing; retry on SQLite lock contention."""
    form_head, _ = ensure_exemption_fee_heads()
    last_err: Exception | None = None
    for attempt in range(6):
        try:
            charge = _open_form_fee_charge(student)
            if charge is not None:
                return charge
            with transaction.atomic():
                charge = _open_form_fee_charge(student)
                if charge is not None:
                    return charge
                return StudentTuitionPayment.objects.create(
                    student=student,
                    source="ad_hoc",
                    fee_head=form_head,
                    label="Exemption application form fee",
                    amount=EXEMPTION_FORM_FEE_UGX,
                    currency="UGX",
                    status="pending",
                    notes="Auto-created to unlock course exemption change request form.",
                    charged_by=charged_by,
                    semester=None,
                )
        except OperationalError as exc:
            last_err = exc
            time.sleep(0.2 * (attempt + 1))
    if last_err:
        raise last_err
    raise OperationalError("Could not create exemption form fee charge.")


def _payment_code_for_student(student: AdmittedStudent) -> str:
    return (
        (getattr(student, "effective_schoolpay_code", None) or "").strip()
        or (student.student_id or "").strip()
        or (student.schoolpay_code or "").strip()
        or (student.reg_no or "").strip()
    )


def _form_fee_status_dict(
    student: AdmittedStudent,
    charge: StudentTuitionPayment | None,
) -> dict:
    """Serialize form-fee state. charge=None means bill not yet generated."""
    payment_code = _payment_code_for_student(student)
    if charge is None:
        return {
            "paid": False,
            "amount": float(EXEMPTION_FORM_FEE_UGX),
            "currency": "UGX",
            "balance": float(EXEMPTION_FORM_FEE_UGX),
            "charge_id": None,
            "charge_status": None,
            "paid_at": None,
            "fee_head_code": EXEMPTION_FORM_FEE_CODE,
            "bill_generated": False,
            "payment_code": payment_code,
            "schoolpay_hint": (
                f"On submit, a UGX {int(EXEMPTION_FORM_FEE_UGX):,} bill is posted to your "
                f"account. Pay via SchoolPay"
                + (f" using payment code {payment_code}" if payment_code else "")
                + ". Payment does not have to be instant."
            ),
        }

    paid = form_fee_paid_for_charge(student, charge)
    paid_at = None
    if paid:
        if charge.status != "completed":
            charge.status = "completed"
            if not charge.paid_at:
                charge.paid_at = timezone.now()
            charge.save(update_fields=["status", "paid_at", "updated_at"])
        paid_at = charge.paid_at

        AdmissionChangeRequest.objects.filter(
            admitted_student=student,
            change_type="exemption",
            form_fee_charge=charge,
            form_fee_paid_at__isnull=True,
        ).update(form_fee_paid_at=paid_at or timezone.now())

    balance = Decimal("0") if paid else Decimal(str(charge.amount))
    if not paid:
        alloc = build_finance_allocation(student)
        for line in alloc.demand_lines:
            if line.kind == "ad_hoc" and line.charge_id == charge.id:
                balance = line.balance
                break

    return {
        "paid": paid,
        "amount": float(EXEMPTION_FORM_FEE_UGX),
        "currency": "UGX",
        "balance": float(balance),
        "charge_id": charge.id,
        "charge_status": charge.status,
        "paid_at": paid_at.isoformat() if paid_at else None,
        "fee_head_code": EXEMPTION_FORM_FEE_CODE,
        "bill_generated": True,
        "payment_code": payment_code,
        "schoolpay_hint": (
            f"Pay via SchoolPay using payment code {payment_code}. "
            "Payment does not have to be instant — refresh after it posts."
            if payment_code
            else "Pay via SchoolPay using your student payment code. "
            "Refresh after payment posts."
        ),
    }


def exemption_form_fee_status(student: AdmittedStudent) -> dict:
    """Report existing form-fee charge without creating one (for form preview)."""
    return _form_fee_status_dict(student, _open_form_fee_charge(student))


def ensure_exemption_form_fee_access(student: AdmittedStudent, *, charged_by=None) -> dict:
    """
    Ensure a 50k form-fee charge exists (creates on first call) and report status.
    Called at exemption *submission* so the bill is generated with the application.
    """
    charge = _ensure_form_fee_charge(student, charged_by=charged_by)
    return _form_fee_status_dict(student, charge)


def student_is_exemption_form_unlocked(student: AdmittedStudent) -> bool:
    charge = _open_form_fee_charge(student)
    if charge is None:
        return False
    return form_fee_paid_for_charge(student, charge)


def exemption_form_fee_report(status_filter: str | None = None) -> list[dict]:
    """
    Accounts follow-up report: every exemption-form-fee charge ever raised, newest first.

    status_filter: 'pending' (unpaid), 'completed' (paid), or None for all.
    """
    form_head, _ = ensure_exemption_fee_heads()
    qs = (
        StudentTuitionPayment.objects.filter(
            source="ad_hoc",
            fee_head=form_head,
        )
        .select_related("student", "student__admitted_program")
        .order_by("-created_at")
    )
    if status_filter == "pending":
        qs = qs.filter(status="pending", is_waived=False)
    elif status_filter == "completed":
        qs = qs.filter(status="completed")

    charge_ids = [c.id for c in qs]
    requests_by_charge = {
        r.form_fee_charge_id: r
        for r in AdmissionChangeRequest.objects.filter(
            change_type="exemption",
            form_fee_charge_id__in=charge_ids,
        ).only("id", "form_fee_charge_id", "status", "created_at")
    }

    now = timezone.now()
    rows = []
    for charge in qs:
        student = charge.student
        req = requests_by_charge.get(charge.id)
        rows.append(
            {
                "charge_id": charge.id,
                "student_pk": student.pk if student else None,
                "student_id": student.student_id if student else "",
                "reg_no": student.reg_no if student else "",
                "student_name": student.full_name if student else "",
                "programme": (
                    student.admitted_program.name
                    if student and student.admitted_program_id
                    else None
                ),
                "amount": float(charge.amount),
                "currency": charge.currency,
                "status": charge.status,
                "is_waived": charge.is_waived,
                "charged_at": charge.created_at.isoformat() if charge.created_at else None,
                "days_pending": (
                    (now - charge.created_at).days
                    if charge.status == "pending" and not charge.is_waived and charge.created_at
                    else None
                ),
                "change_request_id": req.id if req else None,
                "change_request_status": req.status if req else None,
            }
        )
    return rows


def _norm_course_code(code: str) -> str:
    """Normalize course codes for fuzzy matching (ignore spaces/punctuation/case)."""
    import re

    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def _resolve_enrollment_curriculum_version(student: AdmittedStudent):
    from Programs.models import resolve_program_default_curriculum_version

    try:
        enrollment = student.programme_enrollment
    except Exception:
        enrollment = None
    if enrollment is None:
        return None, None

    version = enrollment.curriculum_version
    if version is None and enrollment.program_batch_id:
        version = enrollment.program_batch.curriculum_version
    if version is None:
        version = resolve_program_default_curriculum_version(enrollment.program)
    return enrollment, version


def list_eligible_exemption_courses(student: AdmittedStudent) -> list[dict]:
    """Curriculum lines for the student's pinned/default version, excluding existing exemptions."""
    from Programs.models import (
        ProgramCurriculumLine,
        StudentCurriculumOverride,
    )

    enrollment, version = _resolve_enrollment_curriculum_version(student)
    if enrollment is None or version is None:
        return []

    existing = set(
        StudentCurriculumOverride.objects.filter(
            enrollment=enrollment,
            override_type__in=("exempted", "transferred"),
        ).values_list("curriculum_line_id", flat=True)
    )
    # Also exclude lines already on a pending exemption request
    pending_line_ids = set(
        AdmissionChangeRequest.objects.filter(
            admitted_student=student,
            change_type="exemption",
            status="pending",
        ).values_list("exemption_lines__curriculum_line_id", flat=True)
    )
    existing |= {i for i in pending_line_ids if i}

    lines = (
        ProgramCurriculumLine.objects.filter(
            curriculum_version=version,
            is_active=True,
            program_id=enrollment.program_id,
        )
        .select_related("catalog_course")
        .order_by("year_of_study", "term_number", "sort_order", "catalog_course__code")
    )
    out = []
    for line in lines:
        if line.id in existing:
            continue
        course = line.catalog_course
        out.append(
            {
                "id": line.id,
                "course_code": course.code if course else "",
                # CourseCatalogUnit uses `title`, not `name`.
                "course_name": (course.title if course else "") or "",
                "year_of_study": line.year_of_study,
                "term_number": line.term_number,
                "course_type": line.course_type,
            }
        )
    return out


def list_programme_curriculum_for_review(student: AdmittedStudent) -> list[dict]:
    """
    Full active curriculum for HOD/Dean review — includes already-exempted rows
    so reviewers can see the whole programme when matching student papers.
    """
    from Programs.models import ProgramCurriculumLine, StudentCurriculumOverride

    enrollment, version = _resolve_enrollment_curriculum_version(student)
    if enrollment is None or version is None:
        return []

    existing = set(
        StudentCurriculumOverride.objects.filter(
            enrollment=enrollment,
            override_type__in=("exempted", "transferred"),
        ).values_list("curriculum_line_id", flat=True)
    )

    lines = (
        ProgramCurriculumLine.objects.filter(
            curriculum_version=version,
            is_active=True,
            program_id=enrollment.program_id,
        )
        .select_related("catalog_course")
        .order_by("year_of_study", "term_number", "sort_order", "catalog_course__code")
    )
    out = []
    for line in lines:
        course = line.catalog_course
        out.append(
            {
                "id": line.id,
                "course_code": course.code if course else "",
                "course_name": (course.title if course else "") or "",
                "year_of_study": line.year_of_study,
                "term_number": line.term_number,
                "course_type": line.course_type,
                "already_exempted": line.id in existing,
            }
        )
    return out


def suggest_curriculum_match(paper_code: str, curriculum: list[dict]) -> int | None:
    """Best curriculum line id for a typed paper code, or None."""
    target = _norm_course_code(paper_code)
    if not target:
        return None
    exact = [
        c for c in curriculum
        if not c.get("already_exempted") and _norm_course_code(c.get("course_code") or "") == target
    ]
    if len(exact) == 1:
        return exact[0]["id"]
    # Prefix / contains fallback when codes differ slightly (e.g. MHR4103 vs MHR 4103)
    soft = [
        c for c in curriculum
        if not c.get("already_exempted")
        and target
        and target in _norm_course_code(c.get("course_code") or "")
    ]
    if len(soft) == 1:
        return soft[0]["id"]
    return None


def apply_line_matches(change_request: AdmissionChangeRequest, matches: list[dict]) -> None:
    """
    Link free-text ExemptionRequestLine rows to ProgrammeCurriculumLine ids.
    matches: [{exemption_line_id, curriculum_line_id}, ...]
    """
    from Programs.models import ProgramCurriculumLine

    if not matches:
        return
    by_id = {
        line.id: line
        for line in change_request.exemption_lines.all()
    }
    curriculum_ids = {
        int(m["curriculum_line_id"])
        for m in matches
        if m.get("curriculum_line_id") not in (None, "", 0, "0")
    }
    curriculum_map = {
        c.id: c
        for c in ProgramCurriculumLine.objects.filter(pk__in=curriculum_ids).select_related(
            "catalog_course"
        )
    }
    for raw in matches:
        try:
            eid = int(raw.get("exemption_line_id"))
            cid = int(raw.get("curriculum_line_id"))
        except (TypeError, ValueError):
            raise ValueError("Each line match needs exemption_line_id and curriculum_line_id.")
        line = by_id.get(eid)
        if line is None:
            raise ValueError(f"Unknown exemption line {eid} on this request.")
        curriculum = curriculum_map.get(cid)
        if curriculum is None:
            raise ValueError(f"Unknown curriculum unit {cid}.")
        course = curriculum.catalog_course
        line.curriculum_line = curriculum
        # Keep the student's typed score; sync official code/name/year/term from curriculum.
        if course:
            line.course_code = (course.code or line.course_code or "")[:40]
            line.course_name = ((course.title or "") or line.course_name or "")[:255]
        line.year_of_study = curriculum.year_of_study
        line.term_number = curriculum.term_number
        line.save(
            update_fields=[
                "curriculum_line",
                "course_code",
                "course_name",
                "year_of_study",
                "term_number",
            ]
        )


def apply_line_decisions(change_request: AdmissionChangeRequest, decisions: list[dict]) -> None:
    """
    Record per-paper approve/reject on an exemption request.
    decisions: [{exemption_line_id, decision: 'approved'|'rejected', decision_note?, curriculum_line_id?}]
    """
    from admissions.models import ExemptionRequestLine
    from Programs.models import ProgramCurriculumLine

    if not decisions:
        raise ValueError("Provide a decision (approve or reject) for each requested paper.")

    by_id = {line.id: line for line in change_request.exemption_lines.all()}
    if not by_id:
        raise ValueError("This exemption request has no course papers.")

    seen: set[int] = set()
    curriculum_ids = {
        int(d["curriculum_line_id"])
        for d in decisions
        if d.get("curriculum_line_id") not in (None, "", 0, "0")
    }
    curriculum_map = {
        c.id: c
        for c in ProgramCurriculumLine.objects.filter(pk__in=curriculum_ids).select_related(
            "catalog_course"
        )
    }

    for raw in decisions:
        try:
            eid = int(raw.get("exemption_line_id"))
        except (TypeError, ValueError):
            raise ValueError("Each decision needs a valid exemption_line_id.")
        line = by_id.get(eid)
        if line is None:
            raise ValueError(f"Unknown exemption line {eid} on this request.")
        if eid in seen:
            raise ValueError(f"Duplicate decision for paper {line.course_code or eid}.")
        seen.add(eid)

        decision = str(raw.get("decision") or "").strip().lower()
        if decision in ("approve", "approved"):
            decision = ExemptionRequestLine.DECISION_APPROVED
        elif decision in ("reject", "rejected"):
            decision = ExemptionRequestLine.DECISION_REJECTED
        else:
            raise ValueError(
                f"Decision for {line.course_code or eid} must be approve or reject."
            )

        note = str(raw.get("decision_note") or "").strip()[:255]
        update_fields = ["decision", "decision_note"]

        if decision == ExemptionRequestLine.DECISION_APPROVED:
            cid_raw = raw.get("curriculum_line_id") or line.curriculum_line_id
            try:
                cid = int(cid_raw)
            except (TypeError, ValueError):
                raise ValueError(
                    f"Match {line.course_code or eid} to a curriculum unit before approving it."
                )
            curriculum = curriculum_map.get(cid) or (
                ProgramCurriculumLine.objects.select_related("catalog_course").filter(pk=cid).first()
            )
            if curriculum is None:
                raise ValueError(f"Unknown curriculum unit {cid}.")
            course = curriculum.catalog_course
            line.curriculum_line = curriculum
            if course:
                line.course_code = (course.code or line.course_code or "")[:40]
                line.course_name = ((course.title or "") or line.course_name or "")[:255]
            line.year_of_study = curriculum.year_of_study
            line.term_number = curriculum.term_number
            update_fields.extend(
                ["curriculum_line", "course_code", "course_name", "year_of_study", "term_number"]
            )
            line.decision_note = note
        else:
            line.decision_note = note or line.decision_note

        line.decision = decision
        line.save(update_fields=update_fields)

    undecided = [l for lid, l in by_id.items() if lid not in seen]
    if undecided:
        codes = ", ".join((l.course_code or f"#{l.id}") for l in undecided[:8])
        raise ValueError(
            "Decide every paper (approve or reject). Still pending: "
            f"{codes}."
        )


def apply_exemption_overrides(change_request: AdmissionChangeRequest, decided_by) -> int:
    """Create exempted StudentCurriculumOverride rows for approved papers only."""
    from admissions.models import ExemptionRequestLine
    from Programs.models import StudentCurriculumOverride

    if change_request.change_type != "exemption":
        return 0
    student = change_request.admitted_student
    try:
        enrollment = student.programme_enrollment
    except Exception:
        enrollment = None
    if enrollment is None:
        raise ValueError(
            "Student has no programme enrollment; cannot apply curriculum exemptions."
        )

    lines = list(
        change_request.exemption_lines.select_related("curriculum_line").filter(
            decision=ExemptionRequestLine.DECISION_APPROVED
        )
    )
    if not lines:
        # All papers rejected — valid outcome; no curriculum overrides.
        return 0

    unmapped = [l for l in lines if not l.curriculum_line_id]
    if unmapped:
        codes = ", ".join((l.course_code or f"#{l.id}") for l in unmapped[:8])
        raise ValueError(
            "Match each approved paper to a programme curriculum unit. "
            f"Unmatched: {codes}."
        )

    created = 0
    notes = (
        f"Approved via change request #{change_request.id}. "
        f"{(change_request.reason or '').strip()}"
    ).strip()
    for line in lines:
        line_notes = notes
        if line.decision_note:
            line_notes = f"{notes} Paper note: {line.decision_note}".strip()
        _, was_created = StudentCurriculumOverride.objects.get_or_create(
            enrollment=enrollment,
            curriculum_line_id=line.curriculum_line_id,
            defaults={
                "override_type": "exempted",
                "notes": line_notes[:2000],
                "decided_by": decided_by,
            },
        )
        if was_created:
            created += 1
        else:
            existing = StudentCurriculumOverride.objects.filter(
                enrollment=enrollment,
                curriculum_line_id=line.curriculum_line_id,
            ).first()
            if existing and existing.override_type != "exempted":
                existing.override_type = "exempted"
                existing.notes = line_notes[:2000]
                existing.decided_by = decided_by
                existing.save(
                    update_fields=["override_type", "notes", "decided_by", "updated_at"]
                )
                created += 1
    return created


def _resolve_curriculum_version(enrollment):
    from Programs.models import resolve_program_default_curriculum_version

    version = enrollment.curriculum_version
    if version is None and enrollment.program_batch_id:
        version = enrollment.program_batch.curriculum_version
    if version is None:
        version = resolve_program_default_curriculum_version(enrollment.program)
    return version


def semester_paper_counts_for_exemptions(
    student: AdmittedStudent,
    *,
    year_of_study: int,
    term_number: int,
) -> dict | None:
    """
    Paper counts for a semester used by Accounts' exemption tuition math.

    Returns None when the student has no enrolment / curriculum version, or the
    semester has no active curriculum papers (caller should leave tuition alone).

    Counts are by paper (ProgramCurriculumLine), not credit-hours — matching
    Accounts' "divide the semester tuition by the units/papers" rule.
    """
    from Programs.models import ProgramCurriculumLine, StudentCurriculumOverride

    try:
        enrollment = student.programme_enrollment
    except Exception:
        return None

    version = _resolve_curriculum_version(enrollment)
    if version is None:
        return None

    total = ProgramCurriculumLine.objects.filter(
        curriculum_version=version,
        program_id=enrollment.program_id,
        year_of_study=year_of_study,
        term_number=term_number,
        is_active=True,
    ).count()
    if total <= 0:
        return None

    exempted = StudentCurriculumOverride.objects.filter(
        enrollment=enrollment,
        override_type="exempted",
        curriculum_line__curriculum_version=version,
        curriculum_line__program_id=enrollment.program_id,
        curriculum_line__year_of_study=year_of_study,
        curriculum_line__term_number=term_number,
        curriculum_line__is_active=True,
    ).count()
    exempted = min(exempted, total)
    return {
        "total_papers": total,
        "exempted_papers": exempted,
        "non_exempted_papers": total - exempted,
    }


def prorate_tuition_for_course_exemptions(
    student: AdmittedStudent,
    tuition_amount: Decimal,
    *,
    year_of_study: int,
    term_number: int,
) -> tuple[Decimal, dict | None]:
    """
    Replace full semester tuition with Accounts' paper-based amount when the
    student has any course exemptions in that semester:

        amount = (semester_tuition / total_papers) * non_exempted_papers

    Functional fees are NOT adjusted here — they stay charged in full.
    If every paper is exempted, tuition becomes 0. If no exemptions (or no
    curriculum), the original tuition_amount is returned unchanged.
    """
    counts = semester_paper_counts_for_exemptions(
        student, year_of_study=year_of_study, term_number=term_number
    )
    if counts is None or counts["exempted_papers"] <= 0:
        return tuition_amount, counts

    total = Decimal(counts["total_papers"])
    remaining = Decimal(counts["non_exempted_papers"])
    if remaining <= 0:
        return Decimal("0.00"), counts

    prorated = (Decimal(str(tuition_amount)) / total * remaining).quantize(Decimal("0.01"))
    return prorated, counts


def _next_year_term(year: int, term: int, *, max_terms_per_year: int, max_years: int):
    """Next (year, term) pair in curriculum order, or None past the programme's end."""
    if term < max_terms_per_year:
        return year, term + 1
    if year < max_years:
        return year + 1, 1
    return None


def suggest_promotion_after_exemption(change_request: AdmissionChangeRequest) -> dict | None:
    """
    If the exemptions applied for this student now cover every paper in one or
    more consecutive terms starting at (or before) her current position, return
    the first term that still has non-exempted work — the position she should
    actually be advanced to. Returns None if no advancement is warranted.

    This is advisory only: nothing is changed until an HOD/Dean explicitly
    confirms via advance_student_position_for_exemption().
    """
    from Programs.models import ProgramCurriculumLine, StudentCurriculumOverride

    student = change_request.admitted_student
    try:
        enrollment = student.programme_enrollment
    except Exception:
        return None

    version = _resolve_curriculum_version(enrollment)
    if version is None:
        return None

    program = enrollment.program
    max_terms_per_year = program.max_terms_per_year
    max_years = program.max_years

    lines = ProgramCurriculumLine.objects.filter(
        curriculum_version=version,
        is_active=True,
        program_id=enrollment.program_id,
    ).values_list("id", "year_of_study", "term_number")

    by_term: dict[tuple[int, int], set[int]] = {}
    for line_id, year, term in lines:
        by_term.setdefault((year, term), set()).add(line_id)

    if not by_term:
        return None

    exempted_ids = set(
        StudentCurriculumOverride.objects.filter(
            enrollment=enrollment,
            override_type="exempted",
        ).values_list("curriculum_line_id", flat=True)
    )

    cur_year, cur_term = enrollment.current_year_of_study, enrollment.current_term_number
    year, term = cur_year, cur_term
    covered_terms: list[tuple[int, int]] = []

    while True:
        term_line_ids = by_term.get((year, term))
        # A term with no curriculum lines defined isn't "covered" — stop rather
        # than guess past a gap in the curriculum blueprint.
        if not term_line_ids or not term_line_ids.issubset(exempted_ids):
            break
        covered_terms.append((year, term))
        nxt = _next_year_term(
            year, term, max_terms_per_year=max_terms_per_year, max_years=max_years
        )
        if nxt is None:
            break
        year, term = nxt

    if not covered_terms or (year, term) == (cur_year, cur_term):
        return None

    return {
        "current_year_of_study": cur_year,
        "current_term_number": cur_term,
        "suggested_year_of_study": year,
        "suggested_term_number": term,
        "covered_terms": [{"year_of_study": y, "term_number": t} for y, t in covered_terms],
    }


def advance_student_position_for_exemption(
    change_request: AdmissionChangeRequest,
    *,
    to_year: int,
    to_term: int,
    decided_by,
) -> dict:
    """
    HOD-confirmed action: move the student's current curriculum position forward
    to (to_year, to_term) and record it as an advanced-entry point if this is the
    first time her position has moved past the default Year 1 Term 1.
    """
    student = change_request.admitted_student
    try:
        enrollment = student.programme_enrollment
    except Exception as exc:
        raise ValueError("Student has no programme enrollment to advance.") from exc

    from_year, from_term = enrollment.current_year_of_study, enrollment.current_term_number

    update_fields = ["current_year_of_study", "current_term_number", "updated_at"]
    enrollment.current_year_of_study = to_year
    enrollment.current_term_number = to_term
    # Document advanced entry when the student was still at the default Y1T1
    # start point. entry_* is auto-stamped to current on first SPE save, so a
    # Null check alone would miss every normally-enrolled student — treat the
    # default (1, 1) the same as "not yet a true advanced-entry record".
    entry_y = enrollment.entry_year_of_study
    entry_t = enrollment.entry_term_number
    if (from_year, from_term) == (1, 1) and entry_y in (None, 1) and entry_t in (None, 1):
        enrollment.entry_year_of_study = to_year
        enrollment.entry_term_number = to_term
        update_fields += ["entry_year_of_study", "entry_term_number"]
    enrollment.save(update_fields=update_fields)

    note = (
        f"[{timezone.now():%Y-%m-%d %H:%M}] Advanced Y{from_year}T{from_term} -> "
        f"Y{to_year}T{to_term} following approved course exemption "
        f"(change request #{change_request.id}), confirmed by "
        f"{getattr(decided_by, 'get_full_name', lambda: decided_by)() or decided_by}."
    )
    change_request.review_notes = "\n".join(
        filter(None, [change_request.review_notes, note])
    )[:20000]
    change_request.save(update_fields=["review_notes", "updated_at"])

    return {
        "from_year_of_study": from_year,
        "from_term_number": from_term,
        "to_year_of_study": to_year,
        "to_term_number": to_term,
    }
