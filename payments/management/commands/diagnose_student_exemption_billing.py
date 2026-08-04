"""
Diagnose why a student's fee exemption / scholarship waiver did not post
money to the semesters staff expected, and whether fee-schedule billing
dates are blocking it.

Usage:
    python manage.py diagnose_student_exemption_billing --reg-no "26/2/508/W/2543"
    python manage.py diagnose_student_exemption_billing --schoolpay-code 1012144854
    python manage.py diagnose_student_exemption_billing --student-id 123
"""
from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from admissions.models import AdmissionChangeRequest, AdmittedStudent
from payments.billing_visibility import effective_billing_date
from payments.fee_exemptions import active_fee_exemptions_for_student
from payments.models import FeeHead, ScholarshipAward, StudentFeeExemption, StudentTuitionPayment, TuitionLedger
from payments.scholarship_services import (
    already_credited_for_fee_head,
    demand_amount_for_fee_head,
    waiver_target_amount,
)
from payments.student_portal_finance import (
    _applicable_other_schedule_rules,
    _rules_for_student,
    _student_curriculum_year_term,
    _student_program_batch_id,
    commitment_payment_summary,
)


def _find_student(reg_no, schoolpay_code, student_id, pk):
    qs = AdmittedStudent.objects.select_related(
        "application", "admitted_program", "admitted_program__faculty",
        "admitted_batch", "intended_program_batch", "programme_enrollment",
        "programme_enrollment__program_batch",
    )
    if pk:
        return qs.filter(pk=pk).first()
    if reg_no:
        return qs.filter(reg_no__iexact=reg_no.strip()).first()
    if schoolpay_code:
        return qs.filter(
            Q(schoolpay_code=schoolpay_code.strip()) | Q(student_id=schoolpay_code.strip())
        ).first()
    if student_id:
        return qs.filter(student_id__iexact=student_id.strip()).first()
    return None


