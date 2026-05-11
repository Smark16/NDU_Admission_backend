from decimal import Decimal, InvalidOperation

from django.db import DatabaseError
from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from Programs.models import Program, ProgramBatch
from .models import FeeHead, FeePlan, FeePlanRule


def _get_or_create_other_fee_plan(program: Program) -> FeePlan:
    existing = (
        FeePlan.objects.filter(plan_type="general")
        .filter(Q(program=program) | Q(programs=program))
        .order_by("-updated_at")
        .first()
    )
    if existing:
        if existing.program_id != program.id and not existing.programs.filter(pk=program.id).exists():
            existing.programs.add(program)
        return existing
    return FeePlan.objects.create(
        plan_type="general",
        name=f"{program.short_form} — Other Fees Schedule",
        program=program,
        scope="program",
        status="draft",
        is_active=True,
    )


class ScheduledOtherFeeRuleListCreate(APIView):
    """
    GET/POST scheduled other-fee rules due by year/term.
    """

    permission_classes = [IsAdminUser]

    def get(self, request):
        try:
            program_id = request.query_params.get("program_id")
            program_batch_id = request.query_params.get("program_batch_id")
            if not program_id:
                return Response({"detail": "program_id is required."}, status=status.HTTP_400_BAD_REQUEST)
            try:
                program = Program.objects.get(pk=int(program_id))
            except (ValueError, TypeError, Program.DoesNotExist):
                return Response({"detail": "Invalid program_id."}, status=status.HTTP_400_BAD_REQUEST)
            selected_program_batch = None
            if program_batch_id not in (None, ""):
                try:
                    selected_program_batch = ProgramBatch.objects.get(pk=int(program_batch_id), program=program)
                except (ValueError, TypeError, ProgramBatch.DoesNotExist):
                    return Response({"detail": "Invalid program_batch_id."}, status=status.HTTP_400_BAD_REQUEST)

            rules_qs = (
                FeePlanRule.objects.filter(
                    is_active=True,
                    payable_year_of_study__isnull=False,
                    payable_term_number__isnull=False,
                )
                .filter(
                    Q(fee_plan__program=program)
                    | Q(fee_plan__programs=program)
                    | Q(program=program)
                )
                .exclude(
                    Q(fee_head__code__iexact="TUITION_FEE")
                    | Q(fee_head__code__iexact="FUNCTIONAL_FEE")
                )
                .select_related("fee_head", "fee_plan", "program_batch")
                .distinct()
            )
            if selected_program_batch:
                rules_qs = rules_qs.filter(
                    Q(program_batch=selected_program_batch) | Q(program_batch__isnull=True)
                )
            else:
                rules_qs = rules_qs.filter(program_batch__isnull=True)
            rules = rules_qs.order_by("payable_year_of_study", "payable_term_number", "order", "id")
            return Response(
                {
                    "program": {"id": program.id, "name": program.name, "short_form": program.short_form},
                    "program_batch": (
                        {
                            "id": selected_program_batch.id,
                            "name": selected_program_batch.name,
                        }
                        if selected_program_batch
                        else None
                    ),
                    "rows": [
                        {
                            "id": r.id,
                            "fee_plan_id": r.fee_plan_id,
                            "fee_plan_name": r.fee_plan.name if r.fee_plan_id else "",
                            "fee_head_id": r.fee_head_id,
                            "fee_head_name": r.fee_head.name if r.fee_head_id else "",
                            "amount": str(r.amount or "0"),
                            "currency": r.currency or "UGX",
                            "amount_international": str(r.amount_international) if r.amount_international is not None else "",
                            "currency_international": r.currency_international or "",
                            "payable_year_of_study": r.payable_year_of_study,
                            "payable_term_number": r.payable_term_number,
                            "program_batch_id": r.program_batch_id,
                            "program_batch_name": r.program_batch.name if r.program_batch_id else "",
                            "scope": "batch" if r.program_batch_id else "program_default",
                            "is_active": r.is_active,
                        }
                        for r in rules
                    ],
                }
            )
        except DatabaseError as e:
            return Response(
                {
                    "detail": (
                        "Database is out of date for scheduled other fees. "
                        "Run migrations: python manage.py migrate"
                    ),
                    "error": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception as e:
            return Response({"detail": f"Failed to load scheduled other fees: {e}"}, status=500)

    def post(self, request):
        try:
            program = Program.objects.get(pk=int(request.data.get("program_id")))
            fee_head = FeeHead.objects.get(pk=int(request.data.get("fee_head_id")), is_active=True)
            payable_year = int(request.data.get("payable_year_of_study"))
            payable_term = int(request.data.get("payable_term_number"))
            amount = Decimal(str(request.data.get("amount")))
        except (Program.DoesNotExist, FeeHead.DoesNotExist, ValueError, TypeError, InvalidOperation):
            return Response({"detail": "Invalid input values."}, status=status.HTTP_400_BAD_REQUEST)
        program_batch = None
        program_batch_id = request.data.get("program_batch_id")
        if program_batch_id not in (None, ""):
            try:
                program_batch = ProgramBatch.objects.get(pk=int(program_batch_id), program=program)
            except (ValueError, TypeError, ProgramBatch.DoesNotExist):
                return Response({"detail": "Invalid program_batch_id."}, status=status.HTTP_400_BAD_REQUEST)

        if payable_year < 1 or payable_year > int(program.max_years or 0):
            return Response(
                {"detail": f"payable_year_of_study must be between 1 and {program.max_years}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if payable_term < 1 or payable_term > int(program.max_terms_per_year or 0):
            return Response(
                {
                    "detail": (
                        f"payable_term_number must be between 1 and {program.max_terms_per_year} "
                        f"for a {program.calendar_type}-based programme."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if amount <= 0:
            return Response({"detail": "amount must be greater than zero."}, status=status.HTTP_400_BAD_REQUEST)

        fee_plan = _get_or_create_other_fee_plan(program)
        currency = (request.data.get("currency") or "UGX").strip()[:3].upper()
        amount_international = request.data.get("amount_international")
        currency_international = (request.data.get("currency_international") or "").strip()[:3].upper()

        existing = FeePlanRule.objects.filter(
            fee_plan=fee_plan,
            fee_head=fee_head,
            payable_year_of_study=payable_year,
            payable_term_number=payable_term,
            program_batch=program_batch,
        ).first()
        if existing:
            existing.amount = amount
            existing.currency = currency
            existing.amount_international = (
                Decimal(str(amount_international)) if amount_international not in (None, "") else None
            )
            existing.currency_international = currency_international
            existing.program = program
            existing.program_batch = program_batch
            existing.trigger_stage = "semester_start"
            existing.is_active = True
            existing.save()
            row = existing
        else:
            row = FeePlanRule.objects.create(
                fee_plan=fee_plan,
                fee_head=fee_head,
                program=program,
                program_batch=program_batch,
                trigger_stage="semester_start",
                amount=amount,
                currency=currency,
                amount_international=(
                    Decimal(str(amount_international)) if amount_international not in (None, "") else None
                ),
                currency_international=currency_international,
                payable_year_of_study=payable_year,
                payable_term_number=payable_term,
                is_active=True,
                order=1,
            )

        return Response(
            {
                "detail": "Scheduled other fee saved.",
                "id": row.id,
                "fee_plan_id": row.fee_plan_id,
                "program_batch_id": row.program_batch_id,
                "payable_year_of_study": row.payable_year_of_study,
                "payable_term_number": row.payable_term_number,
            },
            status=status.HTTP_200_OK,
        )


class ScheduledOtherFeeRuleDetail(APIView):
    permission_classes = [IsAdminUser]

    def delete(self, request, pk):
        try:
            row = FeePlanRule.objects.get(pk=pk)
        except FeePlanRule.DoesNotExist:
            return Response({"detail": "Rule not found."}, status=status.HTTP_404_NOT_FOUND)
        row.is_active = False
        row.save(update_fields=["is_active"])
        return Response({"detail": "Rule deactivated."}, status=status.HTTP_200_OK)


class ScheduledOtherFeeRuleClone(APIView):
    """
    Clone all active scheduled other-fee rules from one program to many programs.
    """

    permission_classes = [IsAdminUser]

    def post(self, request):
        try:
            source_program = Program.objects.get(pk=int(request.data.get("source_program_id")))
            target_ids = request.data.get("target_program_ids") or []
            if not isinstance(target_ids, list) or not target_ids:
                return Response({"detail": "target_program_ids must be a non-empty list."}, status=400)
            targets = list(Program.objects.filter(id__in=target_ids))
            if not targets:
                return Response({"detail": "No valid target programs found."}, status=400)
        except (Program.DoesNotExist, ValueError, TypeError):
            return Response({"detail": "Invalid source/target program ids."}, status=400)

        source_rules = (
            FeePlanRule.objects.filter(
                is_active=True,
                payable_year_of_study__isnull=False,
                payable_term_number__isnull=False,
                program_batch__isnull=True,
            )
            .filter(
                Q(fee_plan__program=source_program)
                | Q(fee_plan__programs=source_program)
                | Q(program=source_program)
            )
            .exclude(
                Q(fee_head__code__iexact="TUITION_FEE")
                | Q(fee_head__code__iexact="FUNCTIONAL_FEE")
            )
            .select_related("fee_head")
            .distinct()
        )

        cloned_count = 0
        for target in targets:
            fee_plan = _get_or_create_other_fee_plan(target)
            for src in source_rules:
                if src.payable_year_of_study > int(target.max_years or 0):
                    continue
                if src.payable_term_number > int(target.max_terms_per_year or 0):
                    continue
                row, created = FeePlanRule.objects.get_or_create(
                    fee_plan=fee_plan,
                    fee_head=src.fee_head,
                    payable_year_of_study=src.payable_year_of_study,
                    payable_term_number=src.payable_term_number,
                    defaults={
                        "program": target,
                        "trigger_stage": "semester_start",
                        "amount": src.amount,
                        "currency": src.currency,
                        "amount_international": src.amount_international,
                        "currency_international": src.currency_international,
                        "is_active": True,
                        "order": src.order or 1,
                    },
                )
                if not created:
                    row.program = target
                    row.amount = src.amount
                    row.currency = src.currency
                    row.amount_international = src.amount_international
                    row.currency_international = src.currency_international
                    row.is_active = True
                    row.save()
                cloned_count += 1

        return Response(
            {
                "detail": f"Cloned scheduled other fees to {len(targets)} program(s).",
                "cloned_rules": cloned_count,
            },
            status=200,
        )

