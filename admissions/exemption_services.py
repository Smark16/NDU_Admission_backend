"""Exemption change-request helpers: form fee gate + eligible curriculum lines."""
from __future__ import annotations

import time
from decimal import Decimal

from django.conf import settings
from django.db import OperationalError, transaction
from django.db.models import Q
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
# Up to three academic years = six terms (semesters). Professional / diploma
# credit may cover through Year 3; HOD confirms which papers apply.
MAX_EXEMPTION_YEARS = 3
MAX_EXEMPTION_TERMS = 6
# Catalogue shown in the student exemption picker (Years 1–3).
EXEMPTION_ELIGIBLE_YEARS = (1, 2, 3)
EXEMPTION_TERM_CAP_MESSAGE = (
    "Students may be exempted for at most 3 academic years (6 terms). "
    "Remove papers that fall in extra years or terms, or ask your HOD "
    "to adjust papers during review."
)
# One original application + one resubmit if HOD rejects. Form fee is not voided.
MAX_EXEMPTION_APPLICATION_ATTEMPTS = 2
# Kept for older clients; these gates are no longer enforced.
EXEMPTION_NOT_REGISTERED_CODE = "not_registered"
EXEMPTION_NOT_REGISTERED_MESSAGE = (
    "Course exemption is only for students who have been cleared for registration. "
    "Hostel-only clearance is not enough. Visit Accounts after paying your fees."
)
EXEMPTION_DOCS_NOT_VERIFIED_CODE = "docs_not_verified"
EXEMPTION_DOCS_NOT_VERIFIED_MESSAGE = (
    "Year 1 Semester 1 students must have original academic documents verified "
    "by Academic Registrar before applying for course exemption. "
    "Take your documents and ID to the AR desk."
)


