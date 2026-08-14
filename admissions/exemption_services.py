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
# Minimum mark (%) a candidate must have scored for a paper to be exemptable.
EXEMPTION_MIN_MARK_PERCENT = Decimal(
    str(getattr(settings, "EXEMPTION_MIN_MARK_PERCENT", "60"))
)


def parse_exemption_mark_floor(score_obtained: str | None) -> Decimal | None:
    """
    Best-effort lower mark from student score text.

    Accepts:
      - "65"
      - "60-64" / "60–64.9"
      - "B+ (60-64.9)" / "B+ (60–64.9)"
    Returns the first numeric floor found, or None if unparseable.
    """
    import re

    text = (score_obtained or "").strip()
    if not text:
        return None
    # Prefer range inside parentheses (grade + scheme range).
    paren = re.search(r"\(([^)]*)\)", text)
    chunk = paren.group(1) if paren else text
    m = re.search(r"(\d+(?:\.\d+)?)", chunk.replace(",", ""))
    if not m:
        return None
    try:
        return Decimal(m.group(1))
    except Exception:
        return None


def exemption_paper_meets_min_mark(
    paper: dict,
    *,
    min_percent: Decimal | None = None,
) -> tuple[bool, str]:
    """
    True when the paper's score/grade band floor is >= EXEMPTION_MIN_MARK_PERCENT.
    Optionally accepts client-supplied min_mark (from grading scheme band).
    """
    threshold = min_percent if min_percent is not None else EXEMPTION_MIN_MARK_PERCENT
    floor: Decimal | None = None
    raw_min = paper.get("min_mark")
    if raw_min not in (None, ""):
        try:
            floor = Decimal(str(raw_min))
        except Exception:
            floor = None
    if floor is None:
        floor = parse_exemption_mark_floor(str(paper.get("score_obtained") or ""))
    code = (str(paper.get("course_code") or "").strip() or "paper")
    if floor is None:
        return (
            False,
            f"{code}: enter a grade/score of at least {threshold:g}% "
            "(papers below 60% cannot be exempted).",
        )
    if floor < threshold:
        return (
            False,
            f"{code}: scored {floor:g}% — exemption requires {threshold:g}% and above.",
        )
    return True, ""

# Legacy flat rates (settings-overridable). Kept for display/migration only —
# Accounts now bills EXEMPTION_COURSE as semester tuition ÷ curriculum papers
# (no functional fees). See exemption_course_fee_for_paper().
EXEMPTION_COURSE_FEE_STANDARD_UGX = Decimal(
    str(getattr(settings, "EXEMPTION_COURSE_FEE_STANDARD_UGX", "150000"))
)
EXEMPTION_COURSE_FEE_ALUMNI_UGX = Decimal(
    str(getattr(settings, "EXEMPTION_COURSE_FEE_ALUMNI_UGX", "100000"))
)


def exemption_course_fee_rate(change_request: "AdmissionChangeRequest") -> Decimal | None:
    """
    Legacy single flat rate (alumni vs standard). Prefer per-paper
    exemption_course_fee_for_paper / exemption_billing_lines_for_request —
    those use tuition ÷ papers. Returns None when the request should use
    curriculum-based amounts instead of a flat rate.
    """
    # Flat rates are retired as the billing default. Callers that still need a
    # display fallback can use EXEMPTION_COURSE_FEE_* constants directly.
    _ = change_request
    return None


def semester_tuition_amount_for_student(
    student: AdmittedStudent,
    *,
    year_of_study: int,
    term_number: int,
) -> Decimal | None:
    """
    Programme TUITION_FEE amount for the student's cohort semester matching
    (year_of_study, term_number). Functional fees are excluded.

    Uses the fee-plan tuition structure amount regardless of the semester's
    billing date — required for exemption per-paper fees and for promoted
    students whose next term has not officially opened yet.
    """
    from payments.student_fee_pricing import effective_amount_currency
    from payments.student_portal_finance import _rules_for_student

    international = bool(getattr(student, "is_international", False))
    for rule in _rules_for_student(student):
        fee_code = (rule.fee_head.code or "").upper() if rule.fee_head_id else ""
        if fee_code != "TUITION_FEE":
            continue
        sem = rule.semester
        if sem is None:
            continue
        if int(sem.year_of_study or 0) != int(year_of_study):
            continue
        if int(sem.term_number or 0) != int(term_number):
            continue
        amt, _cur = effective_amount_currency(rule, international)
        if amt > 0:
            return Decimal(str(amt))
    return None


