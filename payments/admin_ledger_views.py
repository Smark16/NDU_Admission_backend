"""Staff-facing tuition payment ledger for admitted students."""
from __future__ import annotations

import csv
from datetime import datetime
from decimal import Decimal

from django.db.models import Count, DecimalField, Max, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from accounts.erp_drf_permissions import FinanceModuleAdminPermission
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.models import AdmittedStudent, Batch, Campus
from Programs.models import Program, ProgramBatch

from .models import StudentTuitionPayment
from .student_portal_finance import (
    COMMITMENT_FEE_THRESHOLD,
    payment_status_dict,
    student_billing_lines,
    student_finance_totals,
)
from .commitment_queryset import annotate_commitment_ugx_paid, filter_by_commitment_met


def _parse_page(value, default: int = 1) -> int:
    try:
        page = int(value)
    except (TypeError, ValueError):
        return default
    return max(page, 1)


def _parse_page_size(value, default: int = 25, maximum: int = 100) -> int:
    try:
        size = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(size, 1), maximum)


def _parse_bool(value: str | None) -> bool | None:
    if value is None or value == "":
        return None
    return value.lower() in {"1", "true", "yes"}


def _parse_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _batch_intake_label(batch: Batch | None) -> str | None:
    if batch is None:
        return None
    if batch.academic_year:
        return f"{batch.name} ({batch.academic_year})"
    return batch.name


def _ledger_cohort_params(request) -> dict[str, int | str | None]:
    return {
        "batch_id": _parse_int(request.query_params.get("batch_id") or request.query_params.get("intake_id")),
        "program_id": _parse_int(request.query_params.get("program_id")),
        "campus_id": _parse_int(request.query_params.get("campus_id")),
        "program_batch_id": _parse_int(request.query_params.get("program_batch_id")),
        "academic_year": (request.query_params.get("academic_year") or "").strip() or None,
        "intake": (request.query_params.get("intake") or "").strip() or None,
    }


def _apply_student_cohort_filters(qs, cohort: dict[str, int | str | None]):
    if cohort["batch_id"]:
        qs = qs.filter(admitted_batch_id=cohort["batch_id"])
    if cohort["program_id"]:
        qs = qs.filter(admitted_program_id=cohort["program_id"])
    if cohort["campus_id"]:
        qs = qs.filter(admitted_campus_id=cohort["campus_id"])
    if cohort["academic_year"]:
        qs = qs.filter(admitted_batch__academic_year=cohort["academic_year"])
    if cohort["program_batch_id"]:
        qs = qs.filter(programme_enrollment__program_batch_id=cohort["program_batch_id"])
    if cohort["intake"]:
        intake = cohort["intake"]
        if intake.isdigit():
            qs = qs.filter(admitted_batch_id=int(intake))
        else:
            qs = qs.filter(
                Q(admitted_batch__name=cohort["intake"])
                | Q(admitted_batch__code=cohort["intake"])
            )
    return qs


def _apply_transaction_cohort_filters(qs, cohort: dict[str, int | str | None]):
    if cohort["batch_id"]:
        qs = qs.filter(student__admitted_batch_id=cohort["batch_id"])
    if cohort["program_id"]:
        qs = qs.filter(student__admitted_program_id=cohort["program_id"])
    if cohort["campus_id"]:
        qs = qs.filter(student__admitted_campus_id=cohort["campus_id"])
    if cohort["academic_year"]:
        qs = qs.filter(student__admitted_batch__academic_year=cohort["academic_year"])
    if cohort["program_batch_id"]:
        qs = qs.filter(student__programme_enrollment__program_batch_id=cohort["program_batch_id"])
    if cohort["intake"]:
        intake = cohort["intake"]
        if intake.isdigit():
            qs = qs.filter(student__admitted_batch_id=int(intake))
        else:
            qs = qs.filter(
                Q(student__admitted_batch__name=cohort["intake"])
                | Q(student__admitted_batch__code=cohort["intake"])
            )
    return qs


def _student_search_filter(search: str) -> Q:
    term = (search or "").strip()
    if not term:
        return Q()
    return (
        Q(student_id__icontains=term)
        | Q(reg_no__icontains=term)
        | Q(schoolpay_code__icontains=term)
        | Q(application__first_name__icontains=term)
        | Q(application__last_name__icontains=term)
    )