class ExemptionNotEligible(ValueError):
    """Student cannot apply / pay / submit a course exemption yet."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def exemption_ineligibility(student: AdmittedStudent) -> tuple[str | None, str]:
    """
    Return (code, message) when the student cannot apply, else (None, "").

    Accounts clearance and AR document verification are not required.
    Anyone admitted may apply; the UGX 50,000 form fee is still required.
    The 60% paper rule is no longer required to open or submit.
    """
    _ = student
    return None, ""


def student_may_apply_course_exemption(student: AdmittedStudent) -> bool:
    """True when the student may open, pay, and submit a course exemption."""
    _ = student
    return True


def exemption_eligibility_payload(student: AdmittedStudent) -> dict:
    """Flags for student portal. Eligible is always true; 50k form fee still applies."""
    from admissions.registration_workflow import requires_physical_document_verification

    requires_docs = requires_physical_document_verification(student)
    return {
        "eligible": True,
        "ineligible_code": None,
        "ineligible_detail": "",
        "accounts_registration_cleared": bool(
            getattr(student, "accounts_registration_cleared", False)
        ),
        "requires_document_verification": requires_docs,
        "physical_documents_verified": bool(
            getattr(student, "physical_documents_verified", False)
        ),
    }


def assert_exemption_registration_required(student: AdmittedStudent) -> None:
    """No Accounts / AR gate. Kept so callers do not need to change."""
    _ = student
    return


def attach_exemption_eligibility(student: AdmittedStudent, payload: dict) -> dict:
    payload.update(exemption_eligibility_payload(student))
    return payload


UNPAID_RETURN_MARKER = "Returned unpaid exemption submission."
UNPAID_RETURN_MESSAGE = (
    "This exemption was returned because the UGX 50,000 form fee was not paid. "
    "Pay via the Course Exemption page (Exemption payments), then submit again."
)


def exemption_form_fee_settled_by_prompt(payment: StudentTuitionPayment | None) -> bool:
    """
    True only when the UGX 50k was collected via the exemption MoMo prompt.

    A completed EXEMPTION_FORM row with no payment_reference is usually tuition /
    SchoolPay-code credit allocated onto the bill — that is not an exemption payment.
    """
    if payment is None or getattr(payment, "is_waived", False):
        return False
    if getattr(payment, "status", None) != "completed":
        return False
    ref = (getattr(payment, "payment_reference", None) or "").strip()
    method = (getattr(payment, "payment_method", None) or "").strip()
    return bool(ref) or method == "mobile_money"


def prompt_paid_exemption_form_fee_qs():
    """Completed EXEMPTION_FORM charges that came from the MoMo / Adhoc prompt."""
    form_head, _ = ensure_exemption_fee_heads()
    return (
        StudentTuitionPayment.objects.filter(
            source="ad_hoc",
            fee_head=form_head,
            is_waived=False,
            status="completed",
        )
        .filter(
            Q(payment_method="mobile_money")
            | (~Q(payment_reference="") & ~Q(payment_reference=None))
        )
    )


def student_has_paid_exemption_form_fee(student: AdmittedStudent) -> bool:
    return form_fee_paid_for_charge(student, _open_form_fee_charge(student))


def exemption_submission_is_unpaid(change_request: AdmissionChangeRequest) -> bool:
    if getattr(change_request, "change_type", None) != "exemption":
        return False
    student = getattr(change_request, "admitted_student", None)
    if student is None:
        return True
    return not student_has_paid_exemption_form_fee(student)


def unpaid_exemption_submissions_qs():
    paid_ids = prompt_paid_exemption_form_fee_qs().values_list("student_id", flat=True)
    return (
        AdmissionChangeRequest.objects.filter(change_type="exemption")
        .exclude(admitted_student_id__in=paid_ids)
        .select_related(
            "admitted_student",
            "admitted_student__admitted_program",
            "admitted_student__application",
        )
        .prefetch_related("exemption_lines")
        .order_by("-created_at")
    )


def undo_exemption_curriculum_effects(change_request: AdmissionChangeRequest) -> dict:
    """Remove curriculum overrides and EXEMPTION_COURSE bills for this request."""
    from Programs.models import StudentCurriculumOverride

    student = change_request.admitted_student
    line_ids = [
        lid
        for lid in change_request.exemption_lines.values_list("curriculum_line_id", flat=True)
        if lid
    ]
    overrides_n = 0
    try:
        enrollment = student.programme_enrollment
    except Exception:
        enrollment = None
    if enrollment is not None and line_ids:
        qs = StudentCurriculumOverride.objects.filter(
            enrollment=enrollment,
            override_type="exempted",
            curriculum_line_id__in=line_ids,
        )
        overrides_n, _ = qs.delete()

    _, course_head = ensure_exemption_fee_heads()
    markers = [
        f"Exemption change request #{change_request.id}",
        f"change request #{change_request.id}",
    ]
    q = Q()
    for m in markers:
        q |= Q(notes__icontains=m)
    charges = StudentTuitionPayment.objects.filter(
        student=student,
        source="ad_hoc",
    ).filter(Q(fee_head=course_head) | Q(fee_head__code=EXEMPTION_COURSE_FEE_CODE)).filter(q)
    charges_n, _ = charges.delete()
    return {"overrides_removed": overrides_n, "course_charges_removed": charges_n}


def return_unpaid_exemption_submission(
    change_request: AdmissionChangeRequest,
    *,
    actor=None,
    undo_approved: bool = False,
) -> dict:
    """
    Take an unpaid exemption out of the HOD/Accounts queue.

    Pending: reject (does not use up a student attempt).
    Approved: only if undo_approved — reverse curriculum exemptions, then reject.
    """
    if change_request.change_type != "exemption":
        raise ValueError("Not an exemption request.")
    if not exemption_submission_is_unpaid(change_request):
        raise ValueError("This student has already paid the exemption form fee.")
    if change_request.status == "rejected":
        return {"id": change_request.id, "status": "rejected", "already_returned": True}
    if change_request.status == "approved" and not undo_approved:
        raise ValueError(
            "This exemption was already approved. Pass undo_approved to reverse "
            "curriculum exemptions and return it."
        )

    extras = {"overrides_removed": 0, "course_charges_removed": 0}
    if change_request.status == "approved":
        extras = undo_exemption_curriculum_effects(change_request)

    from admissions.models import ExemptionRequestLine

    change_request.status = "rejected"
    change_request.exemption_lines.update(decision=ExemptionRequestLine.DECISION_REJECTED)
    note = UNPAID_RETURN_MARKER + " " + UNPAID_RETURN_MESSAGE
    existing = (change_request.review_notes or "").strip()
    change_request.review_notes = f"{note}\n{existing}".strip() if existing else note
    change_request.reviewed_by = actor
    change_request.reviewed_at = timezone.now()
    change_request.save(
        update_fields=["status", "review_notes", "reviewed_by", "reviewed_at", "updated_at"]
        if hasattr(change_request, "updated_at")
        else ["status", "review_notes", "reviewed_by", "reviewed_at"]
    )
    return {
        "id": change_request.id,
        "status": "rejected",
        "already_returned": False,
        **extras,
    }


def exemption_application_attempt_state(student: AdmittedStudent) -> dict:
    """Students get one application, plus one more if HOD rejects. Fee stays paid."""
    qs = AdmissionChangeRequest.objects.filter(
        admitted_student=student, change_type="exemption"
    ).exclude(review_notes__startswith=UNPAID_RETURN_MARKER)
    pending = qs.filter(status="pending").exists()
    approved = qs.filter(status="approved").exists()
    total = qs.count()
    rejected_n = qs.filter(status="rejected").count()
    can_submit = (not pending) and (not approved) and total < MAX_EXEMPTION_APPLICATION_ATTEMPTS
    if pending:
        detail = "You already have a pending exemption application awaiting HOD review."
    elif approved:
        detail = "An exemption application was already approved for this student."
    elif total >= MAX_EXEMPTION_APPLICATION_ATTEMPTS:
        detail = (
            "Both exemption applications have been used (including one after a rejection). "
            "The form fee remains paid."
        )
    elif rejected_n:
        detail = (
            "The previous application was rejected. You may submit once more. "
            "The UGX 50,000 form fee is still valid — do not pay again."
        )
    else:
        detail = ""
    return {
        "can_submit": can_submit,
        "attempts_used": total,
        "attempts_max": MAX_EXEMPTION_APPLICATION_ATTEMPTS,
        "has_pending": pending,
        "has_approved": approved,
        "rejected_count": rejected_n,
        "detail": detail,
    }


def assert_exemption_resubmit_allowed(student: AdmittedStudent) -> None:
    state = exemption_application_attempt_state(student)
    if not state["can_submit"]:
        raise ValueError(state["detail"] or "You cannot submit another exemption application.")


def _term_key(year, term) -> tuple[int, int] | None:
    try:
        y = int(year)
        t = int(term)
    except (TypeError, ValueError):
        return None
    if y < 1 or t < 1:
        return None
    return (y, t)


def exemption_terms_already_committed(student: AdmittedStudent) -> set[tuple[int, int]]:
    """
    Distinct curriculum (year, term) already used by approved exemptions
    or by papers on a pending/approved request (not rejected).
    """
    from admissions.models import ExemptionRequestLine
    from Programs.models import StudentCurriculumOverride

    keys: set[tuple[int, int]] = set()
    try:
        enrollment = student.programme_enrollment
    except Exception:
        enrollment = None
    if enrollment is not None:
        for year, term in StudentCurriculumOverride.objects.filter(
            enrollment=enrollment,
            override_type="exempted",
        ).values_list("curriculum_line__year_of_study", "curriculum_line__term_number"):
            key = _term_key(year, term)
            if key:
                keys.add(key)

    for year, term in ExemptionRequestLine.objects.filter(
        change_request__admitted_student=student,
        change_request__change_type="exemption",
        change_request__status__in=("pending", "approved"),
    ).exclude(decision=ExemptionRequestLine.DECISION_REJECTED).values_list(
        "year_of_study", "term_number"
    ):
        key = _term_key(year, term)
        if key:
            keys.add(key)
    return keys


def exemption_term_cap_error(combined: set[tuple[int, int]]) -> str | None:
    years = {y for y, _t in combined}
    if len(combined) <= MAX_EXEMPTION_TERMS and len(years) <= MAX_EXEMPTION_YEARS:
        return None
    return (
        f"{EXEMPTION_TERM_CAP_MESSAGE} "
        f"This selection covers {len(years)} year(s) and {len(combined)} term(s)."
    )


def assert_exemption_term_cap(
    student: AdmittedStudent,
    extra_terms: set[tuple[int, int]] | None = None,
) -> None:
    combined = set(exemption_terms_already_committed(student))
    if extra_terms:
        combined |= {k for k in extra_terms if k}
    err = exemption_term_cap_error(combined)
    if err:
        raise ValueError(err)


def term_open_for_new_exemption(
    used: set[tuple[int, int]],
    year,
    term,
) -> bool:
    """True if a paper in this year/term can be added without breaking the 3-year / 6-term cap."""
    key = _term_key(year, term)
    if key is None:
        return True
    if key in used:
        return True
    years = {y for y, _t in used}
    if len(used) >= MAX_EXEMPTION_TERMS:
        return False
    if key[0] not in years and len(years) >= MAX_EXEMPTION_YEARS:
        return False
    return True


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
    """Min-mark gate retired — any recorded grade/score may be submitted."""
    _ = paper, min_percent
    return True, ""

# Per-paper flat rates (Option A): Ndejje alumnus vs external applicant.
EXEMPTION_COURSE_FEE_STANDARD_UGX = Decimal(
    str(getattr(settings, "EXEMPTION_COURSE_FEE_STANDARD_UGX", "150000"))
)
EXEMPTION_COURSE_FEE_ALUMNI_UGX = Decimal(
    str(getattr(settings, "EXEMPTION_COURSE_FEE_ALUMNI_UGX", "100000"))
)


def exemption_course_fee_rate(change_request: "AdmissionChangeRequest") -> Decimal | None:
    """Flat UGX rate per approved paper (alumni vs external)."""
    if getattr(change_request, "change_type", None) != "exemption":
        return None
    if change_request.exemption_is_alumnus:
        return EXEMPTION_COURSE_FEE_ALUMNI_UGX
    return EXEMPTION_COURSE_FEE_STANDARD_UGX


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
    year_of_study: int | None = None,
    term_number: int | None = None,
    change_request: "AdmissionChangeRequest | None" = None,
) -> Decimal:
    """
    Per approved paper: UGX 100,000 (Ndejje alumnus) or UGX 150,000 (external).
    When change_request is omitted, defaults to the standard external rate.
    """
    _ = student, year_of_study, term_number
    if change_request is not None:
        rate = exemption_course_fee_rate(change_request)
        if rate is not None:
            return rate
    return EXEMPTION_COURSE_FEE_STANDARD_UGX


def _billable_exemption_lines(change_request: "AdmissionChangeRequest"):
    from admissions.models import ExemptionRequestLine

    qs = change_request.exemption_lines.all()
    if change_request.ar_status == "approved":
        return list(
            qs.filter(
                decision=ExemptionRequestLine.DECISION_APPROVED,
                dean_decision=ExemptionRequestLine.DECISION_APPROVED,
                ar_decision=ExemptionRequestLine.DECISION_APPROVED,
            )
        )
    if change_request.status == "pending":
        return list(qs.filter(decision=ExemptionRequestLine.DECISION_APPROVED))
    return list(qs.filter(decision=ExemptionRequestLine.DECISION_APPROVED))


def exemption_billing_lines_for_request(
    change_request: "AdmissionChangeRequest",
) -> list[dict]:
    """
    Per approved (or pending-estimate) paper: flat alumni/external rate,
    plus resolved semester metadata when available.
    """
    from payments.billing_visibility import resolve_semester_for_year_term
    from payments.student_portal_finance import _student_program_batch_id

    student = change_request.admitted_student
    pb_id = _student_program_batch_id(student)
    paper_rate = exemption_course_fee_rate(change_request) or EXEMPTION_COURSE_FEE_STANDARD_UGX
    out: list[dict] = []
    for line in _billable_exemption_lines(change_request):
        year = line.year_of_study
        term = line.term_number
        if (year is None or term is None) and line.curriculum_line_id:
            cl = line.curriculum_line
            if cl is not None:
                year = cl.year_of_study
                term = cl.term_number
        amount = paper_rate
        error = None
        semester = None
        if year is not None and term is not None:
            semester = resolve_semester_for_year_term(
                program_batch_id=pb_id,
                year_of_study=int(year),
                term_number=int(term),
            )
        elif line.curriculum_line_id is None:
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
                "amount": float(amount),
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
    qs = StudentTuitionPayment.objects.filter(
        student=student,
        source="ad_hoc",
        fee_head=form_head,
        is_waived=False,
        status__in=("pending", "completed"),
    )
    completed = qs.filter(status="completed").order_by("-paid_at", "-created_at").first()
    if completed and exemption_form_fee_settled_by_prompt(completed):
        extras = qs.filter(status="pending").exclude(pk=completed.pk)
        if extras.exists():
            extras.update(
                status="cancelled",
                notes=(
                    "Cancelled: exemption form fee already paid on an earlier charge."
                ),
            )
        return completed
    if completed and not exemption_form_fee_settled_by_prompt(completed):
        # Tuition/SchoolPay-code credit marked this 50k complete. It is not a
        # real exemption payment — keep using the row as an open bill.
        pending_existing = qs.filter(status="pending").order_by("-created_at").first()
        if pending_existing:
            return pending_existing
        return completed

    pending = qs.filter(status="pending").order_by("-created_at").first()
    if pending and (pending.payment_reference or "").strip():
        try:
            from payments.utils.tuition_payment_status import reconcile_pending_tuition_payment

            reconcile_pending_tuition_payment(pending)
            pending.refresh_from_db()
        except Exception:
            pass
        if pending.status == "completed":
            return pending
    return pending


def form_fee_paid_for_charge(student: AdmittedStudent, charge: StudentTuitionPayment | None) -> bool:
    """Unlock only after the exemption MoMo prompt (not SchoolPay student-code tuition)."""
    if prompt_paid_exemption_form_fee_qs().filter(student=student).exists():
        return True
    return exemption_form_fee_settled_by_prompt(charge)


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
        return attach_exemption_eligibility(
            student,
            {
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
                    f"Pay UGX {int(EXEMPTION_FORM_FEE_UGX):,} with the mobile money prompt on "
                    "the Course Exemption page. Paying your SchoolPay student code in the app "
                    "does not unlock submit."
                ),
                "attempts": exemption_application_attempt_state(student),
            },
        )

    paid = form_fee_paid_for_charge(student, charge)
    if not paid:
        try:
            build_finance_allocation(student)
            charge.refresh_from_db()
            paid = form_fee_paid_for_charge(student, charge)
        except Exception:
            pass

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
        try:
            alloc = build_finance_allocation(student)
            for line in alloc.demand_lines:
                if line.kind == "ad_hoc" and line.charge_id == charge.id:
                    balance = line.balance
                    break
        except Exception:
            pass

    return attach_exemption_eligibility(
        student,
        {
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
                "payment prompt on your phone. Do not pay this fee with a SchoolPay student code."
            ),
            "attempts": exemption_application_attempt_state(student),
        },
    )


def exemption_form_fee_status(student: AdmittedStudent) -> dict:
    """Report existing form-fee charge without creating one."""
    return _form_fee_status_dict(student, _open_form_fee_charge(student))


def ensure_exemption_form_fee_access(student: AdmittedStudent, *, charged_by=None) -> dict:
    """
    Ensure a 50k form-fee charge exists (creates if missing) and report status.
    Used when the student starts MoMo pay, not on mere page load.
    """
    if not student_may_apply_course_exemption(student):
        return _form_fee_status_dict(student, _open_form_fee_charge(student))
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

    status_filter: 'pending' (unpaid), 'completed' (paid),
    'paid_unsubmitted' (paid, no exemption request yet), or None for all.
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
    elif status_filter == "paid_unsubmitted":
        qs = qs.filter(status="completed", is_waived=False)

    charges = list(qs)
    charge_ids = [c.id for c in charges]
    student_pks = [c.student_id for c in charges if c.student_id]

    requests_by_charge = {}
    latest_req_by_student: dict[int, AdmissionChangeRequest] = {}
    if charge_ids or student_pks:
        req_filter = Q()
        if charge_ids:
            req_filter |= Q(form_fee_charge_id__in=charge_ids)
        if student_pks:
            req_filter |= Q(admitted_student_id__in=student_pks)
        req_qs = AdmissionChangeRequest.objects.filter(change_type="exemption").filter(req_filter).order_by(
            "created_at"
        )
        for r in req_qs:
            if r.form_fee_charge_id:
                requests_by_charge[r.form_fee_charge_id] = r
            if r.admitted_student_id:
                latest_req_by_student[r.admitted_student_id] = r

    now = timezone.now()
    rows = []
    for charge in charges:
        student = charge.student
        req = requests_by_charge.get(charge.id)
        if req is None and student:
            req = latest_req_by_student.get(student.pk)
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
                "has_draft": False,
                "draft_paper_count": 0,
                "draft_updated_at": None,
                "form_ready": False,
            }
        )

    student_ids = [r["student_pk"] for r in rows if r.get("student_pk")]
    drafts = {
        s.pk: s
        for s in AdmittedStudent.objects.filter(pk__in=student_ids).only(
            "id", "exemption_form_draft", "exemption_form_draft_updated_at"
        )
    }
    for row in rows:
        student = drafts.get(row.get("student_pk"))
        summary = exemption_draft_summary(student.exemption_form_draft if student else None)
        row["has_draft"] = summary["has_draft"]
        row["draft_paper_count"] = summary["paper_count"]
        row["draft_updated_at"] = (
            student.exemption_form_draft_updated_at.isoformat()
            if student and student.exemption_form_draft_updated_at
            else None
        )
        row["form_ready"] = bool(
            summary["ready"]
            and row.get("status") == "completed"
            and not row.get("change_request_id")
        )
    if status_filter == "paid_unsubmitted":
        rows = [
            r
            for r in rows
            if r.get("status") == "completed"
            and not r.get("is_waived")
            and not r.get("change_request_id")
        ]
    return rows


def _compose_draft_score(paper: dict) -> str:
    grade = str(paper.get("grade_letter") or "").strip()
    mark = str(paper.get("mark_percent") or "").strip()
    if grade and mark:
        return f"{grade} ({mark})"
    return grade or mark or str(paper.get("score_obtained") or "").strip()


def sanitize_exemption_draft(payload: dict | None) -> dict:
    data = payload if isinstance(payload, dict) else {}
    papers_in = data.get("papers") if isinstance(data.get("papers"), list) else []
    papers = []
    for raw in papers_in[:40]:
        if not isinstance(raw, dict):
            continue
        clid = raw.get("curriculum_line_id")
        try:
            clid_int = int(clid) if clid not in (None, "", 0, "0") else None
        except (TypeError, ValueError):
            clid_int = None
        papers.append(
            {
                "course_code": str(raw.get("course_code") or "")[:40],
                "course_name": str(raw.get("course_name") or "")[:255],
                "year_of_study": str(raw.get("year_of_study") or "")[:8],
                "term_number": str(raw.get("term_number") or "")[:8],
                "curriculum_line_id": clid_int,
                "grade_letter": str(raw.get("grade_letter") or "")[:12],
                "mark_percent": str(raw.get("mark_percent") or "")[:20],
                "prior_unit_note": str(raw.get("prior_unit_note") or "")[:255],
                "score_obtained": _compose_draft_score(raw)[:40],
            }
        )
    return {
        "attainedAt": str(data.get("attainedAt") or data.get("exemption_attained_at") or "")[:255],
        "academicYears": str(data.get("academicYears") or data.get("exemption_academic_years") or "")[:50],
        "reason": str(data.get("reason") or "")[:4000],
        "phoneNumber": str(data.get("phoneNumber") or "")[:30],
        "papers": papers,
        "savedAt": timezone.now().isoformat(),
    }


def align_exemption_draft_to_curriculum(student: AdmittedStudent, draft: dict | None) -> dict:
    """Keep only papers that exist on this student's programme.

    Stale browser drafts (and leftover server JSON) can carry another
    programme's curriculum_line_id / course codes — e.g. engineering units
    on a non-engineering student.
    """
    cleaned = sanitize_exemption_draft(draft)
    curriculum = list_programme_curriculum_for_review(student)
    by_id = {int(c["id"]): c for c in curriculum if c.get("id") is not None}
    by_code = {}
    for c in curriculum:
        key = _norm_course_code(c.get("course_code") or "")
        if key and key not in by_code:
            by_code[key] = c
    kept = []
    seen = set()
    for paper in cleaned.get("papers") or []:
        row = None
        raw_id = paper.get("curriculum_line_id")
        if raw_id not in (None, "", 0, "0"):
            try:
                row = by_id.get(int(raw_id))
            except (TypeError, ValueError):
                row = None
        if row is None:
            row = by_code.get(_norm_course_code(paper.get("course_code") or ""))
        if row is None:
            continue
        clid = int(row["id"])
        if clid in seen:
            continue
        seen.add(clid)
        kept.append(
            {
                **paper,
                "curriculum_line_id": clid,
                "course_code": row.get("course_code") or paper.get("course_code") or "",
                "course_name": row.get("course_name") or paper.get("course_name") or "",
                "year_of_study": str(row.get("year_of_study") or paper.get("year_of_study") or ""),
                "term_number": str(row.get("term_number") or paper.get("term_number") or ""),
            }
        )
    cleaned["papers"] = kept
    return cleaned


def exemption_draft_summary_for_student(student: AdmittedStudent) -> dict:
    aligned = align_exemption_draft_to_curriculum(student, student.exemption_form_draft)
    stored = sanitize_exemption_draft(student.exemption_form_draft or {})
    if aligned.get("papers") != stored.get("papers"):
        student.exemption_form_draft = aligned
        student.exemption_form_draft_updated_at = timezone.now()
        student.save(
            update_fields=["exemption_form_draft", "exemption_form_draft_updated_at", "updated_at"]
        )
    return exemption_draft_summary(aligned)


def exemption_draft_summary(draft: dict | None) -> dict:
    data = sanitize_exemption_draft(draft) if draft else {"papers": [], "attainedAt": "", "reason": ""}
    selected = [p for p in data.get("papers") or [] if p.get("curriculum_line_id")]
    ready = bool(
        selected
        and all(str(p.get("grade_letter") or "").strip() for p in selected)
        and str(data.get("attainedAt") or "").strip()
        and str(data.get("reason") or "").strip()
    )
    return {
        "has_draft": bool(selected or str(data.get("reason") or "").strip() or str(data.get("attainedAt") or "").strip()),
        "paper_count": len(selected),
        "ready": ready,
        "draft": data if draft else None,
    }


def save_exemption_draft(student: AdmittedStudent, payload: dict | None) -> dict:
    cleaned = align_exemption_draft_to_curriculum(student, payload)
    student.exemption_form_draft = cleaned
    student.exemption_form_draft_updated_at = timezone.now()
    student.save(update_fields=["exemption_form_draft", "exemption_form_draft_updated_at", "updated_at"])
    return exemption_draft_summary(cleaned)


def clear_exemption_draft(student: AdmittedStudent) -> None:
    if not student.exemption_form_draft and not student.exemption_form_draft_updated_at:
        return
    student.exemption_form_draft = None
    student.exemption_form_draft_updated_at = None
    student.save(update_fields=["exemption_form_draft", "exemption_form_draft_updated_at", "updated_at"])


def submit_exemption_from_draft(student: AdmittedStudent, *, requested_by, staff_submit: bool = False):
    """
    Create a pending exemption change request from the saved draft.
    Staff submit is allowed without uploaded files (desk help after the 50k is paid).
    """
    from admissions.models import ExemptionRequestLine
    from Programs.models import ProgramCurriculumLine

    if AdmissionChangeRequest.objects.filter(
        admitted_student=student, change_type="exemption", status="pending"
    ).exists():
        raise ValueError("This student already has a pending exemption application.")

    assert_exemption_registration_required(student)
    assert_exemption_resubmit_allowed(student)

    access = exemption_form_fee_status(student)
    if not access.get("paid"):
        raise ValueError("The UGX 50,000 exemption form fee is not paid yet.")

    summary = exemption_draft_summary_for_student(student)
    draft = summary.get("draft") or {}
    if not summary.get("ready"):
        raise ValueError(
            "The form is not complete yet. The student needs papers with grades, "
            "the prior institution, and a reason."
        )

    papers = [p for p in (draft.get("papers") or []) if p.get("curriculum_line_id")]
    eligible_list = list_eligible_exemption_courses(student)
    eligible = {c["id"]: c for c in eligible_list}
    eligible_by_code = {}
    for c in eligible_list:
        key = _norm_course_code(c.get("course_code") or "")
        if key and key not in eligible_by_code:
            eligible_by_code[key] = c
    extra_terms = set()
    exemption_papers = []
    seen_lines = set()
    for paper in papers:
        try:
            clid = int(paper["curriculum_line_id"])
        except (TypeError, ValueError):
            continue
        row = eligible.get(clid)
        if row is None:
            row = eligible_by_code.get(_norm_course_code(paper.get("course_code") or ""))
            if row is None:
                raise ValueError(
                    f"Paper {paper.get('course_code') or clid} is not eligible for exemption."
                )
            clid = int(row["id"])
            paper = {**paper, "curriculum_line_id": clid}
        if clid in seen_lines:
            continue
        seen_lines.add(clid)
        key = _term_key(row.get("year_of_study"), row.get("term_number"))
        if key:
            extra_terms.add(key)
        score = _compose_draft_score(paper)
        check_paper = {
            "course_code": paper.get("course_code"),
            "score_obtained": score,
            "min_mark": paper.get("mark_percent"),
        }
        ok, msg = exemption_paper_meets_min_mark(check_paper)
        if not ok:
            raise ValueError(msg)
        exemption_papers.append({**paper, "score_obtained": score, "curriculum_line_id": clid})

    assert_exemption_term_cap(student, extra_terms)

    prior_notes = [
        f"{p.get('course_code')}: {p.get('prior_unit_note')}".strip()
        for p in exemption_papers
        if str(p.get("prior_unit_note") or "").strip()
    ]
    reason = str(draft.get("reason") or "").strip()
    if prior_notes:
        reason = (
            reason
            + "\n\nEquivalent units at previous institution:\n"
            + "\n".join(f"- {n}" for n in prior_notes)
        )
    if staff_submit:
        who = getattr(requested_by, "get_full_name", lambda: "")() or getattr(requested_by, "username", "")
        reason = (
            reason
            + f"\n\n[Submitted by staff ({who}) from the saved form. "
            "No files were attached on the draft — ask the student for transcript/certificate if missing.]"
        )

    with transaction.atomic():
        obj = AdmissionChangeRequest.objects.create(
            admitted_student=student,
            requested_by=requested_by,
            current_program=student.admitted_program,
            current_campus=student.admitted_campus,
            current_study_mode=student.study_mode,
            change_type="exemption",
            reason=reason[:8000],
            form_fee_charge_id=access.get("charge_id"),
            form_fee_paid_at=timezone.now() if access.get("paid") else None,
            exemption_attained_at=str(draft.get("attainedAt") or "")[:255],
            exemption_academic_years=str(draft.get("academicYears") or "")[:50],
        )
        for paper in exemption_papers:
            clid = int(paper["curriculum_line_id"])
            linked = (
                ProgramCurriculumLine.objects.filter(pk=clid, is_active=True)
                .select_related("catalog_course")
                .first()
            )
            if linked is None:
                continue
            course = linked.catalog_course
            ExemptionRequestLine.objects.create(
                change_request=obj,
                curriculum_line=linked,
                course_code=(course.code if course else "")[:40],
                course_name=((course.title if course else "") or "")[:255],
                year_of_study=linked.year_of_study,
                term_number=linked.term_number,
                score_obtained=str(paper.get("score_obtained") or "")[:20],
            )
        clear_exemption_draft(student)
    return obj, access


def _norm_course_code(code: str) -> str:
    """Normalize course codes for fuzzy matching (ignore spaces/punctuation/case)."""
    import re

    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def _student_curriculum_program(student: AdmittedStudent):
    """Programme row to read curriculum from (enrollment first, else admission)."""
    try:
        enrollment = student.programme_enrollment
    except Exception:
        enrollment = None
    if enrollment is not None and getattr(enrollment, "program_id", None):
        return enrollment, enrollment.program
    return enrollment, getattr(student, "admitted_program", None)


def is_exemption_eligible_year(year_of_study) -> bool:
    """True when a curriculum line may appear on the student exemption picker."""
    try:
        return int(year_of_study) in EXEMPTION_ELIGIBLE_YEARS
    except (TypeError, ValueError):
        return False


def _resolve_enrollment_curriculum_version(student: AdmittedStudent):
    """
    Return (enrollment, effective_curriculum_version).

    Inherited campus programmes often still pin an empty local "Default
    curriculum" version on the enrollment; real lines live on the master
    programme. Prefer a version that actually has active units so exemption
    forms are not empty when the cohort version and default version differ.

    Students without a programme enrollment still get the admission
    programme's curriculum so the picker is not blank during QA.
    """
    from Programs.curriculum_inheritance import (
        ensure_enrollment_curriculum_version,
        resolve_curriculum_version_with_lines,
    )

    enrollment, program = _student_curriculum_program(student)
    if program is None:
        return enrollment, None

    if enrollment is not None:
        version = ensure_enrollment_curriculum_version(enrollment)
        return enrollment, version

    version = resolve_curriculum_version_with_lines(program, batch=None, pinned=None)
    return enrollment, version


def _active_curriculum_lines_qs(student: AdmittedStudent, version):
    """Active curriculum lines for exemption pickers, with version fallback."""
    from Programs.curriculum_inheritance import curriculum_owner_program
    from Programs.models import ProgramCurriculumLine

    enrollment, program = _student_curriculum_program(student)
    owner = curriculum_owner_program(program) if program else None
    owner_program_id = owner.pk if owner else (program.pk if program else None)

    def _scoped(qs):
        if not owner_program_id:
            return qs
        scoped = qs.filter(program_id=owner_program_id)
        return scoped if scoped.exists() else qs

    lines_qs = ProgramCurriculumLine.objects.none()
    if version is not None:
        lines_qs = _scoped(
            ProgramCurriculumLine.objects.filter(
                curriculum_version=version,
                is_active=True,
            )
        )
    if lines_qs.exists():
        return lines_qs.select_related("catalog_course")

    if owner is None and program is None:
        return lines_qs.select_related("catalog_course")

    owner_or_program = owner or program
    fallback = _scoped(
        ProgramCurriculumLine.objects.filter(
            curriculum_version__program=owner_or_program,
            is_active=True,
        )
    )
    if not fallback.exists():
        fallback = ProgramCurriculumLine.objects.filter(
            program_id=owner_or_program.pk,
            is_active=True,
        )
    return fallback.select_related("catalog_course")


def _curriculum_line_program_id(enrollment) -> int | None:
    """Programme id that owns curriculum lines for this enrollment."""
    from Programs.curriculum_inheritance import curriculum_owner_program

    owner = curriculum_owner_program(enrollment.program)
    return owner.pk if owner else enrollment.program_id


def list_eligible_exemption_courses(student: AdmittedStudent) -> list[dict]:
    """Curriculum lines for the student's pinned/default version, excluding existing exemptions."""
    from Programs.models import StudentCurriculumOverride

    enrollment, version = _resolve_enrollment_curriculum_version(student)
    existing = set()
    if enrollment is not None:
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

    used_terms = exemption_terms_already_committed(student)
    lines = (
        _active_curriculum_lines_qs(student, version)
        .filter(year_of_study__in=EXEMPTION_ELIGIBLE_YEARS)
        .order_by("year_of_study", "term_number", "sort_order", "catalog_course__code")
    )
    out = []
    for line in lines:
        if line.id in existing:
            continue
        if not is_exemption_eligible_year(line.year_of_study):
            continue
        if not term_open_for_new_exemption(used_terms, line.year_of_study, line.term_number):
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
    from Programs.models import StudentCurriculumOverride

    enrollment, version = _resolve_enrollment_curriculum_version(student)
    existing = set()
    if enrollment is not None:
        existing = set(
            StudentCurriculumOverride.objects.filter(
                enrollment=enrollment,
                override_type__in=("exempted", "transferred"),
            ).values_list("curriculum_line_id", flat=True)
        )

    lines = _active_curriculum_lines_qs(student, version).order_by(
        "year_of_study", "term_number", "sort_order", "catalog_course__code"
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


def apply_line_decisions(
    change_request: AdmissionChangeRequest,
    decisions: list[dict],
    *,
    stage: str = "hod",
) -> None:
    """
    Record per-paper approve/reject at HOD, Dean, or AR stage.
    decisions: [{exemption_line_id, decision, decision_note?, curriculum_line_id?}]
    """
    from admissions.models import ExemptionRequestLine
    from Programs.models import ProgramCurriculumLine

    stage = (stage or "hod").strip().lower()
    if stage not in ("hod", "dean", "ar"):
        raise ValueError('stage must be "hod", "dean", or "ar".')

    if not decisions:
        raise ValueError("Provide a decision (approve or reject) for each paper.")

    by_id = {line.id: line for line in change_request.exemption_lines.all()}
    if not by_id:
        raise ValueError("This exemption request has no course papers.")

    if stage == "dean":
        eligible = {
            lid: line
            for lid, line in by_id.items()
            if line.decision == ExemptionRequestLine.DECISION_APPROVED
        }
    elif stage == "ar":
        eligible = {
            lid: line
            for lid, line in by_id.items()
            if line.decision == ExemptionRequestLine.DECISION_APPROVED
            and line.dean_decision == ExemptionRequestLine.DECISION_APPROVED
        }
    else:
        eligible = by_id

    if not eligible:
        raise ValueError("No papers are eligible for review at this stage.")

    seen: set[int] = set()
    curriculum_ids = {
        int(d["curriculum_line_id"])
        for d in decisions
        if stage == "hod" and d.get("curriculum_line_id") not in (None, "", 0, "0")
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
        line = eligible.get(eid)
        if line is None:
            if eid in by_id:
                raise ValueError(
                    f"Paper {by_id[eid].course_code or eid} is not eligible at the {stage.upper()} stage."
                )
            raise ValueError(f"Unknown exemption line {eid} on this request.")
        if eid in seen:
            raise ValueError(f"Duplicate decision for paper {line.course_code or eid}.")
        seen.add(eid)

        decision = str(raw.get("decision") or "").strip().lower()
        if decision in ("approve", "approved"):
            decision_val = ExemptionRequestLine.DECISION_APPROVED
        elif decision in ("reject", "rejected"):
            decision_val = ExemptionRequestLine.DECISION_REJECTED
        else:
            raise ValueError(
                f"Decision for {line.course_code or eid} must be approve or reject."
            )

        note = str(raw.get("decision_note") or "").strip()[:255]

        if stage == "hod":
            update_fields = ["decision", "decision_note"]
            if decision_val == ExemptionRequestLine.DECISION_APPROVED:
                cid_raw = raw.get("curriculum_line_id") or line.curriculum_line_id
                try:
                    cid = int(cid_raw)
                except (TypeError, ValueError):
                    raise ValueError(
                        f"Match {line.course_code or eid} to a curriculum unit before approving it."
                    )
                curriculum = curriculum_map.get(cid) or (
                    ProgramCurriculumLine.objects.select_related("catalog_course")
                    .filter(pk=cid)
                    .first()
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
            line.decision = decision_val
            line.save(update_fields=update_fields)
        elif stage == "dean":
            line.dean_decision = decision_val
            line.dean_decision_note = note or line.dean_decision_note
            line.save(update_fields=["dean_decision", "dean_decision_note"])
            if decision_val == ExemptionRequestLine.DECISION_REJECTED:
                revoke_exemption_override_for_line(line)
        else:
            line.ar_decision = decision_val
            line.ar_decision_note = note or line.ar_decision_note
            line.save(update_fields=["ar_decision", "ar_decision_note"])
            if decision_val == ExemptionRequestLine.DECISION_REJECTED:
                revoke_exemption_override_for_line(line)

    undecided = [l for lid, l in eligible.items() if lid not in seen]
    if undecided:
        codes = ", ".join((l.course_code or f"#{l.id}") for l in undecided[:8])
        raise ValueError(
            f"Decide every eligible paper at {stage.upper()} (approve or reject). Still pending: {codes}."
        )

    sync_exemption_request_stages_from_lines(change_request)


def revoke_exemption_override_for_line(line) -> None:
    """Remove curriculum exemption when a paper is rejected after effects were applied."""
    change_request = line.change_request
    if not exemption_effects_applied(change_request):
        return
    from Programs.models import StudentCurriculumOverride

    if not line.curriculum_line_id:
        return
    try:
        enrollment = line.change_request.admitted_student.programme_enrollment
    except Exception:
        return
    if enrollment is None:
        return
    StudentCurriculumOverride.objects.filter(
        enrollment=enrollment,
        curriculum_line_id=line.curriculum_line_id,
        override_type="exempted",
    ).delete()


def sync_exemption_request_stages_from_lines(change_request: AdmissionChangeRequest) -> None:
    """Derive HOD / Dean / AR request status from per-paper decisions."""
    from admissions.exemption_stages import (
        compute_exemption_pipeline_from_lines,
        sync_exemption_overall_status,
    )

    lines = list(change_request.exemption_lines.all())
    if not lines:
        return

    hod, dean, ar = compute_exemption_pipeline_from_lines(lines)
    change_request.hod_status = hod
    change_request.dean_status = dean
    change_request.ar_status = ar
    sync_exemption_overall_status(change_request)


def ensure_exemption_request_stages_synced(
    change_request: AdmissionChangeRequest,
    *,
    save: bool = True,
) -> bool:
    """Align stored request-level stage fields with line decisions; persist if changed."""
    lines = list(change_request.exemption_lines.all())
    if not lines:
        return False

    before = (
        change_request.hod_status,
        change_request.dean_status,
        change_request.ar_status,
        change_request.status,
    )
    sync_exemption_request_stages_from_lines(change_request)
    after = (
        change_request.hod_status,
        change_request.dean_status,
        change_request.ar_status,
        change_request.status,
    )
    if after == before:
        return False
    if save:
        change_request.save(
            update_fields=["hod_status", "dean_status", "ar_status", "status"]
        )
    return True


def apply_exemption_overrides(change_request: AdmissionChangeRequest, decided_by) -> int:
    """Create exempted StudentCurriculumOverride rows for fully approved papers only."""
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

    approved = ExemptionRequestLine.DECISION_APPROVED
    lines = list(
        change_request.exemption_lines.select_related("curriculum_line").filter(
            decision=approved,
            dean_decision=approved,
            ar_decision=approved,
        )
    )
    if not lines:
        # All papers rejected — valid outcome; no curriculum overrides.
        return 0

    extra = set()
    for line in lines:
        key = _term_key(line.year_of_study, line.term_number)
        if key is None and line.curriculum_line_id:
            cl = line.curriculum_line
            key = _term_key(
                getattr(cl, "year_of_study", None),
                getattr(cl, "term_number", None),
            )
        if key:
            extra.add(key)
    assert_exemption_term_cap(student, extra)

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


def exemption_ready_for_hod_promotion(change_request: AdmissionChangeRequest) -> bool:
    """True when HOD has approved at least one paper and effects are not yet applied."""
    from admissions.models import ExemptionRequestLine

    if change_request.change_type != "exemption":
        return False
    if change_request.exemption_effects_applied_at:
        return False
    if change_request.hod_status != "approved":
        return False
    return change_request.exemption_lines.filter(
        decision=ExemptionRequestLine.DECISION_APPROVED,
    ).exists()


def exemption_effects_applied(change_request: AdmissionChangeRequest) -> bool:
    return bool(getattr(change_request, "exemption_effects_applied_at", None))


def exemption_stage_can_reopen(change_request: AdmissionChangeRequest, stage: str) -> tuple[bool, str]:
    """
    Whether HOD / Dean / AR can undo their own stage decisions.

    Only allowed before the next pipeline stage has acted, and before AR
    final effects (curriculum + promotion) are applied.
    """
    stage = (stage or "").strip().lower()
    if change_request.change_type != "exemption":
        return False, "Not an exemption request."
    if exemption_effects_applied(change_request):
        return False, (
            "Curriculum exemptions and promotion already applied after AR approval. "
            "Contact Academic Registry / system admin to reverse effects."
        )
    if change_request.accounts_status in ("billed", "confirmed"):
        return False, "Accounts has already billed this exemption — cannot reopen earlier stages."

    lines = list(change_request.exemption_lines.all())
    if not lines:
        return False, "This exemption request has no papers."

    from admissions.models import ExemptionRequestLine

    pending = ExemptionRequestLine.DECISION_PENDING

    if stage == "hod":
        if change_request.hod_status == "pending" and all(
            (l.decision or pending) == pending for l in lines
        ):
            return False, "HOD has not submitted decisions yet."
        if change_request.dean_status != "pending":
            return False, "Dean has already reviewed — ask Dean to undo first, or contact AR."
        if any((l.dean_decision or pending) != pending for l in lines):
            return False, "Dean has already decided on one or more papers."
        if change_request.ar_status != "pending":
            return False, "AR has already reviewed this request."
        return True, ""

    if stage == "dean":
        if change_request.hod_status != "approved":
            return False, "HOD must approve papers before Dean review can be undone."
        if change_request.dean_status == "pending" and all(
            (l.dean_decision or pending) == pending
            for l in lines
            if l.decision == ExemptionRequestLine.DECISION_APPROVED
        ):
            return False, "Dean has not submitted decisions yet."
        if change_request.ar_status != "pending":
            return False, "AR has already reviewed — ask AR to undo first, or contact registry."
        if any(
            (l.ar_decision or pending) != pending
            for l in lines
            if l.dean_decision == ExemptionRequestLine.DECISION_APPROVED
        ):
            return False, "AR has already decided on one or more papers."
        return True, ""

    if stage == "ar":
        if change_request.dean_status != "approved":
            return False, "Dean must approve papers before AR review can be undone."
        if change_request.ar_status == "pending" and all(
            (l.ar_decision or pending) == pending
            for l in lines
            if (
                l.decision == ExemptionRequestLine.DECISION_APPROVED
                and l.dean_decision == ExemptionRequestLine.DECISION_APPROVED
            )
        ):
            return False, "AR has not submitted decisions yet."
        return True, ""

    return False, 'stage must be "hod", "dean", or "ar".'


def reopen_exemption_stage_review(
    change_request: AdmissionChangeRequest,
    *,
    stage: str,
    actor=None,
    reason: str = "",
) -> dict:
    """
    Undo HOD / Dean / AR paper decisions so they can correct a mistake.

    Keeps curriculum unit matches on papers. Clears a pending promotion proposal
    when HOD reopens (promotion was based on HOD-approved papers).
    """
    from admissions.models import ExemptionRequestLine

    stage = (stage or "").strip().lower()
    ok, detail = exemption_stage_can_reopen(change_request, stage)
    if not ok:
        raise ValueError(detail)

    pending = ExemptionRequestLine.DECISION_PENDING
    lines = list(change_request.exemption_lines.all())
    reset_n = 0

    for line in lines:
        update_fields: list[str] = []
        if stage == "hod":
            if line.decision != pending or line.dean_decision != pending or line.ar_decision != pending:
                line.decision = pending
                line.decision_note = ""
                line.dean_decision = pending
                line.dean_decision_note = ""
                line.ar_decision = pending
                line.ar_decision_note = ""
                update_fields = [
                    "decision",
                    "decision_note",
                    "dean_decision",
                    "dean_decision_note",
                    "ar_decision",
                    "ar_decision_note",
                ]
        elif stage == "dean":
            if line.decision != ExemptionRequestLine.DECISION_APPROVED:
                continue
            if line.dean_decision != pending or line.ar_decision != pending:
                line.dean_decision = pending
                line.dean_decision_note = ""
                line.ar_decision = pending
                line.ar_decision_note = ""
                update_fields = [
                    "dean_decision",
                    "dean_decision_note",
                    "ar_decision",
                    "ar_decision_note",
                ]
        else:  # ar
            if (
                line.decision != ExemptionRequestLine.DECISION_APPROVED
                or line.dean_decision != ExemptionRequestLine.DECISION_APPROVED
            ):
                continue
            if line.ar_decision != pending:
                line.ar_decision = pending
                line.ar_decision_note = ""
                update_fields = ["ar_decision", "ar_decision_note"]
        if update_fields:
            line.save(update_fields=update_fields)
            reset_n += 1

    sync_exemption_request_stages_from_lines(change_request)

    cleared_promotion = False
    update_fields = ["hod_status", "dean_status", "ar_status", "status", "updated_at"]
    if stage == "hod":
        change_request.hod_reviewed_by = None
        change_request.hod_reviewed_at = None
        change_request.hod_notes = ""
        update_fields += ["hod_reviewed_by", "hod_reviewed_at", "hod_notes"]
        if (
            change_request.exemption_promotion_year is not None
            or change_request.exemption_promotion_term is not None
        ):
            change_request.exemption_promotion_year = None
            change_request.exemption_promotion_term = None
            change_request.exemption_promotion_by = None
            change_request.exemption_promotion_at = None
            update_fields += [
                "exemption_promotion_year",
                "exemption_promotion_term",
                "exemption_promotion_by",
                "exemption_promotion_at",
            ]
            cleared_promotion = True
    elif stage == "dean":
        change_request.dean_reviewed_by = None
        change_request.dean_reviewed_at = None
        change_request.dean_notes = ""
        update_fields += ["dean_reviewed_by", "dean_reviewed_at", "dean_notes"]
    else:
        change_request.ar_reviewed_by = None
        change_request.ar_reviewed_at = None
        change_request.ar_notes = ""
        update_fields += ["ar_reviewed_by", "ar_reviewed_at", "ar_notes"]

    actor_name = ""
    if actor is not None:
        actor_name = (
            getattr(actor, "get_full_name", lambda: "")() or getattr(actor, "username", "") or str(actor)
        )
    note = (
        f"[{timezone.now():%Y-%m-%d %H:%M}] {stage.upper()} decisions reopened"
        + (f" by {actor_name}" if actor_name else "")
        + (f": {(reason or '').strip()}" if (reason or "").strip() else ".")
    )
    change_request.review_notes = "\n".join(
        filter(None, [change_request.review_notes, note])
    )[:20000]
    update_fields.append("review_notes")
    change_request.save(update_fields=list(dict.fromkeys(update_fields)))

    return {
        "reopened": True,
        "stage": stage,
        "papers_reset": reset_n,
        "cleared_promotion_proposal": cleared_promotion,
        "hod_status": change_request.hod_status,
        "dean_status": change_request.dean_status,
        "ar_status": change_request.ar_status,
        "status": change_request.status,
    }


def propose_exemption_promotion(
    change_request: AdmissionChangeRequest,
    *,
    to_year: int,
    to_term: int,
    decided_by,
) -> dict:
    """
    HOD or Dean proposes a year/semester move. Stored on the request until AR
    final approval applies it together with curriculum exemptions.
    """
    if not exemption_ready_for_hod_promotion(change_request):
        raise ValueError(
            "The HOD must approve at least one exemption paper before proposing promotion."
        )

    student = change_request.admitted_student
    validate_advance_position(student, to_year=to_year, to_term=to_term)
    try:
        enrollment = student.programme_enrollment
    except Exception as exc:
        raise ValueError("Student has no programme enrollment to advance.") from exc

    from_year, from_term = enrollment.current_year_of_study, enrollment.current_term_number
    if (int(to_year), int(to_term)) == (int(from_year), int(from_term)):
        raise ValueError("Student is already at that year/term.")

    change_request.exemption_promotion_year = int(to_year)
    change_request.exemption_promotion_term = int(to_term)
    change_request.exemption_promotion_by = decided_by
    change_request.exemption_promotion_at = timezone.now()
    note = (
        f"[{timezone.now():%Y-%m-%d %H:%M}] Proposed promotion Y{from_year}T{from_term} -> "
        f"Y{to_year}T{to_term} (pending AR final approval), by "
        f"{getattr(decided_by, 'get_full_name', lambda: decided_by)() or decided_by}."
    )
    change_request.review_notes = "\n".join(
        filter(None, [change_request.review_notes, note])
    )[:20000]
    change_request.save(
        update_fields=[
            "exemption_promotion_year",
            "exemption_promotion_term",
            "exemption_promotion_by",
            "exemption_promotion_at",
            "review_notes",
            "updated_at",
        ]
    )
    return {
        "proposed": True,
        "pending_ar_approval": True,
        "from_year_of_study": from_year,
        "from_term_number": from_term,
        "to_year_of_study": to_year,
        "to_term_number": to_term,
    }


def finalize_exemption_effects(change_request: AdmissionChangeRequest, *, decided_by) -> dict:
    """
    Apply curriculum exemptions and any proposed promotion after AR final approval.
    """
    if change_request.change_type != "exemption":
        return {"applied": False, "reason": "not_exemption"}
    if change_request.ar_status != "approved":
        raise ValueError("AR must approve the exemption before effects can be applied.")
    if exemption_effects_applied(change_request):
        return {"applied": False, "reason": "already_applied"}

    overrides_created = apply_exemption_overrides(change_request, decided_by=decided_by)
    promotion = None
    if (
        change_request.exemption_promotion_year is not None
        and change_request.exemption_promotion_term is not None
    ):
        promotion = advance_student_position_for_exemption(
            change_request,
            to_year=int(change_request.exemption_promotion_year),
            to_term=int(change_request.exemption_promotion_term),
            decided_by=change_request.exemption_promotion_by or decided_by,
        )

    change_request.exemption_effects_applied_at = timezone.now()
    change_request.save(update_fields=["exemption_effects_applied_at", "updated_at"])
    return {
        "applied": True,
        "overrides_created": overrides_created,
        "promotion": promotion,
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

    assert_exemption_term_cap(
        student,
        {k for k in (_term_key(cl.year_of_study, cl.term_number),) if k},
    )

    course = cl.catalog_course
    line = ExemptionRequestLine.objects.create(
        change_request=change_request,
        curriculum_line=cl,
        course_code=(course.code if course else "")[:40],
        course_name=((course.title if course else "") or "")[:255],
        year_of_study=cl.year_of_study,
        term_number=cl.term_number,
        score_obtained=(score_obtained or "").strip()[:20],
        decision=ExemptionRequestLine.DECISION_PENDING,
    )
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