def exemption_course_fee_for_paper(
    student: AdmittedStudent,
    *,
    year_of_study: int,
    term_number: int,
) -> Decimal:
    """
    Accounts rule: (semester tuition excluding functional fees) ÷ papers in
    that curriculum year/term. Raises ValueError when tuition or papers
    cannot be resolved.
    """
    from decimal import ROUND_HALF_UP

    tuition = semester_tuition_amount_for_student(
        student, year_of_study=year_of_study, term_number=term_number
    )
    if tuition is None or tuition <= 0:
        raise ValueError(
            f"No semester tuition configured for Year {year_of_study} "
            f"Term {term_number}."
        )
    counts = semester_paper_counts_for_exemptions(
        student, year_of_study=year_of_study, term_number=term_number
    )
    if counts is None or counts["total_papers"] <= 0:
        raise ValueError(
            f"No curriculum papers found for Year {year_of_study} "
            f"Term {term_number}."
        )
    total = Decimal(counts["total_papers"])
    return (tuition / total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _billable_exemption_lines(change_request: "AdmissionChangeRequest"):
    from admissions.models import ExemptionRequestLine

    qs = change_request.exemption_lines.all()
    if change_request.status == "pending":
        return list(qs)
    return list(qs.filter(decision=ExemptionRequestLine.DECISION_APPROVED))


def exemption_billing_lines_for_request(
    change_request: "AdmissionChangeRequest",
) -> list[dict]:
    """
    Per approved (or pending-estimate) paper: amount = tuition÷papers for that
    paper's curriculum year/term, plus resolved semester metadata when available.
    """
    from payments.billing_visibility import resolve_semester_for_year_term
    from payments.student_portal_finance import _student_program_batch_id

    student = change_request.admitted_student
    pb_id = _student_program_batch_id(student)
    out: list[dict] = []
    for line in _billable_exemption_lines(change_request):
        year = line.year_of_study
        term = line.term_number
        if (year is None or term is None) and line.curriculum_line_id:
            cl = line.curriculum_line
            if cl is not None:
                year = cl.year_of_study
                term = cl.term_number
        amount = None
        error = None
        semester = None
        if year is not None and term is not None:
            try:
                amount = exemption_course_fee_for_paper(
                    student, year_of_study=int(year), term_number=int(term)
                )
            except ValueError as exc:
                error = str(exc)
            semester = resolve_semester_for_year_term(
                program_batch_id=pb_id,
                year_of_study=int(year),
                term_number=int(term),
            )
        else:
            error = "Paper has no year/term — match it to a curriculum unit first."
        out.append(
            {
                "exemption_line_id": line.id,
                "curriculum_line_id": line.curriculum_line_id,
                "course_code": line.course_code or "",
                "course_name": line.course_name or "",
                "score_obtained": line.score_obtained or "",
                "year_of_study": int(year) if year is not None else None,
                "term_number": int(term) if term is not None else None,
                "amount": float(amount) if amount is not None else None,
                "semester_id": semester.id if semester is not None else None,
                "semester_label": (
                    f"Year {semester.year_of_study}, Term {semester.term_number}"
                    f" — {semester.name}"
                    if semester is not None
                    else None
                ),
                "error": error,
            }
        )
    return out


def exemption_course_fee_total(change_request: "AdmissionChangeRequest") -> Decimal:
    """Sum of tuition÷papers amounts for billable papers on this request."""
    total = Decimal("0.00")
    for row in exemption_billing_lines_for_request(change_request):
        if row.get("amount") is not None:
            total += Decimal(str(row["amount"]))
    return total


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
    """
    Unlock only after this portal sent a SchoolPay phone prompt (STK).

    A random payment_reference on the bill is not enough — tuition / ledger
    sync can copy SchoolPay refs without the student paying the form fee.
    """
    if charge.is_waived:
        return False
    if charge.status != "completed":
        return False
    tid = (charge.transaction_id or "").strip()
    notes = charge.notes or ""
    return tid.startswith("EXF-") or "Exemption form fee STK" in notes


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
                    notes="Auto-created when the student opens the course exemption form; must be paid before submit.",
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
            "payment_reference": None,
            "stk_pending": False,
            "schoolpay_hint": (
                f"Pay UGX {int(EXEMPTION_FORM_FEE_UGX):,} via mobile money prompt on this page "
                f"(or SchoolPay"
                + (f" code {payment_code}" if payment_code else "")
                + "). Submit is blocked until the form fee is paid."
            ),
        }

    paid = form_fee_paid_for_charge(student, charge)
    paid_at = None
    if paid:
        paid_at = charge.paid_at
        AdmissionChangeRequest.objects.filter(
            admitted_student=student,
            change_type="exemption",
            form_fee_charge=charge,
            form_fee_paid_at__isnull=True,
        ).update(form_fee_paid_at=paid_at or timezone.now())

    balance = Decimal("0") if paid else Decimal(str(charge.amount))
    if not paid:
        # Informational only — unlock still requires charge.status == completed.
        try:
            alloc = build_finance_allocation(student)
            for line in alloc.demand_lines:
                if line.kind == "ad_hoc" and line.charge_id == charge.id:
                    balance = line.balance
                    break
        except Exception:
            pass

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
        "payment_reference": (charge.payment_reference or "").strip() or None,
        "stk_pending": bool(
            not paid
            and charge.status == "pending"
            and (charge.payment_reference or "").strip()
        ),
        "schoolpay_hint": (
            f"Enter your MoMo number below to receive a UGX {int(EXEMPTION_FORM_FEE_UGX):,} "
            "payment prompt on your phone."
            + (
                f" You can also pay via SchoolPay using code {payment_code}."
                if payment_code
                else ""
            )
        ),
    }


