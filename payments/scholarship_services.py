"""Scholarship awards → ledger credits (completed StudentTuitionPayment rows)."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from admissions.models import AdmittedStudent
from payments.models import (
    FeeHead,
    ScholarshipAward,
    ScholarshipAwardWaiver,
    ScholarshipCredit,
    ScholarshipProgramme,
    ScholarshipProgrammeRate,
    ScholarshipProgrammeWaiver,
    StudentTuitionPayment,
)
from payments.student_fee_pricing import effective_amount_currency, is_international_student
from payments.student_portal_finance import (
    _adhoc_charges_for_student,
    _applicable_other_schedule_rules,
    _rules_for_student,
)
from payments.billing_visibility import billing_date_reached


TWOPLACES = Decimal("0.01")


def _q(amount: Decimal) -> Decimal:
    return (amount or Decimal("0")).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def programme_committed_amount(programme: ScholarshipProgramme) -> Decimal:
    """Sum of award ceilings for active awards (committed pot usage)."""
    total = (
        programme.awards.filter(status=ScholarshipAward.STATUS_ACTIVE).aggregate(
            s=Sum("award_amount")
        )["s"]
        or Decimal("0")
    )
    return _q(total)


def programme_applied_amount(programme: ScholarshipProgramme) -> Decimal:
    total = (
        ScholarshipCredit.objects.filter(
            award__programme=programme, is_reversed=False
        ).aggregate(s=Sum("amount"))["s"]
        or Decimal("0")
    )
    return _q(total)


def refresh_award_applied_amount(award: ScholarshipAward) -> Decimal:
    total = (
        award.credits.filter(is_reversed=False).aggregate(s=Sum("amount"))["s"]
        or Decimal("0")
    )
    award.applied_amount = _q(total)
    if (
        award.status == ScholarshipAward.STATUS_ACTIVE
        and award.applied_amount >= (award.award_amount or Decimal("0"))
        and award.award_amount > 0
    ):
        award.status = ScholarshipAward.STATUS_EXHAUSTED
    elif (
        award.status == ScholarshipAward.STATUS_EXHAUSTED
        and award.applied_amount < (award.award_amount or Decimal("0"))
    ):
        award.status = ScholarshipAward.STATUS_ACTIVE
    award.save(update_fields=["applied_amount", "status", "updated_at"])
    return award.applied_amount


def demand_amount_for_fee_head(student: AdmittedStudent, fee_head: FeeHead) -> Decimal:
    """Gross demand for a fee head (billable lines only), before payment allocation."""
    from payments.fee_exemptions import active_fee_exemptions_for_student, is_fee_head_exempted

    international = is_international_student(student)
    total = Decimal("0")
    fh_id = fee_head.id
    exemptions = active_fee_exemptions_for_student(student)

    for rule in _rules_for_student(student):
        if rule.fee_head_id != fh_id:
            continue
        if not billing_date_reached(rule):
            continue
        amt, _ = effective_amount_currency(rule, international)
        if amt > 0:
            total += amt

    for rule in _applicable_other_schedule_rules(student):
        if rule.fee_head_id != fh_id:
            continue
        py = int(rule.payable_year_of_study) if rule.payable_year_of_study else None
        pt = int(rule.payable_term_number) if rule.payable_term_number else None
        if is_fee_head_exempted(exemptions, fh_id, payable_year=py, payable_term=pt):
            continue
        if not billing_date_reached(rule):
            continue
        amt, _ = effective_amount_currency(rule, international)
        if amt > 0:
            total += amt

    for charge in _adhoc_charges_for_student(student):
        if charge.is_waived or charge.fee_head_id != fh_id:
            continue
        if (charge.amount or Decimal("0")) > 0:
            total += charge.amount

    return _q(total)


def already_credited_for_fee_head(award: ScholarshipAward, fee_head: FeeHead) -> Decimal:
    total = (
        award.credits.filter(fee_head=fee_head, is_reversed=False).aggregate(s=Sum("amount"))[
            "s"
        ]
        or Decimal("0")
    )
    return _q(total)


def waiver_target_amount(award: ScholarshipAward, waiver: ScholarshipAwardWaiver) -> Decimal:
    """How much credit this waiver wants to post (uncapped by award remaining)."""
    demand = demand_amount_for_fee_head(award.student, waiver.fee_head)
    if demand <= 0:
        return Decimal("0")
    already = already_credited_for_fee_head(award, waiver.fee_head)
    remaining_demand = demand - already
    if remaining_demand <= 0:
        return Decimal("0")

    if waiver.waiver_mode == ScholarshipProgrammeWaiver.WAIVER_FULL:
        target = remaining_demand
    else:
        pct = waiver.percent or Decimal("0")
        if pct <= 0:
            return Decimal("0")
        # Percent of original demand, minus what we already credited for this head
        wanted = _q(demand * pct / Decimal("100"))
        target = wanted - already
        if target < 0:
            target = Decimal("0")
        if target > remaining_demand:
            target = remaining_demand
    return _q(target)


def rate_for_student(programme: ScholarshipProgramme, student: AdmittedStudent):
    """Return ScholarshipProgrammeRate for the student's admitted academic programme, or None."""
    program_id = getattr(student, "admitted_program_id", None)
    if not program_id:
        return None
    return (
        ScholarshipProgrammeRate.objects.filter(
            scholarship=programme, academic_program_id=program_id
        )
        .select_related("academic_program")
        .first()
    )


