"""Admin API: scheduled other fees by program / optional batch (year + term milestones)."""

from django.db import DatabaseError
from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from Programs.models import Program, ProgramBatch

from .batch_semester_fee_helpers import parse_decimal
from .models import FeeHead, FeePlan, FeePlanRule


def _disallowed_fee_head(head: FeeHead) -> bool:
    code = (head.code or "").upper()
    if code in ("TUITION_FEE", "FUNCTIONAL_FEE"):
        return True
    if head.category == "tuition":
        return True
    return False


def get_or_create_other_schedule_fee_plan(program: Program) -> FeePlan:
    base = FeePlan.objects.filter(plan_type="other_schedule").filter(
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
        plan_type="other_schedule",
        batch=None,
        name=f"{program.short_form} — Scheduled other fees",
        program=program,
        is_active=True,
        term="",
        scope="program",
        status="approved",
        version=1,
    )


def _rule_to_row(r: FeePlanRule) -> dict:
    return {
        "id": r.id,
        "fee_head_id": r.fee_head_id,
        "fee_head_name": r.fee_head.name,
        "amount": str(r.amount),
        "currency": r.currency or "UGX",
        "amount_international": str(r.amount_international) if r.amount_international is not None else "",
        "currency_international": r.currency_international or "",
        "payable_year_of_study": r.payable_year_of_study,
        "payable_term_number": r.payable_term_number,
        "program_batch_id": r.program_batch_id,
        "program_batch_name": r.program_batch.name if r.program_batch_id else "",
        "scope": "batch" if r.program_batch_id else "program",
    }