def exemption_form_fee_status(student: AdmittedStudent) -> dict:
    """Report existing form-fee charge without creating one."""
    return _form_fee_status_dict(student, _open_form_fee_charge(student))


def ensure_exemption_form_fee_access(student: AdmittedStudent, *, charged_by=None) -> dict:
    """
    Ensure a 50k form-fee charge exists (creates on first call) and report status.
    Called when the student opens the exemption form so they can pay before submit.
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
    """
    Return (enrollment, effective_curriculum_version).

    Inherited campus programmes often still pin an empty local "Default
    curriculum" version on the enrollment; real lines live on the master
    programme. Use resolve_effective_curriculum_version so those students
    see the master's units.
    """
    from Programs.curriculum_inheritance import resolve_effective_curriculum_version

    try:
        enrollment = student.programme_enrollment
    except Exception:
        enrollment = None
    if enrollment is None:
        return None, None

    batch = enrollment.program_batch if enrollment.program_batch_id else None
    version = resolve_effective_curriculum_version(enrollment.program, batch=batch)
    return enrollment, version


def _curriculum_line_program_id(enrollment) -> int | None:
    """Programme id that owns curriculum lines for this enrollment."""
    from Programs.curriculum_inheritance import curriculum_owner_program

    owner = curriculum_owner_program(enrollment.program)
    return owner.pk if owner else enrollment.program_id


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

    owner_program_id = _curriculum_line_program_id(enrollment)
    lines = (
        ProgramCurriculumLine.objects.filter(
            curriculum_version=version,
            is_active=True,
            program_id=owner_program_id,
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

    owner_program_id = _curriculum_line_program_id(enrollment)
    lines = (
        ProgramCurriculumLine.objects.filter(
            curriculum_version=version,
            is_active=True,
            program_id=owner_program_id,
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


def _code_digit_tail(code: str) -> str:
    """Trailing digit run from a course code (e.g. MHR4103 → 4103)."""
    import re

    m = re.search(r"(\d+)\s*$", (code or "").strip())
    return m.group(1) if m else ""


def suggest_curriculum_match(
    paper_code: str,
    curriculum: list[dict],
    *,
    course_name: str | None = None,
    year_of_study: int | None = None,
    term_number: int | None = None,
) -> int | None:
    """
    Best curriculum line id for a typed student paper.

    Tries exact/soft code match, then same year/term + digit tail / name overlap
    so HOD review can prefill units the student already identified.
    """
    open_rows = [c for c in curriculum if not c.get("already_exempted")]
    if not open_rows:
        return None

    target = _norm_course_code(paper_code)
    if target:
        exact = [
            c for c in open_rows
            if _norm_course_code(c.get("course_code") or "") == target
        ]
        if len(exact) == 1:
            return exact[0]["id"]
        soft = [
            c for c in open_rows
            if target in _norm_course_code(c.get("course_code") or "")
            or _norm_course_code(c.get("course_code") or "") in target
        ]
        if len(soft) == 1:
            return soft[0]["id"]

    pool = open_rows
    if year_of_study is not None and term_number is not None:
        yt = [
            c for c in open_rows
            if c.get("year_of_study") == year_of_study
            and c.get("term_number") == term_number
        ]
        if yt:
            pool = yt

    digits = _code_digit_tail(paper_code or "")
    if digits and len(digits) >= 3:
        digit_hits = [
            c for c in pool
            if _code_digit_tail(c.get("course_code") or "") == digits
        ]
        if len(digit_hits) == 1:
            return digit_hits[0]["id"]

    name = (course_name or "").strip().lower()
    if name and len(name) >= 6:
        name_hits = [
            c for c in pool
            if name in (c.get("course_name") or "").strip().lower()
            or (c.get("course_name") or "").strip().lower() in name
        ]
        if len(name_hits) == 1:
            return name_hits[0]["id"]
        # Token overlap (e.g. "Research Methods" vs "Research Methods in …")
        tokens = {t for t in name.replace("/", " ").split() if len(t) >= 4}
        if tokens:
            scored: list[tuple[int, dict]] = []
            for c in pool:
                other = (c.get("course_name") or "").strip().lower()
                other_tokens = {t for t in other.replace("/", " ").split() if len(t) >= 4}
                overlap = len(tokens & other_tokens)
                if overlap >= 2 or (overlap == 1 and len(tokens) == 1):
                    scored.append((overlap, c))
            scored.sort(key=lambda x: -x[0])
            if len(scored) == 1 or (len(scored) >= 2 and scored[0][0] > scored[1][0]):
                return scored[0][1]["id"]
    return None


def lookup_exemption_paper_by_code(student: AdmittedStudent, paper_code: str) -> dict | None:
    """
    Resolve a typed paper code to a course name (and year/sem when known).

    Prefer the student's eligible curriculum, then fall back to the shared catalog.
    """
    target = _norm_course_code(paper_code)
    if not target:
        return None

    try:
        eligible = list_eligible_exemption_courses(student)
    except Exception:
        eligible = []
    for c in eligible:
        if _norm_course_code(c.get("course_code") or "") == target:
            return {
                "curriculum_line_id": c.get("id"),
                "course_code": c.get("course_code") or paper_code.strip(),
                "course_name": c.get("course_name") or "",
                "year_of_study": c.get("year_of_study"),
                "term_number": c.get("term_number"),
                "source": "curriculum",
            }
    soft = [
        c
        for c in eligible
        if target and target in _norm_course_code(c.get("course_code") or "")
    ]
    if len(soft) == 1:
        c = soft[0]
        return {
            "curriculum_line_id": c.get("id"),
            "course_code": c.get("course_code") or paper_code.strip(),
            "course_name": c.get("course_name") or "",
            "year_of_study": c.get("year_of_study"),
            "term_number": c.get("term_number"),
            "source": "curriculum",
        }

    from Programs.models import CourseCatalogUnit

    raw = (paper_code or "").strip()
    nospace = "".join(raw.split())
    catalog_qs = CourseCatalogUnit.objects.filter(is_active=True).only("code", "title")
    hit = (
        catalog_qs.filter(code__iexact=raw).first()
        or catalog_qs.filter(code__iexact=nospace).first()
    )
    if hit:
        return {
            "curriculum_line_id": None,
            "course_code": hit.code,
            "course_name": hit.title or "",
            "year_of_study": None,
            "term_number": None,
            "source": "catalog",
        }
    # Soft match on a small candidate set (codes that contain the typed digits/letters).
    tip = nospace[:4] if len(nospace) >= 4 else nospace
    if tip:
        candidates = list(catalog_qs.filter(code__icontains=tip)[:80])
        soft_cat = [c for c in candidates if target in _norm_course_code(c.code)]
        if len(soft_cat) == 1:
            c = soft_cat[0]
            return {
                "curriculum_line_id": None,
                "course_code": c.code,
                "course_name": c.title or "",
                "year_of_study": None,
                "term_number": None,
                "source": "catalog",
            }
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
    from Programs.curriculum_inheritance import resolve_effective_curriculum_version

    batch = enrollment.program_batch if enrollment.program_batch_id else None
    return resolve_effective_curriculum_version(enrollment.program, batch=batch)


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

    owner_program_id = _curriculum_line_program_id(enrollment)
    total = ProgramCurriculumLine.objects.filter(
        curriculum_version=version,
        program_id=owner_program_id,
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
        curriculum_line__program_id=owner_program_id,
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


def year_fully_course_exempted(
    student: AdmittedStudent,
    *,
    year_of_study: int,
) -> bool:
    """
    True when every active curriculum paper in that academic year is exempted.

    Accounts rule: a fully exempted year has no semester tuition and no
    functional fees — the student is billed only per-paper EXEMPTION_COURSE
    charges for that year.
    """
    from Programs.models import ProgramCurriculumLine, StudentCurriculumOverride

    try:
        enrollment = student.programme_enrollment
    except Exception:
        return False

    version = _resolve_curriculum_version(enrollment)
    if version is None:
        return False

    owner_program_id = _curriculum_line_program_id(enrollment)
    total = ProgramCurriculumLine.objects.filter(
        curriculum_version=version,
        program_id=owner_program_id,
        year_of_study=year_of_study,
        is_active=True,
    ).count()
    if total <= 0:
        return False

    exempted = StudentCurriculumOverride.objects.filter(
        enrollment=enrollment,
        override_type="exempted",
        curriculum_line__curriculum_version=version,
        curriculum_line__program_id=owner_program_id,
        curriculum_line__year_of_study=year_of_study,
        curriculum_line__is_active=True,
    ).count()
    return exempted >= total


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

    If every paper in the year is exempted, callers should omit tuition and
    functional entirely (see year_fully_course_exempted). For a fully exempted
    term within a partial year, tuition becomes 0 here; functional is handled
    separately by the allocator.
    """
    if year_fully_course_exempted(student, year_of_study=year_of_study):
        counts = semester_paper_counts_for_exemptions(
            student, year_of_study=year_of_study, term_number=term_number
        )
        return Decimal("0.00"), counts

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
        program_id=_curriculum_line_program_id(enrollment),
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