def _transaction_search_filter(search: str) -> Q:
    term = (search or "").strip()
    if not term:
        return Q()
    return (
        Q(student__student_id__icontains=term)
        | Q(student__reg_no__icontains=term)
        | Q(student__schoolpay_code__icontains=term)
        | Q(student__application__first_name__icontains=term)
        | Q(student__application__last_name__icontains=term)
        | Q(receipt_number__icontains=term)
        | Q(payment_reference__icontains=term)
        | Q(label__icontains=term)
    )


def _student_payment_counts(student: AdmittedStudent) -> tuple[int, int]:
    if "completed_payment_count" in student.__dict__:
        return (
            int(student.completed_payment_count or 0),
            int(student.pending_payment_count or 0),
        )
    completed = StudentTuitionPayment.objects.filter(student=student, status="completed").count()
    pending = StudentTuitionPayment.objects.filter(student=student, status="pending").count()
    return completed, pending


def _student_last_paid_at(student: AdmittedStudent):
    if "last_paid_at" in student.__dict__:
        return student.last_paid_at
    return (
        StudentTuitionPayment.objects.filter(student=student, status="completed")
        .order_by("-paid_at", "-created_at")
        .values_list("paid_at", flat=True)
        .first()
    )


def _cohort_finance_summary(students_qs) -> dict[str, float]:
    billed = Decimal("0")
    paid = Decimal("0")
    balance = Decimal("0")
    for student in students_qs.iterator(chunk_size=100):
        totals = student_finance_totals(student)
        billed += Decimal(str(totals["total_required"]))
        paid += Decimal(str(totals["total_paid"]))
        balance += Decimal(str(totals["balance"]))
    return {
        "total_billed": float(billed),
        "total_paid": float(paid),
        "total_balance": float(balance),
    }


def _student_display_name(student: AdmittedStudent) -> str:
    try:
        return student.full_name or ""
    except Exception:
        if student.application_id and student.application:
            return getattr(student.application, "full_name", "") or ""
    return ""


def _commitment_student_row(student: AdmittedStudent) -> dict:
    """Lightweight list row — uses commitment annotations when present."""
    threshold = float(COMMITMENT_FEE_THRESHOLD)
    paid_raw = getattr(student, "commitment_paid_ugx", None)
    if paid_raw is None:
        finance = student_finance_totals(student)
        paid = float(finance["commitment_paid_ugx"])
        met = bool(finance["commitment_met"])
        balance = float(finance["commitment_balance"])
    else:
        paid = float(paid_raw or 0)
        admission_paid = bool(student.admission_fee_paid)
        met = admission_paid or paid >= threshold
        balance = 0.0 if met else max(threshold - paid, 0.0)

    enrollment_status = None
    try:
        enrollment_status = student.programme_enrollment.status
    except Exception:
        enrollment_status = None

    return {
        "id": student.id,
        "student_id": student.student_id,
        "reg_no": student.reg_no,
        "student_name": _student_display_name(student),
        "program": student.admitted_program.name if student.admitted_program_id else None,
        "campus": student.admitted_campus.name if student.admitted_campus_id else None,
        "batch_id": student.admitted_batch_id,
        "batch_name": student.admitted_batch.name if student.admitted_batch_id else None,
        "academic_year": student.admitted_batch.academic_year if student.admitted_batch_id else None,
        "intake": _batch_intake_label(student.admitted_batch if student.admitted_batch_id else None),
        "schoolpay_code": student.effective_schoolpay_code,
        "commitment_threshold": threshold,
        "commitment_paid_ugx": paid,
        "commitment_met": met,
        "commitment_balance": balance,
        "total_paid": paid,
        "balance": balance,
        "enrollment_status": enrollment_status,
    }


def _commitment_students_queryset(
    *,
    search: str = "",
    cohort: dict[str, int | str | None] | None = None,
    commitment_met: bool | None = None,
):
    qs = (
        AdmittedStudent.objects.filter(is_admitted=True)
        .select_related(
            "admitted_program",
            "admitted_campus",
            "admitted_batch",
            "application",
            "programme_enrollment",
        )
        .filter(_student_search_filter(search))
        .order_by("student_id", "-id")
    )
    if cohort:
        qs = _apply_student_cohort_filters(qs, cohort)
    if commitment_met is not None:
        qs = filter_by_commitment_met(qs, commitment_met)
    else:
        qs = annotate_commitment_ugx_paid(qs)
    return qs


class _CsvEcho:
    """Write CSV rows for StreamingHttpResponse."""

    def write(self, value: str) -> str:
        return value