class Command(BaseCommand):
    help = "Diagnose a student's fee exemption / scholarship billing (why money didn't move)."

    def add_arguments(self, parser):
        parser.add_argument("--reg-no", default=None)
        parser.add_argument("--schoolpay-code", default=None)
        parser.add_argument("--student-id", default=None)
        parser.add_argument("--pk", type=int, default=None)

    def handle(self, *args, **options):
        student = _find_student(
            options["reg_no"], options["schoolpay_code"], options["student_id"], options["pk"]
        )
        if student is None:
            raise CommandError("No matching student found for the given identifier.")

        today = timezone.localdate()
        w = self.stdout.write

        w("=" * 78)
        w(f"STUDENT: {student.full_name}  (reg_no={student.reg_no}, student_id={student.student_id}, "
          f"schoolpay_code={student.schoolpay_code}, pk={student.pk})")
        w(f"Programme: {getattr(student.admitted_program, 'name', '—')}  "
          f"Faculty: {getattr(getattr(student.admitted_program, 'faculty', None), 'name', '—')}")
        pb_id = _student_program_batch_id(student)
        w(f"Effective program_batch_id used for billing: {pb_id}")
        cur_y, cur_t = _student_curriculum_year_term(student)
        w(f"Current curriculum position (from enrollment): Year {cur_y} Term {cur_t}")
        w(f"Today (server localdate): {today.isoformat()}")
        w("=" * 78)

        # ------------------------------------------------------------------
        # 1. StudentFeeExemption rows (non-tuition 'other fee' exemptions)
        # ------------------------------------------------------------------
        w("\n--- StudentFeeExemption (other-fee exemptions, e.g. hostel) ---")
        active = active_fee_exemptions_for_student(student)
        revoked = list(
            StudentFeeExemption.objects.filter(student=student, is_active=False)
            .select_related("fee_head")
            .order_by("-created_at")
        )
        if not active and not revoked:
            w("  (none)")
        for row in active:
            scope = "ALL years/terms" if row.payable_year_of_study is None else (
                f"Y{row.payable_year_of_study}"
                + (f"T{row.payable_term_number}" if row.payable_term_number else " (all terms)")
            )
            w(f"  ACTIVE  fee_head={row.fee_head.code} scope={scope} reason={row.reason!r} "
              f"created={row.created_at}")
        for row in revoked:
            w(f"  REVOKED fee_head={row.fee_head.code} reason={row.reason!r} revoked_at={row.revoked_at}")

        # ------------------------------------------------------------------
        # 1b. Academic course-exemption change requests (the Dean-approval flow)
        # ------------------------------------------------------------------
        w("\n--- AdmissionChangeRequest (change_type=exemption) ---")
        change_requests = list(
            AdmissionChangeRequest.objects.filter(
                admitted_student=student, change_type="exemption"
            )
            .select_related("form_fee_charge", "reviewed_by")
            .prefetch_related("exemption_lines")
            .order_by("-created_at")
        )
        if not change_requests:
            w("  (no exemption change requests on record for this student)")
        for cr in change_requests:
            w(f"  Request #{cr.id} status={cr.status} created={cr.created_at} "
              f"reviewed_by={cr.reviewed_by} reviewed_at={cr.reviewed_at}")
            w(f"    reason={cr.reason!r}")
            if cr.review_notes:
                w(f"    review_notes={cr.review_notes!r}")
            ffc = cr.form_fee_charge
            if ffc is not None:
                w(f"    form_fee_charge: amount={ffc.amount} status={ffc.status} "
                  f"form_fee_paid_at={cr.form_fee_paid_at}")
            for line in cr.exemption_lines.all():
                w(f"    line: course_code={line.course_code!r} course_name={line.course_name!r} "
                  f"Y{line.year_of_study}T{line.term_number} score_obtained={line.score_obtained!r}")

        # ------------------------------------------------------------------
        # 1c. Fee heads named/coded like an exemption charge
        # ------------------------------------------------------------------
        w("\n--- FeeHead rows matching 'exemption' or code EXP ---")
        fee_heads = FeeHead.objects.filter(
            Q(code__icontains="exp") | Q(name__icontains="exempt")
        ).order_by("code")
        for fh in fee_heads:
            w(f"  code={fh.code!r} name={fh.name!r} category={fh.category} is_active={fh.is_active}")

        # ------------------------------------------------------------------
        # 2. Scholarship awards + waivers + credits
        # ------------------------------------------------------------------
        w("\n--- ScholarshipAward / Waivers / Credits ---")
        awards = list(
            ScholarshipAward.objects.filter(student=student)
            .select_related("programme")
            .prefetch_related("waivers__fee_head", "credits__fee_head")
            .order_by("-awarded_at")
        )
        if not awards:
            w("  (no scholarship awards for this student)")
        for award in awards:
            w(f"\n  Award #{award.id}  programme={award.programme.code} status={award.status}")
            w(f"    award_amount={award.award_amount} {award.currency}  "
              f"applied_amount={award.applied_amount}  remaining={award.remaining_amount}")
            waivers = list(award.waivers.all())
            if not waivers:
                w("    (no waivers configured on this award — nothing can ever be credited)")
            for waiver in waivers:
                fh = waiver.fee_head
                demand = demand_amount_for_fee_head(student, fh)
                already = already_credited_for_fee_head(award, fh)
                target = waiver_target_amount(award, waiver)
                w(f"    Waiver fee_head={fh.code} mode={waiver.waiver_mode} pct={waiver.percent}")
                w(f"      demand (billable-so-far, all reached milestones)={demand}")
                w(f"      already_credited_for_this_head={already}")
                w(f"      => target_amount_computed_now={target}"
                  + ("  <-- ZERO: nothing to post right now" if target == 0 else ""))
            credits = list(award.credits.all().order_by("-id"))
            if not credits:
                w("    Credits posted: (none)")
            else:
                w(f"    Credits posted ({len(credits)}):")
                for c in credits:
                    flag = " [REVERSED]" if c.is_reversed else ""
                    w(f"      #{c.id} fee_head={getattr(c.fee_head, 'code', '—')} amount={c.amount}{flag}"
                      f" applied_at={c.applied_at}")

        # ------------------------------------------------------------------
        # 3. Fee plan rules (tuition + other) with billing dates
        # ------------------------------------------------------------------
        w("\n--- Tuition FeePlanRule lines (billing dates) ---")
        for rule in _rules_for_student(student):
            eff = effective_billing_date(rule)
            reached = (eff is None) or (today >= eff)
            sem = rule.semester
            sem_label = (
                f"Y{sem.year_of_study}T{sem.term_number}" if sem is not None else "—"
            )
            w(f"  fee_head={rule.fee_head.code:<14} semester={sem_label:<6} amount={rule.amount:<12} "
              f"billing_date={eff} reached={'YES' if reached else 'NO — not billable yet'}")

        w("\n--- Other-fee schedule FeePlanRule lines (billing dates) ---")
        for rule in _applicable_other_schedule_rules(student):
            eff = effective_billing_date(rule)
            reached = (eff is None) or (today >= eff)
            w(f"  fee_head={rule.fee_head.code:<14} "
              f"Y{rule.payable_year_of_study}T{rule.payable_term_number:<3} amount={rule.amount:<12} "
              f"billing_date={eff} reached={'YES' if reached else 'NO — not billable yet'}")

        # ------------------------------------------------------------------
        # 4. Actual money on record
        # ------------------------------------------------------------------
        w("\n--- StudentTuitionPayment (portal / scholarship credit / ad-hoc charge rows) ---")
        payments = list(
            StudentTuitionPayment.objects.filter(student=student)
            .select_related("semester", "fee_head")
            .order_by("-id")[:30]
        )
        if not payments:
            w("  (none)")
        for p in payments:
            sem = p.semester
            sem_label = f"Y{sem.year_of_study}T{sem.term_number} (id={sem.id})" if sem else "— NO SEMESTER SET"
            w(f"  #{p.id} source={p.source} fee_head={getattr(p.fee_head, 'code', '—')} "
              f"label={p.label!r} amount={p.amount} status={p.status} waived={p.is_waived} "
              f"semester={sem_label} paid_at={p.paid_at} created_at={getattr(p, 'created_at', '—')}")
            w(f"      notes={(p.notes or '')!r}")

        w("\n--- TuitionLedger (SchoolPay / bank reconciliation rows) ---")
        ledgers = list(
            TuitionLedger.objects.filter(
                Q(student=student)
                | Q(student_payment_code__in=[
                    student.student_id, student.schoolpay_code, student.reg_no
                ])
            ).order_by("-id")[:30]
        )
        if not ledgers:
            w("  (none)")
        for l in ledgers:
            w(f"  #{l.id} amount={l.amount} status={l.transaction_completion_status} "
              f"receipt={l.schoolpay_receipt_number} payment_date={l.payment_date_time}")

        w("\n--- Commitment fee summary ---")
        summary = commitment_payment_summary(student)
        for k, v in summary.items():
            w(f"  {k}: {v}")

        w("\nDONE.")