def enrollment_promotion_context(student: AdmittedStudent) -> dict | None:
    """Current SPE position + programme year/term bounds for the HOD promote UI."""
    try:
        enrollment = student.programme_enrollment
    except Exception:
        return None
    if enrollment is None or enrollment.program_id is None:
        return None
    program = enrollment.program
    max_years = int(getattr(program, "max_years", None) or 4)
    max_terms = int(getattr(program, "max_terms_per_year", None) or 2)
    cur_year = int(enrollment.current_year_of_study or 1)
    cur_term = int(enrollment.current_term_number or 1)
    nxt = _next_year_term(
        cur_year, cur_term, max_terms_per_year=max_terms, max_years=max_years
    )
    return {
        "current_year_of_study": cur_year,
        "current_term_number": cur_term,
        "max_years": max_years,
        "max_terms_per_year": max_terms,
        "default_year_of_study": nxt[0] if nxt else cur_year,
        "default_term_number": nxt[1] if nxt else cur_term,
    }


def validate_advance_position(
    student: AdmittedStudent,
    *,
    to_year: int,
    to_term: int,
) -> None:
    """Raise ValueError if (to_year, to_term) is outside the programme range."""
    ctx = enrollment_promotion_context(student)
    if ctx is None:
        raise ValueError("Student has no programme enrollment to advance.")
    max_years = ctx["max_years"]
    max_terms = ctx["max_terms_per_year"]
    if to_year < 1 or to_year > max_years:
        raise ValueError(f"year_of_study must be between 1 and {max_years}.")
    if to_term < 1 or to_term > max_terms:
        raise ValueError(f"term_number must be between 1 and {max_terms}.")