class OtherFeeScheduleView(APIView):
    """GET list / POST create for /api/payments/other_fee_schedule"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        program_id = request.query_params.get("program_id")
        if not program_id:
            return Response(
                {"detail": "program_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            try:
                program = Program.objects.get(pk=int(program_id))
            except (Program.DoesNotExist, TypeError, ValueError):
                return Response({"detail": "Program not found"}, status=status.HTTP_404_NOT_FOUND)

            batch_id = request.query_params.get("program_batch_id")
            fee_plan = get_or_create_other_schedule_fee_plan(program)
            qs = (
                FeePlanRule.objects.filter(
                    fee_plan=fee_plan,
                    program_id=program.id,
                    is_active=True,
                    payable_year_of_study__isnull=False,
                    payable_term_number__isnull=False,
                )
                .select_related("fee_head", "program_batch")
                .order_by("payable_year_of_study", "payable_term_number", "fee_head__name", "id")
            )
            if batch_id:
                try:
                    bid = int(batch_id)
                except (TypeError, ValueError):
                    return Response({"detail": "Invalid program_batch_id"}, status=status.HTTP_400_BAD_REQUEST)
                pb = ProgramBatch.objects.filter(pk=bid, program=program).first()
                if not pb:
                    return Response({"detail": "Program batch not found"}, status=status.HTTP_404_NOT_FOUND)
                qs = qs.filter(Q(program_batch_id=bid) | Q(program_batch__isnull=True))
            else:
                qs = qs.filter(program_batch__isnull=True)

            return Response({"rows": [_rule_to_row(r) for r in qs]})
        except DatabaseError as e:
            return Response(
                {
                    "detail": (
                        "Database is out of date for scheduled other fees. "
                        "Run: python manage.py migrate payments"
                    ),
                    "error": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception as e:
            return Response(
                {"detail": f"Failed to load scheduled other fees: {e}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def post(self, request):
        try:
            program = Program.objects.get(pk=int(request.data.get("program_id")))
        except (Program.DoesNotExist, TypeError, ValueError):
            return Response({"detail": "Program not found"}, status=status.HTTP_404_NOT_FOUND)

        fee_head_id = request.data.get("fee_head_id")
        try:
            head = FeeHead.objects.get(pk=int(fee_head_id))
        except (FeeHead.DoesNotExist, TypeError, ValueError):
            return Response({"detail": "Invalid fee_head_id"}, status=status.HTTP_400_BAD_REQUEST)

        if _disallowed_fee_head(head):
            return Response(
                {"detail": "This fee item cannot be used in scheduled other fees."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            y = int(request.data.get("payable_year_of_study"))
            t = int(request.data.get("payable_term_number"))
        except (TypeError, ValueError):
            return Response(
                {"detail": "payable_year_of_study and payable_term_number are required integers"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if y < 1 or t < 1:
            return Response(
                {"detail": "Year and term must be positive"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        program_batch = None
        raw_pb = request.data.get("program_batch_id")
        if raw_pb not in (None, "", 0, "0"):
            try:
                program_batch = ProgramBatch.objects.get(pk=int(raw_pb), program=program)
            except (ProgramBatch.DoesNotExist, TypeError, ValueError):
                return Response({"detail": "Invalid program_batch_id"}, status=status.HTTP_400_BAD_REQUEST)

        amount = parse_decimal(request.data.get("amount"))
        if amount <= 0:
            return Response({"detail": "amount must be greater than zero"}, status=status.HTTP_400_BAD_REQUEST)

        currency = (request.data.get("currency") or "UGX").strip()[:3].upper() or "UGX"
        amt_intl_raw = request.data.get("amount_international")
        amount_international = None
        if amt_intl_raw not in (None, ""):
            amount_international = parse_decimal(amt_intl_raw)
            if amount_international <= 0:
                amount_international = None
        currency_international = (request.data.get("currency_international") or "").strip()[:3]
        if amount_international is None:
            currency_international = ""

        fee_plan = get_or_create_other_schedule_fee_plan(program)

        existing = FeePlanRule.objects.filter(
            fee_plan=fee_plan,
            program=program,
            program_batch=program_batch,
            fee_head=head,
            payable_year_of_study=y,
            payable_term_number=t,
        ).first()
        if existing:
            existing.amount = amount
            existing.currency = currency
            existing.amount_international = amount_international
            existing.currency_international = currency_international or ""
            existing.is_active = True
            existing.trigger_stage = "semester_start"
            existing.save()
            return Response({"id": existing.id, "detail": "updated"}, status=status.HTTP_200_OK)

        rule = FeePlanRule.objects.create(
            fee_plan=fee_plan,
            fee_head=head,
            program=program,
            program_batch=program_batch,
            semester=None,
            amount=amount,
            currency=currency,
            amount_international=amount_international,
            currency_international=currency_international or "",
            payable_year_of_study=y,
            payable_term_number=t,
            trigger_stage="semester_start",
            is_active=True,
            order=1,
        )
        return Response({"id": rule.id}, status=status.HTTP_201_CREATED)


class OtherFeeScheduleRuleDetailView(APIView):
    """DELETE /api/payments/other_fee_schedule/<id> — soft deactivate."""

    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        rule = FeePlanRule.objects.filter(pk=pk, fee_plan__plan_type="other_schedule").select_related("fee_plan").first()
        if not rule:
            return Response({"detail": "Rule not found"}, status=status.HTTP_404_NOT_FOUND)
        rule.is_active = False
        rule.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


class OtherFeeScheduleCloneView(APIView):
    """POST clone rules from one program to others (program-default rules only)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            source = Program.objects.get(pk=int(request.data.get("source_program_id")))
        except (Program.DoesNotExist, TypeError, ValueError):
            return Response({"detail": "source_program_id not found"}, status=status.HTTP_404_NOT_FOUND)

        targets = request.data.get("target_program_ids") or []
        if not isinstance(targets, list) or not targets:
            return Response({"detail": "target_program_ids must be a non-empty list"}, status=status.HTTP_400_BAD_REQUEST)

        source_plan = get_or_create_other_schedule_fee_plan(source)
        rules = list(
            FeePlanRule.objects.filter(
                fee_plan=source_plan,
                program=source,
                is_active=True,
                program_batch__isnull=True,
                payable_year_of_study__isnull=False,
                payable_term_number__isnull=False,
            ).select_related("fee_head")
        )

        created = 0
        for tid in targets:
            try:
                tid_int = int(tid)
            except (TypeError, ValueError):
                continue
            if tid_int == source.id:
                continue
            try:
                target_program = Program.objects.get(pk=tid_int)
            except Program.DoesNotExist:
                continue
            target_plan = get_or_create_other_schedule_fee_plan(target_program)
            for r in rules:
                if _disallowed_fee_head(r.fee_head):
                    continue
                FeePlanRule.objects.update_or_create(
                    fee_plan=target_plan,
                    program=target_program,
                    program_batch=None,
                    fee_head=r.fee_head,
                    payable_year_of_study=r.payable_year_of_study,
                    payable_term_number=r.payable_term_number,
                    defaults={
                        "amount": r.amount,
                        "currency": r.currency,
                        "amount_international": r.amount_international,
                        "currency_international": r.currency_international or "",
                        "trigger_stage": "semester_start",
                        "is_active": True,
                        "order": 1,
                    },
                )
                created += 1

        return Response({"detail": "cloned", "rules_touched": created})
