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
from payments.commitment_queryset import annotate_commitment_ugx_paid, filter_by_commitment_met
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


def _admitted_base(*, batch_id: int | None = None, exclude_legacy_imports: bool = False):
    qs = AdmittedStudent.objects.filter(is_admitted=True)
    if batch_id:
        qs = qs.filter(admitted_batch_id=batch_id)
    if exclude_legacy_imports:
        # Bulk-imported continuing students mistakenly tagged onto a live intake
        # must not inflate that intake's bursar figures.
        qs = qs.exclude(application__source="legacy_import")
    return qs


def _batch_label(batch) -> str:
    if batch is None:
        return "All admitted cohorts"
    if getattr(batch, "academic_year", None):
        return f"{batch.name} ({batch.academic_year})"
    return batch.name or f"Batch {batch.pk}"


def build_bursar_weekly_metrics(
    *,
    reference: date | None = None,
    batch_id: int | None = None,
    use_settings_batch: bool = True,
) -> dict[str, Any]:
    """
    Build report metrics from the live portal DB.

    Paid / not-paid headcounts use the same strict commitment check as
    Tuition Ledger → Download paid/unpaid CSV (portal + SchoolPay ledger math,
    not only the admission_fee_paid flag).

    Registration-ready = semester tuition % met (RegistrationSettings threshold,
    typically 60%).

    Pass batch_id to scope to one admission intake. If batch_id is None and
    use_settings_batch is True, fall back to settings.report_batch.

    This report is always scoped to one specific intake — never a blended
    "all cohorts" total. Resolution order: explicit batch_id → saved
    settings.report_batch → the currently active admission intake. Only
    when the system has no Batch rows at all does the report fall back to
    every admitted student (empty-system edge case).
    """
    from admissions.models import Batch
    from payments.tuition_pct_queryset import (
        filter_by_tuition_pct_met,
        registration_min_tuition_pct,
    )

    week_start, week_end = week_bounds_for(reference)
    settings_row = BursarWeeklyReportSettings.get_solo()
    threshold = COMMITMENT_FEE_THRESHOLD
    uni = get_university_display_name()
    min_reg_pct = registration_min_tuition_pct()

    batch = None
    if batch_id:
        batch = Batch.objects.filter(pk=batch_id).first()
        if batch is None:
            raise ValueError(f"Admission batch id={batch_id} was not found.")
    elif use_settings_batch and getattr(settings_row, "report_batch_id", None):
        batch = settings_row.report_batch
        batch_id = settings_row.report_batch_id

    if batch is None:
        # Never blend cohorts — default to the currently active intake.
        batch = Batch.objects.filter(is_active=True).order_by("-id").first()
        if batch is not None:
            batch_id = batch.id

    # When scoped to a LIVE intake, legacy-imported (bulk migration) rows are
    # excluded — they belong to the Continuing / Legacy intake, and counting
    # them here inflates the live intake's numbers. When the report is scoped
    # to an inactive intake (e.g. Continuing / Legacy itself), they count.
    scoped_to_live_intake = bool(batch is not None and batch.is_active)

    apps_all = Application.objects.exclude(status="draft")
    apps = apps_all.filter(batch_id=batch_id) if batch_id else apps_all
    if scoped_to_live_intake:
        apps = apps.exclude(source="legacy_import")
    apps_week = apps.filter(created_at__date__gte=week_start, created_at__date__lte=week_end)
    applications_received = apps_week.count()
    applications_total = apps.count()
    pending = apps.filter(status__in=["submitted", "under_review"]).count()

    admitted_qs = _admitted_base(
        batch_id=batch_id, exclude_legacy_imports=scoped_to_live_intake
    )
    admitted_total = admitted_qs.count()
    # Same definition as AdminTuitionLedgerStudentsExportView (strict=True):
    # portal + SchoolPay ledger credits >= threshold (not the admission_fee_paid flag alone).
    # annotate fallback covers SQLite (Exists+Sum HAVING breaks there); Postgres uses strict.
    try:
        paid_id_set = set(
            filter_by_commitment_met(admitted_qs, True, strict=True).values_list("id", flat=True)
        )
        not_paid_total = filter_by_commitment_met(admitted_qs, False, strict=True).count()
    except Exception:
        _ann = annotate_commitment_ugx_paid(admitted_qs)
        _met = Q(commitment_paid_ugx__gte=threshold)
        paid_id_set = set(_ann.filter(_met).values_list("id", flat=True))
        not_paid_total = _ann.exclude(_met).count()
    paid_total = len(paid_id_set)
    collection_rate = _pct(paid_total, admitted_total)
    revenue_at_risk = Decimal(not_paid_total) * threshold

    # Ready for registration: configured semester tuition % (e.g. 60%+)
    try:
        ready_qs = filter_by_tuition_pct_met(admitted_qs, True)
        ready_id_set = set(ready_qs.values_list("id", flat=True))
    except Exception:
        ready_id_set = set(
            admitted_qs.filter(
                registration_tuition_pct_met=True,
                registration_tuition_pct_at__isnull=False,
            ).values_list("id", flat=True)
        )
    registration_ready_total = len(ready_id_set)
    registration_not_ready_total = max(admitted_total - registration_ready_total, 0)
    registration_ready_rate = _pct(registration_ready_total, admitted_total)
    batch_scope_label = _batch_label(batch)

    from admissions.temporary_access import count_active_temporary_passes

    temporary_access_active_total = count_active_temporary_passes(admitted_qs)

    annotated = annotate_commitment_ugx_paid(admitted_qs)
    paid_filter = Q(pk__in=paid_id_set) if paid_id_set else Q(pk__in=[])
    total_collected = (
        annotated.filter(paid_filter).aggregate(s=Sum("commitment_paid_ugx"))["s"]
        or Decimal("0")
    )
    flag_paid_total = admitted_qs.filter(admission_fee_paid=True).count()
    flag_without_ledger = admitted_qs.filter(admission_fee_paid=True).exclude(
        pk__in=paid_id_set
    ).count() if paid_id_set else admitted_qs.filter(admission_fee_paid=True).count()
    ledger_without_flag = (
        admitted_qs.filter(pk__in=paid_id_set, admission_fee_paid=False).count()
        if paid_id_set
        else 0
    )

    # Faculty / campus / batch paid headcounts from the same paid_id_set (avoids SQL Count quirks).
    faculty_totals: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"admitted": 0, "paid": 0, "amount": Decimal("0")}
    )
    campus_totals: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"admitted": 0, "paid": 0, "amount": Decimal("0")}
    )
    batch_totals: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "admitted": 0,
            "paid": 0,
            "registration_ready": 0,
            "amount": Decimal("0"),
            "batch_id": None,
        }
    )
    for row in annotated.values(
        "id",
        "admitted_program__faculty__name",
        "admitted_campus__name",
        "admitted_batch_id",
        "admitted_batch__name",
        "admitted_batch__academic_year",
        "commitment_paid_ugx",
    ):
        fac = _safe_name(row["admitted_program__faculty__name"])
        camp = _safe_name(row["admitted_campus__name"])
        bname = row["admitted_batch__name"]
        byear = row["admitted_batch__academic_year"]
        if bname:
            batch_key = f"{bname} ({byear})" if byear else bname
        else:
            batch_key = "Unassigned batch"
        sid = row["id"]
        amt = Decimal(row["commitment_paid_ugx"] or 0)
        faculty_totals[fac]["admitted"] += 1
        campus_totals[camp]["admitted"] += 1
        batch_totals[batch_key]["admitted"] += 1
        batch_totals[batch_key]["batch_id"] = row["admitted_batch_id"]
        if sid in paid_id_set:
            faculty_totals[fac]["paid"] += 1
            campus_totals[camp]["paid"] += 1
            batch_totals[batch_key]["paid"] += 1
            faculty_totals[fac]["amount"] += amt
            campus_totals[camp]["amount"] += amt
            batch_totals[batch_key]["amount"] += amt
        if sid in ready_id_set:
            batch_totals[batch_key]["registration_ready"] += 1

    by_faculty = []
    for name, totals in sorted(faculty_totals.items(), key=lambda x: -x[1]["admitted"]):
        admitted = int(totals["admitted"])
        paid = int(totals["paid"])
        not_paid = max(admitted - paid, 0)
        amount = Decimal(totals["amount"] or 0)
        by_faculty.append(
            {
                "name": name,
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

    by_campus = []
    for name, totals in sorted(campus_totals.items(), key=lambda x: -x[1]["admitted"]):
        admitted = int(totals["admitted"])
        paid = int(totals["paid"])
        not_paid = max(admitted - paid, 0)
        amount = Decimal(totals["amount"] or 0)
        by_campus.append(
            {
                "name": name,
                "admitted": admitted,
                "paid": paid,
                "not_paid": not_paid,
                "collection_rate": _pct(paid, admitted),
                "amount": amount,
                "amount_display": _money(amount),
            }
        )

    by_batch = []
    for name, totals in sorted(batch_totals.items(), key=lambda x: -x[1]["admitted"]):
        admitted = int(totals["admitted"])
        paid = int(totals["paid"])
        not_paid = max(admitted - paid, 0)
        reg_ready = int(totals["registration_ready"])
        amount = Decimal(totals["amount"] or 0)
        by_batch.append(
            {
                "name": name,
                "batch_id": totals["batch_id"],
                "admitted": admitted,
                "paid": paid,
                "not_paid": not_paid,
                "collection_rate": _pct(paid, admitted),
                "registration_ready": reg_ready,
                "registration_ready_rate": _pct(reg_ready, admitted),
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
    ledger_base = TuitionLedger.objects.filter(
        transaction_completion_status__iexact="Completed",
    )
    if batch_id:
        ledger_base = ledger_base.filter(student_id__in=admitted_qs.values("id"))
    ledger_months = list(
        ledger_base.filter(payment_date_time__date__gte=six_months_ago)
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
    ledger_week = ledger_base.filter(
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
        f"{applications_total:,} total applicants for {batch_scope_label}; "
        f"{admitted_total:,} admitted, {paid_total:,} ({collection_rate}%) have paid "
        f"commitment fees and {not_paid_total:,} have not yet paid."
    )
    observations.append(
        f"{registration_ready_total:,} ({registration_ready_rate}%) are ready for registration "
        f"(≥ {min_reg_pct:g}% semester tuition paid); "
        f"{registration_not_ready_total:,} are not yet at that threshold."
    )
    if temporary_access_active_total:
        observations.append(
            f"{temporary_access_active_total:,} student(s) currently hold an active temporary "
            "access pass (sponsored / pending settlement — cleared by Bursar only)."
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
        f"Paid headcount uses portal + SchoolPay ledger credits >= {_money(threshold)} "
        f"({paid_total:,} students) — same as Tuition Ledger paid export. "
        f"Flag-only count (admission_fee_paid) is {flag_paid_total:,}"
        f"{f' ({flag_without_ledger:,} flagged without ledger proof)' if flag_without_ledger else ''}"
        f"{f'; {ledger_without_flag:,} paid in ledger but flag still false' if ledger_without_flag else ''}. "
        f"Run sync_commitment_flags to backfill missing flags. "
        f"Amount collected sums commitment UGX for ledger-paid students "
        f"({_money(total_collected)})."
    )

    custom_intake = (settings_row.intake_label or "").strip()
    intake_label = custom_intake or batch_scope_label

    exec_paragraphs = [
        (
            f"As of {timezone.localtime().strftime('%d %b %Y %H:%M')}, {uni} received "
            f"{applications_total:,} applications for {intake_label}, with "
            f"{admitted_total:,} admitted. "
            f"{paid_total:,} ({collection_rate}%) have paid commitment fees; "
            f"{not_paid_total:,} ({_pct(not_paid_total, admitted_total)}%) have not yet paid."
        ),
        (
            f"{registration_ready_total:,} ({registration_ready_rate}%) are ready for registration "
            f"(≥ {min_reg_pct:g}% semester tuition). "
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
        "batch_id": batch_id,
        "batch_scope_label": batch_scope_label,
        "report_date": timezone.localdate().strftime("%d %b %Y"),
        "data_as_of": timezone.localtime().strftime("%d %b %Y %H:%M %Z"),
        "week_start": week_start.strftime("%d %b %Y"),
        "week_end": week_end.strftime("%d %b %Y"),
        "threshold": threshold,
        "threshold_display": _money(threshold),
        "min_registration_tuition_pct": min_reg_pct,
        "applications_received_week": applications_received,
        "applications_total": applications_total,
        "applications_pending": pending,
        "admitted_total": admitted_total,
        "paid_total": paid_total,
        "not_paid_total": not_paid_total,
        "collection_rate": collection_rate,
        "registration_ready_total": registration_ready_total,
        "registration_not_ready_total": registration_not_ready_total,
        "registration_ready_rate": registration_ready_rate,
        "temporary_access_active_total": temporary_access_active_total,
        "total_collected": total_collected,
        "total_collected_display": _money(total_collected),
        "revenue_at_risk": revenue_at_risk,
        "revenue_at_risk_display": _money(revenue_at_risk),
        "risk_statement": risk_statement,
        "reconciliation_note": reconciliation_note,
        "exec_paragraphs": exec_paragraphs,
        "by_faculty": by_faculty,
        "by_campus": by_campus,
        "by_batch": by_batch,
        "by_gender": by_gender,
        "by_level": by_level,
        "local_count": local,
        "international_count": international,
        "enrolled_count": enrolled_count,
        "enrolment_pending": enrolment_pending,
        "monthly_applications": monthly_applications,
        "monthly_collections": monthly_collections,
        "payment_size": payment_size,
        "observations": observations[:7],
        "recommendations": recommendations,
        "top_faculty_admissions": top_faculty_admissions,
        "top_faculty_collections": top_faculty_collections,
        "source_note": (
            "Generated from live NDU portal data, scoped to one specific admission intake "
            "(never a blended total across intakes). "
            + (
                "Legacy-imported (bulk migration) students are excluded from this live "
                "intake's figures — they are reported under Continuing / Legacy Students. "
                if scoped_to_live_intake
                else ""
            )
            + "Commitment paid = portal + SchoolPay ledger ≥ commitment threshold. "
            "Registration-ready = semester tuition % ≥ RegistrationSettings minimum "
            f"({min_reg_pct:g}%, configured in Registration Settings)."
        ),
        "flag_paid_total": flag_paid_total,
        "flag_without_ledger": flag_without_ledger,
        "ledger_without_flag": ledger_without_flag,
    }