def add_exemption_line_from_curriculum(
    change_request: AdmissionChangeRequest,
    *,
    curriculum_line_id: int,
    score_obtained: str = "",
    decided_by=None,
) -> "ExemptionRequestLine":
    """
    HOD adds a curriculum paper to an exemption request.

    Pending requests: line stays pending until review.
    Already-approved requests: line is auto-approved and curriculum override applied.
    """
    from admissions.models import ExemptionRequestLine
    from Programs.models import ProgramCurriculumLine

    if change_request.change_type != "exemption":
        raise ValueError("Only exemption requests accept additional papers.")
    if change_request.status == "rejected":
        raise ValueError("Cannot add papers to a rejected exemption request.")

    student = change_request.admitted_student
    curriculum = list_programme_curriculum_for_review(student)
    allowed_ids = {c["id"] for c in curriculum}
    if curriculum_line_id not in allowed_ids:
        raise ValueError("That curriculum unit is not on this student's programme.")

    if change_request.exemption_lines.filter(curriculum_line_id=curriculum_line_id).exists():
        raise ValueError("That paper is already on this exemption request.")

    cl = (
        ProgramCurriculumLine.objects.select_related("catalog_course")
        .filter(pk=curriculum_line_id, is_active=True)
        .first()
    )
    if cl is None:
        raise ValueError("Curriculum unit not found.")

    course = cl.catalog_course
    auto_approve = change_request.status == "approved"
    line = ExemptionRequestLine.objects.create(
        change_request=change_request,
        curriculum_line=cl,
        course_code=(course.code if course else "")[:40],
        course_name=((course.title if course else "") or "")[:255],
        year_of_study=cl.year_of_study,
        term_number=cl.term_number,
        score_obtained=(score_obtained or "").strip()[:20],
        decision=(
            ExemptionRequestLine.DECISION_APPROVED
            if auto_approve
            else ExemptionRequestLine.DECISION_PENDING
        ),
    )
    if auto_approve:
        apply_exemption_overrides(change_request, decided_by=decided_by)
    return line