def _student_row(student: AdmittedStudent) -> dict:
    finance = student_finance_totals(student)
    completed_count, pending_count = _student_payment_counts(student)
    paid_at = _student_last_paid_at(student)
    enrollment_status = None
    try:
        enrollment_status = student.programme_enrollment.status
    except Exception:
        enrollment_status = None

    return {
        "id": student.id,
        "student_id": student.student_id,
        "reg_no": student.reg_no,
        "student_name": _student_display_name(student),
        "program": student.admitted_program.name if student.admitted_program_id else None,
        "campus": student.admitted_campus.name if student.admitted_campus_id else None,
        "batch_id": student.admitted_batch_id,
        "batch_name": student.admitted_batch.name if student.admitted_batch_id else None,
        "academic_year": student.admitted_batch.academic_year if student.admitted_batch_id else None,
        "intake": _batch_intake_label(student.admitted_batch if student.admitted_batch_id else None),
        "schoolpay_code": student.effective_schoolpay_code,
        "total_required": finance["total_required"],
        "total_paid": finance["total_paid"],
        "balance": finance["balance"],
        "percentage_paid": finance["percentage_paid"],
        "display_currency": finance["display_currency"],
        "tuition_structure_total": finance["tuition_structure_total"],
        "ad_hoc_total": finance["ad_hoc_total"],
        "scheduled_other_fees_due": finance["scheduled_other_fees_due"],
        "commitment_threshold": finance["commitment_threshold"],
        "commitment_paid_ugx": finance["commitment_paid_ugx"],
        "commitment_met": finance["commitment_met"],
        "commitment_balance": finance["commitment_balance"],
        "completed_payment_count": completed_count,
        "pending_payment_count": pending_count,
        "last_paid_at": paid_at.isoformat() if paid_at else None,
        "enrollment_status": enrollment_status,
    }


def _transaction_row(payment: StudentTuitionPayment) -> dict:
    student = payment.student
    if payment.source == "ad_hoc":
        fee_label = payment.label or (payment.fee_head.name if payment.fee_head_id else "Ad-hoc charge")
    else:
        fee_label = payment.label or (
            payment.fee_plan_rule.fee_head.name
            if payment.fee_plan_rule_id and payment.fee_plan_rule.fee_head_id
            else "Tuition"
        )

    return {
        "id": payment.id,
        "student_pk": student.id,
        "student_id": student.student_id,
        "reg_no": student.reg_no,
        "student_name": _student_display_name(student),
        "program": student.admitted_program.name if student.admitted_program_id else None,
        "intake": _batch_intake_label(student.admitted_batch if student.admitted_batch_id else None),
        "amount": float(payment.amount),
        "currency": payment.currency or "UGX",
        "status": payment.status,
        "source": payment.source,
        "label": fee_label,
        "payment_method": payment.payment_method or "",
        "receipt_number": payment.receipt_number or "",
        "payment_reference": payment.payment_reference or "",
        "paid_at": payment.paid_at.isoformat() if payment.paid_at else None,
        "created_at": payment.created_at.isoformat(),
        "is_waived": payment.is_waived,
    }


class AdminTuitionLedgerFiltersView(APIView):
    """GET /api/payments/admin/tuition_ledger/filters"""

    permission_classes = [FinanceModuleAdminPermission]

    def get(self, request):
        admitted = AdmittedStudent.objects.filter(is_admitted=True)
        batch_ids = admitted.values_list("admitted_batch_id", flat=True).distinct()
        program_ids = admitted.values_list("admitted_program_id", flat=True).distinct()
        campus_ids = admitted.values_list("admitted_campus_id", flat=True).distinct()
        program_batch_ids = (
            admitted.filter(programme_enrollment__program_batch_id__isnull=False)
            .values_list("programme_enrollment__program_batch_id", flat=True)
            .distinct()
        )

        intakes = [
            {
                "id": batch.id,
                "name": batch.name,
                "academic_year": batch.academic_year,
                "label": _batch_intake_label(batch),
            }
            for batch in Batch.objects.filter(id__in=batch_ids).order_by("-created_at")
        ]
        academic_years = list(
            Batch.objects.filter(id__in=batch_ids)
            .exclude(academic_year="")
            .order_by("-academic_year")
            .values_list("academic_year", flat=True)
            .distinct()
        )
        programs = list(
            Program.objects.filter(id__in=program_ids).order_by("name").values("id", "name")
        )
        campuses = list(
            Campus.objects.filter(id__in=campus_ids).order_by("name").values("id", "name")
        )
        program_batches = [
            {
                "id": batch.id,
                "name": batch.name,
                "program_id": batch.program_id,
                "program_name": batch.program.name if batch.program_id else None,
                "academic_year": batch.academic_year,
            }
            for batch in ProgramBatch.objects.filter(id__in=program_batch_ids)
            .select_related("program")
            .order_by("program__name", "name")
        ]

        return Response(
            {
                "intakes": intakes,
                "academic_years": academic_years,
                "programs": programs,
                "campuses": campuses,
                "program_batches": program_batches,
            }
        )


