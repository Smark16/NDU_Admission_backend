"""Weekly Bursar report metrics from live admissions + commitment data."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from admissions.models import AdmittedStudent, Application
from accounts.portal_branding import get_university_display_name
from payments.commitment_queryset import annotate_commitment_ugx_paid
from payments.models import BursarWeeklyReportSettings, TuitionLedger
from payments.student_payment_allocation import COMMITMENT_FEE_THRESHOLD

LOCAL_NATIONALITIES = {"ugandan", "uganda", "ug"}


def week_bounds_for(reference: date | None = None) -> tuple[date, date]:
    ref = reference or timezone.localdate()
    monday = ref - timedelta(days=ref.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def _pct(part: int | float, whole: int | float) -> float:
    if not whole:
        return 0.0
    return round((float(part) / float(whole)) * 100.0, 1)


def _money(amount: Decimal | float | int | None) -> str:
    try:
        n = int(Decimal(str(amount or 0)))
    except Exception:
        n = 0
    return f"UGX {n:,}"


def _safe_name(raw) -> str:
    name = (raw or "").strip() if isinstance(raw, str) else str(raw or "").strip()
    return name or "Unassigned"


def _admitted_base():
    return AdmittedStudent.objects.filter(is_admitted=True)


def build_bursar_weekly_metrics(*, reference: date | None = None) -> dict[str, Any]:
    """
    Build report metrics from the live portal DB.

    Paid = admission_fee_paid (ops commitment flag). Amounts use annotated
    commitment UGX paid where available.
    """
    week_start, week_end = week_bounds_for(reference)
    settings_row = BursarWeeklyReportSettings.get_solo()
    threshold = COMMITMENT_FEE_THRESHOLD
    uni = get_university_display_name()

    apps = Application.objects.exclude(status="draft")
    apps_week = apps.filter(created_at__date__gte=week_start, created_at__date__lte=week_end)
    applications_received = apps_week.count()
    pending = apps.filter(status__in=["submitted", "under_review"]).count()

    admitted_qs = _admitted_base()
    admitted_total = admitted_qs.count()
    paid_qs = admitted_qs.filter(admission_fee_paid=True)
    paid_total = paid_qs.count()
    not_paid_total = max(admitted_total - paid_total, 0)
    collection_rate = _pct(paid_total, admitted_total)
    revenue_at_risk = Decimal(not_paid_total) * threshold

    annotated = annotate_commitment_ugx_paid(admitted_qs)
    total_collected = annotated.aggregate(s=Sum("commitment_paid_ugx"))["s"] or Decimal("0")

    # Faculty breakdown
    faculty_rows_raw = list(
        annotated.values("admitted_program__faculty__name")
        .annotate(
            admitted=Count("id"),
            paid=Count("id", filter=Q(admission_fee_paid=True)),
            amount=Sum("commitment_paid_ugx"),
        )
        .order_by("-admitted")
    )
    by_faculty = []
    for row in faculty_rows_raw:
        admitted = int(row["admitted"] or 0)
        paid = int(row["paid"] or 0)
        not_paid = max(admitted - paid, 0)
        amount = Decimal(row["amount"] or 0)
        by_faculty.append(
            {
                "name": _safe_name(row["admitted_program__faculty__name"]),
                "admitted": admitted,
                "paid": paid,
                "not_paid": not_paid,
                "collection_rate": _pct(paid, admitted),
                "amount": amount,
                "amount_display": _money(amount),
                "revenue_at_risk": Decimal(not_paid) * threshold,
                "revenue_at_risk_display": _money(Decimal(not_paid) * threshold),
            }
        )

    # Campus breakdown
    campus_rows_raw = list(
        annotated.values("admitted_campus__name")
        .annotate(
            admitted=Count("id"),
            paid=Count("id", filter=Q(admission_fee_paid=True)),
            amount=Sum("commitment_paid_ugx"),
        )
        .order_by("-admitted")
    )
    by_campus = []
    for row in campus_rows_raw:
        admitted = int(row["admitted"] or 0)
        paid = int(row["paid"] or 0)
        not_paid = max(admitted - paid, 0)
        amount = Decimal(row["amount"] or 0)
        by_campus.append(
            {
                "name": _safe_name(row["admitted_campus__name"]),
                "admitted": admitted,
                "paid": paid,
                "not_paid": not_paid,
                "collection_rate": _pct(paid, admitted),
                "amount": amount,
                "amount_display": _money(amount),
            }
        )

    # Demographics (admitted)
    gender_map: dict[str, int] = defaultdict(int)
    local = 0
    international = 0
    for g, nat in admitted_qs.select_related("application").values_list(
        "application__gender", "application__nationality"
    ):
        g_label = (g or "Unknown").strip().title() or "Unknown"
        if g_label.lower() in ("m", "male"):
            g_label = "Male"
        elif g_label.lower() in ("f", "female"):
            g_label = "Female"
        gender_map[g_label] += 1
        nat_key = (nat or "").strip().lower()
        if nat_key in LOCAL_NATIONALITIES or nat_key.startswith("uganda"):
            local += 1
        else:
            international += 1

    by_gender = [{"name": k, "count": v, "pct": _pct(v, admitted_total)} for k, v in sorted(gender_map.items())]

    # Academic level
    level_rows = list(
        admitted_qs.values("admitted_program__academic_level__name")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    by_level = [
        {
            "name": _safe_name(r["admitted_program__academic_level__name"]),
            "count": int(r["count"] or 0),
            "pct": _pct(r["count"] or 0, admitted_total),
        }
        for r in level_rows
    ]

    # Enrolment status (programme enrollment)
    from Programs.models import StudentProgrammeEnrollment

    enrolled_ids = set(
        StudentProgrammeEnrollment.objects.filter(status="enrolled").values_list(
            "student_id", flat=True
        )
    )
    enrolled_count = admitted_qs.filter(pk__in=enrolled_ids).count()
    enrolment_pending = max(admitted_total - enrolled_count, 0)

    # Monthly application trend (last 6 months)
    six_months_ago = (timezone.localdate().replace(day=1) - timedelta(days=150)).replace(day=1)
    app_months = list(
        apps.filter(created_at__date__gte=six_months_ago)
        .annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(count=Count("id"))
        .order_by("month")
    )
    monthly_applications = [
        {
            "month": r["month"].strftime("%b %Y") if r["month"] else "—",
            "count": int(r["count"] or 0),
        }
        for r in app_months
        if r["month"]
    ]

    # Monthly SchoolPay / ledger collections (Completed)
    ledger_months = list(
        TuitionLedger.objects.filter(
            transaction_completion_status__iexact="Completed",
            payment_date_time__date__gte=six_months_ago,
        )
        .annotate(month=TruncMonth("payment_date_time"))
        .values("month")
        .annotate(count=Count("id"), amount=Sum("amount"))
        .order_by("month")
    )
    monthly_collections = []
    for r in ledger_months:
        if not r["month"]:
            continue
        amt = Decimal(r["amount"] or 0)
        monthly_collections.append(
            {
                "month": r["month"].strftime("%b %Y"),
                "transactions": int(r["count"] or 0),
                "amount": amt,
                "amount_display": _money(amt),
            }
        )

    # Payment size distribution vs exact commitment threshold (ledger sample)
    ledger_week = TuitionLedger.objects.filter(
        transaction_completion_status__iexact="Completed",
        payment_date_time__date__gte=week_start,
        payment_date_time__date__lte=week_end,
    )
    tx_week = ledger_week.count()
    exact_commitment = ledger_week.filter(amount=threshold).count()
    above_commitment = ledger_week.filter(amount__gt=threshold).count()
    payment_size = {
        "week_transactions": tx_week,
        "exact_commitment_count": exact_commitment,
        "exact_commitment_pct": _pct(exact_commitment, tx_week),
        "above_commitment_count": above_commitment,
        "above_commitment_pct": _pct(above_commitment, tx_week),
        "threshold_display": _money(threshold),
    }

    # Leaders / risks
    top_faculty_admissions = by_faculty[0]["name"] if by_faculty else "—"
    top_faculty_collections = (
        max(by_faculty, key=lambda r: r["amount"])["name"] if by_faculty else "—"
    )
    lowest_rate_faculty = (
        min(by_faculty, key=lambda r: (r["collection_rate"], -r["not_paid"]))
        if by_faculty
        else None
    )
    largest_unpaid_faculty = (
        max(by_faculty, key=lambda r: r["not_paid"]) if by_faculty else None
    )

    observations = []
    observations.append(
        f"{admitted_total:,} admitted students are in scope; "
        f"{paid_total:,} ({collection_rate}%) have met the commitment fee and "
        f"{not_paid_total:,} have not."
    )
    observations.append(
        f"Total commitment-related collections recorded: {_money(total_collected)}. "
        f"Estimated revenue at risk (unpaid × {_money(threshold)}): {_money(revenue_at_risk)}."
    )
    if top_faculty_admissions != "—":
        observations.append(
            f"{top_faculty_admissions} leads in admissions volume; "
            f"{top_faculty_collections} leads in commitment amounts collected."
        )
    if lowest_rate_faculty and lowest_rate_faculty["admitted"] > 0:
        observations.append(
            f"Lowest collection rate: {lowest_rate_faculty['name']} "
            f"({lowest_rate_faculty['collection_rate']}% — "
            f"{lowest_rate_faculty['not_paid']} unpaid)."
        )
    if largest_unpaid_faculty and largest_unpaid_faculty["not_paid"] > 0:
        observations.append(
            f"Largest unpaid headcount: {largest_unpaid_faculty['name']} "
            f"({largest_unpaid_faculty['not_paid']} students)."
        )
    if len(monthly_collections) >= 2:
        prev_a = monthly_collections[-2]["amount"]
        curr_a = monthly_collections[-1]["amount"]
        if curr_a > prev_a:
            observations.append(
                f"Collections rose in {monthly_collections[-1]['month']} vs "
                f"{monthly_collections[-2]['month']}."
            )
        elif curr_a < prev_a:
            observations.append(
                f"Collections fell in {monthly_collections[-1]['month']} vs "
                f"{monthly_collections[-2]['month']} — review follow-up cadence."
            )
    if payment_size["week_transactions"]:
        observations.append(
            f"This week, {payment_size['exact_commitment_pct']}% of completed ledger "
            f"transactions were exactly {_money(threshold)} (minimum commitment)."
        )

    recommendations = [
        "Prioritise follow-up calls/SMS for faculties with the lowest collection rates and largest unpaid headcounts.",
        "Set a clear commitment-fee payment deadline for the current intake and communicate it via portal + SMS.",
        "Reconcile admission_fee_paid flags weekly against SchoolPay ledger so the bursar report and bonafide list stay aligned.",
        "Monitor weekly collection velocity (transactions and amount) and escalate if week-on-week collections decline.",
        "Ensure newly admitted students receive pay codes promptly so commitment payments can be matched automatically.",
    ]

    risk_statement = (
        f"Revenue at risk from unpaid commitment fees is approximately {_money(revenue_at_risk)} "
        f"({not_paid_total:,} students × {_money(threshold)})."
    )

    reconciliation_note = (
        f"Paid headcount uses admission_fee_paid ({paid_total:,} students). "
        f"Amount collected uses commitment UGX annotations ({_money(total_collected)}). "
        "If these feel out of sync, run SchoolPay sync / sync_commitment_flags — "
        "timing differences between ledger and flags are expected until flags catch up."
    )

    intake_label = (settings_row.intake_label or "").strip() or "Current admitted cohort"

    exec_paragraphs = [
        (
            f"As of {timezone.localtime().strftime('%d %b %Y %H:%M')}, {uni} has "
            f"{admitted_total:,} admitted students in the bursar commitment cohort "
            f"({intake_label}). {paid_total:,} ({collection_rate}%) have paid the commitment fee; "
            f"{not_paid_total:,} ({_pct(not_paid_total, admitted_total)}%) have not."
        ),
        (
            f"Commitment-related collections total {_money(total_collected)}. "
            f"{top_faculty_admissions} leads admissions volume; "
            f"{top_faculty_collections} leads amounts collected."
        ),
        risk_statement,
    ]

    return {
        "university_name": uni,
        "report_title": "Weekly Admissions & Commitment Fee Status Report",
        "prepared_for": "The Bursar",
        "intake_label": intake_label,
        "report_date": timezone.localdate().strftime("%d %b %Y"),
        "data_as_of": timezone.localtime().strftime("%d %b %Y %H:%M %Z"),
        "week_start": week_start.strftime("%d %b %Y"),
        "week_end": week_end.strftime("%d %b %Y"),
        "threshold": threshold,
        "threshold_display": _money(threshold),
        "applications_received_week": applications_received,
        "applications_pending": pending,
        "admitted_total": admitted_total,
        "paid_total": paid_total,
        "not_paid_total": not_paid_total,
        "collection_rate": collection_rate,
        "total_collected": total_collected,
        "total_collected_display": _money(total_collected),
        "revenue_at_risk": revenue_at_risk,
        "revenue_at_risk_display": _money(revenue_at_risk),
        "risk_statement": risk_statement,
        "reconciliation_note": reconciliation_note,
        "exec_paragraphs": exec_paragraphs,
        "by_faculty": by_faculty,
        "by_campus": by_campus,
        "by_gender": by_gender,
        "by_level": by_level,
        "local_count": local,
        "international_count": international,
        "enrolled_count": enrolled_count,
        "enrolment_pending": enrolment_pending,
        "monthly_applications": monthly_applications,
        "monthly_collections": monthly_collections,
        "payment_size": payment_size,
        "observations": observations[:6],
        "recommendations": recommendations,
        "top_faculty_admissions": top_faculty_admissions,
        "top_faculty_collections": top_faculty_collections,
        "source_note": (
            "Generated from live NDU portal data (AdmittedStudent.admission_fee_paid, "
            "commitment UGX annotations, Application pipeline, TuitionLedger)."
        ),
    }