def advance_student_position_for_exemption(
    change_request: AdmissionChangeRequest,
    *,
    to_year: int,
    to_term: int,
    decided_by,
) -> dict:
    """
    HOD-confirmed action: move the student's current curriculum position
    to (to_year, to_term) and record it as an advanced-entry point if this is the
    first time her position has moved past the default Year 1 Term 1.

    Student portal (My Courses / Enrolment / Academic Tracker) reads SPE
    current_year_of_study / current_term_number, so this change is visible there.
    """
    student = change_request.admitted_student
    validate_advance_position(student, to_year=to_year, to_term=to_term)
    try:
        enrollment = student.programme_enrollment
    except Exception as exc:
        raise ValueError("Student has no programme enrollment to advance.") from exc

    from_year, from_term = enrollment.current_year_of_study, enrollment.current_term_number
    if (int(to_year), int(to_term)) == (int(from_year), int(from_term)):
        raise ValueError("Student is already at that year/term.")

    update_fields = ["current_year_of_study", "current_term_number", "updated_at"]
    enrollment.current_year_of_study = to_year
    enrollment.current_term_number = to_term
    # Exemption advance = advanced standing: stamp entry so terms before the
    # new position do not keep full tuition/functional (those years are covered
    # by per-paper EXEMPTION_COURSE charges instead).
    entry_y = enrollment.entry_year_of_study
    entry_t = enrollment.entry_term_number
    try:
        entry_pair = (
            int(entry_y) if entry_y is not None else 1,
            int(entry_t) if entry_t is not None else 1,
        )
    except (TypeError, ValueError):
        entry_pair = (1, 1)
    if entry_pair <= (int(from_year), int(from_term)) or entry_pair < (int(to_year), int(to_term)):
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