class AdminTuitionLedgerStudentsView(APIView):
    """GET /api/payments/admin/tuition_ledger/students"""

    permission_classes = [FinanceModuleAdminPermission]

    def get(self, request):
        page = _parse_page(request.query_params.get("page"))
        page_size = _parse_page_size(request.query_params.get("page_size"))
        search = request.query_params.get("search", "")
        commitment_met = _parse_bool(request.query_params.get("commitment_met"))
        cohort = _ledger_cohort_params(request)
        include_finance_summary = _parse_bool(
            request.query_params.get("include_finance_summary")
        )
        skip_summary = _parse_bool(request.query_params.get("skip_summary"))

        qs = _commitment_students_queryset(
            search=search,
            cohort=cohort,
            commitment_met=commitment_met,
        )

        total = qs.count()
        offset = (page - 1) * page_size
        page_qs = list(qs[offset : offset + page_size])
        rows = []
        for student in page_qs:
            try:
                rows.append(_commitment_student_row(student))
            except Exception:
                rows.append(
                    {
                        "id": student.id,
                        "student_id": student.student_id,
                        "reg_no": student.reg_no,
                        "student_name": _student_display_name(student),
                        "program": student.admitted_program.name
                        if student.admitted_program_id
                        else None,
                        "campus": student.admitted_campus.name
                        if student.admitted_campus_id
                        else None,
                        "commitment_threshold": float(COMMITMENT_FEE_THRESHOLD),
                        "commitment_paid_ugx": 0.0,
                        "commitment_met": bool(student.admission_fee_paid),
                        "commitment_balance": float(COMMITMENT_FEE_THRESHOLD),
                        "total_paid": 0.0,
                        "balance": float(COMMITMENT_FEE_THRESHOLD),
                        "enrollment_status": None,
                    }
                )

        summary = {
            "students_count": 0,
            "commitment_met_count": 0,
            "commitment_threshold": float(COMMITMENT_FEE_THRESHOLD),
            "completed_payments_count": 0,
            "completed_amount_ugx": 0.0,
        }
        if not skip_summary:
            summary_qs = _apply_student_cohort_filters(
                AdmittedStudent.objects.filter(is_admitted=True),
                cohort,
            )
            commitment_met_count = filter_by_commitment_met(summary_qs, True).count()
            payment_totals = _apply_transaction_cohort_filters(
                StudentTuitionPayment.objects.filter(status="completed"),
                cohort,
            ).aggregate(
                completed_count=Count("id"),
                completed_amount_ugx=Coalesce(
                    Sum("amount", filter=Q(currency="UGX")),
                    Value(0),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                ),
            )
            summary = {
                "students_count": summary_qs.count(),
                "commitment_met_count": commitment_met_count,
                "commitment_threshold": float(COMMITMENT_FEE_THRESHOLD),
                "completed_payments_count": int(payment_totals["completed_count"] or 0),
                "completed_amount_ugx": float(payment_totals["completed_amount_ugx"] or 0),
            }
            if include_finance_summary:
                try:
                    summary.update(
                        _cohort_finance_summary(
                            summary_qs.select_related(
                                "admitted_program",
                                "admitted_campus",
                                "admitted_batch",
                                "application",
                                "programme_enrollment",
                            )
                        )
                    )
                except Exception:
                    summary.update(
                        {
                            "total_billed": 0.0,
                            "total_paid": 0.0,
                            "total_balance": 0.0,
                        }
                    )

        return Response(
            {
                "summary": summary,
                "filters": cohort,
                "results": rows,
                "page": page,
                "page_size": page_size,
                "total": total,
            }
        )