def suggested_award_amount(programme: ScholarshipProgramme, student: AdmittedStudent):
    """Suggested award from rate table when awarding_mode is by_programme (or rates exist)."""
    rate = rate_for_student(programme, student)
    if rate is not None:
        return _q(rate.amount), rate
    return None, None


def copy_programme_waivers_to_award(award: ScholarshipAward) -> list[ScholarshipAwardWaiver]:
    created: list[ScholarshipAwardWaiver] = []
    for row in award.programme.default_waivers.select_related("fee_head"):
        obj, was_created = ScholarshipAwardWaiver.objects.get_or_create(
            award=award,
            fee_head=row.fee_head,
            defaults={
                "waiver_mode": row.waiver_mode,
                "percent": row.percent,
            },
        )
        if was_created:
            created.append(obj)
    return created


def validate_waiver_payload(waiver_mode: str, percent) -> tuple[str, Decimal | None]:
    mode = (waiver_mode or ScholarshipProgrammeWaiver.WAIVER_FULL).strip().lower()
    if mode not in (
        ScholarshipProgrammeWaiver.WAIVER_FULL,
        ScholarshipProgrammeWaiver.WAIVER_PERCENT,
    ):
        raise ValueError("waiver_mode must be 'full' or 'percent'.")
    pct = None
    if mode == ScholarshipProgrammeWaiver.WAIVER_PERCENT:
        try:
            pct = Decimal(str(percent))
        except Exception as exc:
            raise ValueError("percent is required for percentage waivers.") from exc
        if pct <= 0 or pct > 100:
            raise ValueError("percent must be between 0 and 100.")
    return mode, pct


@transaction.atomic
def apply_award_waivers(award: ScholarshipAward, user) -> list[ScholarshipCredit]:
    """Post ledger credits for each award waiver, capped by remaining award amount."""
    if award.status == ScholarshipAward.STATUS_REVOKED:
        raise ValueError("Cannot apply credits on a revoked award.")

    refresh_award_applied_amount(award)
    remaining = award.remaining_amount
    if remaining <= 0:
        raise ValueError("Award has no remaining balance to apply.")

    credits: list[ScholarshipCredit] = []
    waivers = list(award.waivers.select_related("fee_head"))
    if not waivers:
        raise ValueError("Award has no fee waivers configured.")

    now = timezone.now()
    for waiver in waivers:
        if remaining <= 0:
            break
        target = waiver_target_amount(award, waiver)
        if target <= 0:
            continue
        amount = min(target, remaining)
        amount = _q(amount)
        if amount <= 0:
            continue

        label = (
            f"{award.programme.name} scholarship — {waiver.fee_head.name}"
        )[:200]
        payment = StudentTuitionPayment.objects.create(
            student=award.student,
            source="scholarship",
            fee_head=waiver.fee_head,
            label=label,
            charged_by=user if getattr(user, "is_authenticated", False) else None,
            amount=amount,
            currency=award.currency or "UGX",
            payment_method="other",
            status="completed",
            paid_at=now,
            notes=(
                f"Scholarship credit. programme={award.programme.code} "
                f"award_id={award.id} waiver={waiver.waiver_mode}"
                + (f" {waiver.percent}%" if waiver.percent is not None else "")
            ),
        )
        credit = ScholarshipCredit.objects.create(
            award=award,
            fee_head=waiver.fee_head,
            amount=amount,
            currency=award.currency or "UGX",
            payment=payment,
            applied_by=user if getattr(user, "is_authenticated", False) else None,
            notes=label,
        )
        credits.append(credit)
        remaining -= amount

    refresh_award_applied_amount(award)
    return credits


@transaction.atomic
def reverse_credit(credit: ScholarshipCredit, user) -> ScholarshipCredit:
    if credit.is_reversed:
        raise ValueError("Credit is already reversed.")
    credit.is_reversed = True
    credit.reversed_at = timezone.now()
    credit.reversed_by = user if getattr(user, "is_authenticated", False) else None
    credit.save(update_fields=["is_reversed", "reversed_at", "reversed_by"])

    payment = credit.payment
    if payment and not payment.is_waived:
        payment.is_waived = True
        payment.waived_by = user if getattr(user, "is_authenticated", False) else None
        payment.waived_at = timezone.now()
        note = (payment.notes or "").strip()
        payment.notes = (note + " | Scholarship credit reversed.").strip(" |")
        payment.save(update_fields=["is_waived", "waived_by", "waived_at", "notes", "updated_at"])

    refresh_award_applied_amount(credit.award)
    return credit


@transaction.atomic
def revoke_award(award: ScholarshipAward, user, *, reverse_credits: bool = True) -> ScholarshipAward:
    if award.status == ScholarshipAward.STATUS_REVOKED:
        return award
    if reverse_credits:
        for credit in award.credits.filter(is_reversed=False):
            reverse_credit(credit, user)
    award.status = ScholarshipAward.STATUS_REVOKED
    award.revoked_at = timezone.now()
    award.revoked_by = user if getattr(user, "is_authenticated", False) else None
    award.save(update_fields=["status", "revoked_at", "revoked_by", "updated_at"])
    return award
