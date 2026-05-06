"""
NEW MODULE — Helpers for semester tuition matrix (batch × semester).

Used by batch_semester_fee_views.BatchSemesterFeeMatrixView:
  - get_or_create_tuition_fee_plan: one tuition FeePlan per program
  - tuition_head / functional_head: FeeHead rows for TUITION_FEE & FUNCTIONAL_FEE
  - rule_amount_map / upsert_rule: read/write FeePlanRule per program_batch + semester
"""
from decimal import Decimal

from django.db.models import Q

from Programs.models import Program
from .models import FeeHead, FeePlan, FeePlanRule


def get_or_create_tuition_fee_plan(program: Program) -> FeePlan:
    """
    One logical tuition plan per program. Prefer a plan with no admissions batch; otherwise reuse
    any tuition plan for this program.
    """
    base = FeePlan.objects.filter(plan_type='tuition').filter(
        Q(program_id=program.id) | Q(programs__id=program.id)
    )
    fp = base.filter(batch__isnull=True).distinct().first()
    if not fp:
        fp = base.distinct().first()
    if fp:
        if fp.program_id != program.id and not fp.programs.filter(pk=program.id).exists():
            fp.programs.add(program)
        return fp
    return FeePlan.objects.create(
        plan_type='tuition',
        batch=None,
        name=f'{program.short_form} — Tuition',
        program=program,
        is_active=True,
        term='',
        scope='program',
        status='draft',
        version=1,
    )


def tuition_head():
    fee, _ = FeeHead.objects.get_or_create(
        code='TUITION_FEE',
        defaults={
            'name': 'Tuition Fee',
            'category': 'tuition',
            'description': 'Per-semester tuition (configured under Semester tuition)',
        },
    )
    return fee


def functional_head():
    fee, _ = FeeHead.objects.get_or_create(
        code='FUNCTIONAL_FEE',
        defaults={
            'name': 'Functional Fees',
            'category': 'other',
            'description': 'Per-semester functional charges (ICT, library, etc.)',
        },
    )
    return fee


def plan_covers_program(plan: FeePlan, program_id: int) -> bool:
    if plan.program_id == program_id:
        return True
    return plan.programs.filter(pk=program_id).exists()


def rule_amount_map(fee_plan_id: int, program_id: int, program_batch_id: int):
    rules = FeePlanRule.objects.filter(
        fee_plan_id=fee_plan_id,
        program_batch_id=program_batch_id,
        program_batch__program_id=program_id,
    ).select_related('fee_head', 'program_batch', 'semester')
    out = {}
    for r in rules:
        key = (r.program_batch_id, r.semester_id)
        if key not in out:
            out[key] = {
                'tuition': None,
                'functional': None,
                'currency': 'UGX',
                'tuition_international': None,
                'tuition_currency_international': '',
                'functional_international': None,
                'functional_currency_international': '',
            }
        code = (r.fee_head.code or '').upper()
        if code == 'TUITION_FEE' or r.fee_head.category == 'tuition':
            out[key]['tuition'] = r.amount
            out[key]['currency'] = r.currency or out[key]['currency'] or 'UGX'
            out[key]['tuition_international'] = r.amount_international
            out[key]['tuition_currency_international'] = r.currency_international or ''
        elif code == 'FUNCTIONAL_FEE' or 'FUNCTIONAL' in code:
            out[key]['functional'] = r.amount
            out[key]['functional_international'] = r.amount_international
            out[key]['functional_currency_international'] = r.currency_international or ''
    return out


def upsert_rule(
    fee_plan,
    program,
    pb,
    sem,
    head,
    amount: Decimal,
    currency: str,
    amount_international=None,
    currency_international: str = '',
):
    qs = FeePlanRule.objects.filter(
        fee_plan=fee_plan,
        program_batch=pb,
        semester=sem,
        fee_head=head,
    )
    ci = (currency_international or '').strip()[:3]
    if qs.exists():
        r = qs.first()
        r.amount = amount
        r.currency = currency
        r.amount_international = amount_international
        r.currency_international = ci
        r.trigger_stage = 'semester_start'
        r.program = program
        r.save()
        return r
    return FeePlanRule.objects.create(
        fee_plan=fee_plan,
        fee_head=head,
        program=program,
        program_batch=pb,
        semester=sem,
        amount=amount,
        currency=currency,
        amount_international=amount_international,
        currency_international=ci,
        trigger_stage='semester_start',
        is_active=True,
        order=1,
    )


def parse_decimal(v):
    if v is None or v == '':
        return Decimal('0')
    return Decimal(str(v))