class AdminTuitionLedgerStudentsExportView(APIView):
    """GET /api/payments/admin/tuition_ledger/students/export — CSV download."""

    permission_classes = [FinanceModuleAdminPermission]

    def get(self, request):
        search = request.query_params.get("search", "")
        commitment_met = _parse_bool(request.query_params.get("commitment_met"))
        if commitment_met is None:
            commitment_met = False
        cohort = _ledger_cohort_params(request)
        qs = _commitment_students_queryset(
            search=search,
            cohort=cohort,
            commitment_met=commitment_met,
        )

        label = "paid" if commitment_met else "unpaid"
        filename = f"commitment_{label}_{datetime.now().strftime('%Y-%m-%d')}.csv"

        def stream_rows():
            pseudo_buffer = _CsvEcho()
            writer = csv.writer(pseudo_buffer)
            yield writer.writerow(
                [
                    "Student ID",
                    "Reg No",
                    "Name",
                    "Program",
                    "Campus",
                    "Intake",
                    "Commitment Paid (UGX)",
                    "Commitment Balance (UGX)",
                    "Status",
                ]
            )
            for student in qs.iterator(chunk_size=500):
                try:
                    row = _commitment_student_row(student)
                except Exception:
                    row = {
                        "student_id": student.student_id,
                        "reg_no": student.reg_no,
                        "student_name": _student_display_name(student),
                        "program": None,
                        "campus": None,
                        "intake": None,
                        "commitment_paid_ugx": 0.0,
                        "commitment_balance": float(COMMITMENT_FEE_THRESHOLD),
                        "commitment_met": bool(student.admission_fee_paid),
                    }
                yield writer.writerow(
                    [
                        row.get("student_id") or "",
                        row.get("reg_no") or "",
                        row.get("student_name") or "",
                        row.get("program") or "",
                        row.get("campus") or "",
                        row.get("intake") or "",
                        row.get("commitment_paid_ugx") or 0,
                        row.get("commitment_balance") or 0,
                        "Paid" if row.get("commitment_met") else "Not paid",
                    ]
                )

        response = StreamingHttpResponse(stream_rows(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class AdminTuitionLedgerStudentDetailView(APIView):
    """GET /api/payments/admin/tuition_ledger/students/<student_id>"""

    permission_classes = [FinanceModuleAdminPermission]

    def get(self, request, student_id):
        student = get_object_or_404(
            AdmittedStudent.objects.select_related(
                "admitted_program",
                "admitted_campus",
                "admitted_batch",
                "application",
                "programme_enrollment",
            ),
            pk=student_id,
            is_admitted=True,
        )
        finance = payment_status_dict(student, request)
        return Response(
            {
                "student": _student_row(student),
                "finance": finance,
                "billing_lines": student_billing_lines(student),
            }
        )


class AdminTuitionLedgerTransactionsView(APIView):
    """GET /api/payments/admin/tuition_ledger/transactions"""

    permission_classes = [FinanceModuleAdminPermission]

    def get(self, request):
        page = _parse_page(request.query_params.get("page"))
        page_size = _parse_page_size(request.query_params.get("page_size"))
        search = request.query_params.get("search", "")
        status = (request.query_params.get("status") or "").strip().lower()
        source = (request.query_params.get("source") or "").strip().lower()
        from_date = parse_date(request.query_params.get("from_date") or "")
        to_date = parse_date(request.query_params.get("to_date") or "")
        cohort = _ledger_cohort_params(request)

        qs = (
            StudentTuitionPayment.objects.select_related(
                "student",
                "student__admitted_program",
                "student__admitted_batch",
                "student__application",
                "fee_head",
                "fee_plan_rule__fee_head",
            )
            .filter(_transaction_search_filter(search))
            .order_by("-paid_at", "-created_at")
        )
        qs = _apply_transaction_cohort_filters(qs, cohort)

        if status:
            qs = qs.filter(status=status)
        if source:
            qs = qs.filter(source=source)
        if from_date:
            qs = qs.filter(
                Q(paid_at__date__gte=from_date)
                | Q(paid_at__isnull=True, created_at__date__gte=from_date)
            )
        if to_date:
            qs = qs.filter(
                Q(paid_at__date__lte=to_date)
                | Q(paid_at__isnull=True, created_at__date__lte=to_date)
            )

        total = qs.count()
        offset = (page - 1) * page_size
        rows = [_transaction_row(payment) for payment in qs[offset : offset + page_size]]

        return Response(
            {
                "filters": cohort,
                "results": rows,
                "page": page,
                "page_size": page_size,
                "total": total,
            }
        )
