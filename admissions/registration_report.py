"""Registration census: admitted vs reported vs registered, clearance, temp passes, scholarships."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db.models import Count, Q, Sum

from admissions.models import AdmittedStudent, Batch, TemporaryAccessPass


def _pct(part: int, whole: int) -> float | None:
    if not whole:
        return None
    return round(100.0 * part / whole, 1)


def _student_name(student: AdmittedStudent) -> str:
    app = getattr(student, "application", None)
    if not app:
        return "—"
    parts = [app.first_name or "", app.middle_name or "", app.last_name or ""]
    name = " ".join(p.strip() for p in parts if p and p.strip())
    return name or "—"


def _officer_name(user) -> str:
    if not user:
        return ""
    return (
        (getattr(user, "full_name", None) or "").strip()
        or (user.get_full_name() or "").strip()
        or user.username
        or user.email
        or ""
    )


def _cleared_student_rows(qs) -> list[dict[str, Any]]:
    students = (
        qs.filter(accounts_registration_cleared=True)
        .select_related(
            "application",
            "admitted_program",
            "admitted_campus",
            "accounts_registration_cleared_by",
        )
        .order_by("application__last_name", "application__first_name", "id")
    )
    rows = []
    for s in students.iterator(chunk_size=500):
        rows.append(
            {
                "student_pk": s.pk,
                "name": _student_name(s),
                "student_id": s.student_id or "",
                "reg_no": s.reg_no or "",
                "campus": s.admitted_campus.name if s.admitted_campus_id else "—",
                "program": s.admitted_program.name if s.admitted_program_id else "—",
                "cleared_by": _officer_name(s.accounts_registration_cleared_by),
            }
        )
    return rows


def _identity_student_rows(qs) -> list[dict[str, Any]]:
    students = qs.select_related(
        "application",
        "admitted_program",
        "admitted_campus",
    ).order_by("application__last_name", "application__first_name", "id")
    rows = []
    for s in students.iterator(chunk_size=500):
        rows.append(
            {
                "student_pk": s.pk,
                "name": _student_name(s),
                "student_id": s.student_id or "",
                "reg_no": s.reg_no or "",
                "campus": s.admitted_campus.name if s.admitted_campus_id else "—",
                "program": s.admitted_program.name if s.admitted_program_id else "—",
                "is_registered": bool(s.is_registered),
            }
        )
    return rows


def _verified_student_rows(qs) -> list[dict[str, Any]]:
    """Desk-verified students — same definition as the verified registration roster."""
    students = (
        qs.filter(physical_documents_verified=True)
        .select_related(
            "application",
            "admitted_program",
            "admitted_campus",
            "physical_documents_verified_by",
        )
        .order_by("application__last_name", "application__first_name", "id")
    )
    rows = []
    for s in students.iterator(chunk_size=500):
        verified_at = s.physical_documents_verified_at
        rows.append(
            {
                "student_pk": s.pk,
                "name": _student_name(s),
                "student_id": s.student_id or "",
                "reg_no": s.reg_no or "",
                "campus": s.admitted_campus.name if s.admitted_campus_id else "—",
                "program": s.admitted_program.name if s.admitted_program_id else "—",
                "verified_by": _officer_name(s.physical_documents_verified_by),
                "verified_at": verified_at.isoformat() if verified_at else None,
                "is_registered": bool(s.is_registered),
            }
        )
    return rows


def _total_reported_student_rows(
    qs, temp_ids: set[int], sch_ids: set[int]
) -> list[dict[str, Any]]:
    students = qs.select_related(
        "application",
        "admitted_program",
        "admitted_campus",
        "accounts_registration_cleared_by",
    ).order_by("application__last_name", "application__first_name", "id")
    rows = []
    for s in students.iterator(chunk_size=500):
        rows.append(
            {
                "student_pk": s.pk,
                "name": _student_name(s),
                "student_id": s.student_id or "",
                "reg_no": s.reg_no or "",
                "campus": s.admitted_campus.name if s.admitted_campus_id else "—",
                "program": s.admitted_program.name if s.admitted_program_id else "—",
                "accounts_cleared": bool(s.accounts_registration_cleared),
                "cleared_by": _officer_name(s.accounts_registration_cleared_by),
                "temp_pass": s.pk in temp_ids,
                "scholarship": s.pk in sch_ids,
                "is_registered": bool(s.is_registered),
            }
        )
    return rows


def _enrolled_student_rows(qs) -> list[dict[str, Any]]:
    students = (
        qs.filter(programme_enrollment__status="enrolled")
        .select_related(
            "application",
            "admitted_program",
            "admitted_campus",
            "programme_enrollment",
            "programme_enrollment__program_batch",
        )
        .order_by("application__last_name", "application__first_name", "id")
    )
    rows = []
    for s in students.iterator(chunk_size=500):
        spe = getattr(s, "programme_enrollment", None)
        rows.append(
            {
                "student_pk": s.pk,
                "name": _student_name(s),
                "student_id": s.student_id or "",
                "reg_no": s.reg_no or "",
                "campus": s.admitted_campus.name if s.admitted_campus_id else "—",
                "program": s.admitted_program.name if s.admitted_program_id else "—",
                "year_of_study": int(getattr(spe, "current_year_of_study", 0) or 0),
                "term": int(getattr(spe, "current_term_number", 0) or 0),
                "cohort": (
                    spe.program_batch.name
                    if spe is not None and spe.program_batch_id
                    else "—"
                ),
                "is_registered": bool(s.is_registered),
            }
        )
    return rows


def active_intake():
    return Batch.objects.filter(is_active=True).order_by("-academic_year", "-id").first()


DATE_FIELD_MAP = {
    "admission": "admission_date",
    "registered": "registration_date",
    "cleared": "accounts_registration_cleared_at",
    "verified": "physical_documents_verified_at",
}


def apply_roster_slice(qs, params: dict[str, Any]):
    """Year / period / campus / faculty / programme slice used by the verified roster."""
    academic_year = (params.get("academic_year") or "").strip()
    admission_period = (params.get("admission_period") or "").strip()
    campus_id = params.get("campus_id")
    faculty_id = params.get("faculty_id")
    program_id = params.get("program_id")
    if academic_year:
        qs = qs.filter(admitted_batch__academic_year=academic_year)
    if admission_period:
        qs = qs.filter(admitted_batch__name__icontains=admission_period)
    if campus_id:
        qs = qs.filter(admitted_campus_id=campus_id)
    if faculty_id:
        qs = qs.filter(admitted_program__faculty_id=faculty_id)
    if program_id:
        qs = qs.filter(admitted_program_id=program_id)
    return qs


def desk_reported_queryset(params: dict[str, Any]):
    """Verified registration roster: admitted + desk documents verified. No user/date scope."""
    qs = AdmittedStudent.objects.filter(
        is_admitted=True,
        physical_documents_verified=True,
    )
    return apply_roster_slice(qs, params).order_by()


def _apply_report_filters(qs, params: dict[str, Any]):
    academic_year = (params.get("academic_year") or "").strip()
    batch_id = params.get("batch_id")
    admission_period = (params.get("admission_period") or "").strip()
    campus_id = params.get("campus_id")
    faculty_id = params.get("faculty_id")
    from_date = params.get("from_date")
    to_date = params.get("to_date")
    date_basis = (params.get("date_basis") or "cleared").strip().lower()
    date_field = DATE_FIELD_MAP.get(date_basis, "admission_date")
    if batch_id and not admission_period:
        batch = Batch.objects.filter(pk=batch_id).values("name", "academic_year").first()
        if batch:
            admission_period = (batch.get("name") or "").strip()
            if not academic_year:
                academic_year = (batch.get("academic_year") or "").strip()
    slice_params = {
        "academic_year": academic_year,
        "admission_period": admission_period,
        "campus_id": campus_id,
        "faculty_id": faculty_id,
    }
    qs = apply_roster_slice(qs, slice_params)
    if not admission_period and batch_id:
        qs = qs.filter(admitted_batch_id=batch_id)
    if from_date:
        qs = qs.filter(**{f"{date_field}__date__gte": from_date})
    if to_date:
        qs = qs.filter(**{f"{date_field}__date__lte": to_date})
    return qs


def _ledger_paid_by_student(student_ids: list[int]) -> dict[int, Decimal]:
    if not student_ids:
        return {}
    from payments.models import TuitionLedger
    from payments.utils.tuition_ledger_linking import completed_ledger_status_q

    rows = (
        TuitionLedger.objects.filter(student_id__in=student_ids)
        .filter(completed_ledger_status_q())
        .values("student_id")
        .annotate(total=Sum("amount"))
    )
    return {int(r["student_id"]): r["total"] or Decimal("0") for r in rows}


def _breakdown_rows(qs, group_fields: list[str], reported_qs=None) -> list[dict[str, Any]]:
    annotated = (
        qs.order_by()
        .values(*group_fields)
        .annotate(
            admitted=Count("id"),
            enrolled=Count("id", filter=Q(programme_enrollment__status="enrolled")),
            registered=Count("id", filter=Q(is_registered=True)),
            cleared=Count("id", filter=Q(accounts_registration_cleared=True)),
            verified=Count("id", filter=Q(physical_documents_verified=True)),
        )
        .order_by(*group_fields)
    )
    reported_map: dict[tuple, int] = {}
    if reported_qs is not None:
        for item in (
            reported_qs.order_by().values(*group_fields).annotate(n=Count("id"))
        ):
            reported_map[tuple(item[f] for f in group_fields)] = int(item["n"] or 0)
    rows = []
    for item in annotated:
        admitted = int(item["admitted"] or 0)
        registered = int(item["registered"] or 0)
        enrolled = int(item.get("enrolled") or 0)
        cleared = int(item["cleared"] or 0)
        key = tuple(item[f] for f in group_fields)
        verified = int(item["verified"] or 0)
        reported = reported_map.get(key, 0)
        row = {
            "admitted": admitted,
            "reported": reported,
            "reported_pct": _pct(reported, admitted),
            "enrolled": enrolled,
            "enrolled_pct": _pct(enrolled, admitted),
            "registered": registered,
            "registered_pct": _pct(registered, admitted),
            "cleared": cleared,
            "clearance_pct": _pct(cleared, admitted),
            "verified": verified,
            "verified_pct": _pct(verified, admitted),
        }
        for field in group_fields:
            key = field.split("__")[-1] if "__" in field else field
            if field.endswith("__name"):
                parent = field.rsplit("__", 1)[0].split("__")[-1]
                if parent in ("admitted_campus", "campus"):
                    key = "campus"
                elif parent in ("admitted_program", "program"):
                    key = "program"
                elif parent == "faculty":
                    key = "faculty"
                elif parent in ("admitted_batch", "batch"):
                    key = "intake"
            row[key] = item[field] or "—"
        rows.append(row)
    rows.sort(key=lambda r: (-int(r["admitted"]), str(r.get("campus") or r.get("program") or "")))
    return rows


def registration_report_filter_options(user) -> dict[str, Any]:
    from accounts.models import Campus
    from admissions.faculty_scope import filter_faculties_for_user
    from admissions.models import Faculty

    batches = list(Batch.objects.order_by("-academic_year", "name").values("id", "name", "academic_year", "is_active"))
    academic_years = []
    seen = set()
    for b in batches:
        ay = b.get("academic_year") or ""
        if ay and ay not in seen:
            seen.add(ay)
            academic_years.append(ay)
    campuses = list(
        Campus.objects.order_by("name").values("id", "name")
    )
    faculties = list(
        filter_faculties_for_user(
            Faculty.objects.filter(is_active=True).order_by("name"),
            user,
        ).values("id", "name")
    )
    return {
        "academic_years": academic_years,
        "intakes": [
            {
                "id": b["id"],
                "name": b["name"],
                "academic_year": b["academic_year"],
                "is_active": b["is_active"],
            }
            for b in batches
        ],
        "campuses": campuses,
        "faculties": faculties,
    }


def registration_report_queryset(user, params: dict[str, Any]):
    qs = AdmittedStudent.objects.filter(is_admitted=True)
    return _apply_report_filters(qs, params).order_by()


def build_registration_report(user, params: dict[str, Any], *, include_finance: bool) -> dict[str, Any]:
    from payments.models import ScholarshipAward

    base = registration_report_queryset(user, params)
    verified_params = {
        "academic_year": params.get("academic_year") or "",
        "admission_period": params.get("admission_period") or "",
        "campus_id": params.get("campus_id"),
        "faculty_id": params.get("faculty_id"),
    }
    if params.get("batch_id") and not verified_params["admission_period"]:
        batch = Batch.objects.filter(pk=params["batch_id"]).values("name", "academic_year").first()
        if batch:
            verified_params["admission_period"] = (batch.get("name") or "").strip()
            if not verified_params["academic_year"]:
                verified_params["academic_year"] = (batch.get("academic_year") or "").strip()
    verified_qs = desk_reported_queryset(verified_params)

    totals_row = base.aggregate(
        admitted=Count("id"),
        enrolled=Count("id", filter=Q(programme_enrollment__status="enrolled")),
        registered=Count("id", filter=Q(is_registered=True)),
        cleared=Count("id", filter=Q(accounts_registration_cleared=True)),
    )
    admitted = int(totals_row["admitted"] or 0)
    enrolled = int(totals_row["enrolled"] or 0)
    registered = int(totals_row["registered"] or 0)
    cleared = int(totals_row["cleared"] or 0)
    verified = verified_qs.count()

    from django.utils import timezone

    today = timezone.localdate()
    temp_qs = (
        TemporaryAccessPass.objects.filter(
            student_id__in=base.values("pk"),
            status=TemporaryAccessPass.STATUS_ACTIVE,
            valid_from__lte=today,
        )
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))
        .select_related(
            "student__application",
            "student__admitted_program",
            "student__admitted_campus",
            "student__admitted_batch",
            "scholarship_award__programme",
        )
        .order_by("-issued_at", "-id")
    )
    # One row per student (latest pass).
    temp_by_student: dict[int, TemporaryAccessPass] = {}
    for p in temp_qs:
        temp_by_student.setdefault(p.student_id, p)
    temp_passes = list(temp_by_student.values())

    awards = list(
        ScholarshipAward.objects.filter(
            student_id__in=base.values("pk"),
            status=ScholarshipAward.STATUS_ACTIVE,
            programme__is_active=True,
        )
        .select_related(
            "programme",
            "student__application",
            "student__admitted_program",
            "student__admitted_campus",
            "student__admitted_batch",
        )
        .order_by(
            "student__application__last_name",
            "student__application__first_name",
            "programme__name",
        )
    )

    finance_ids = list({p.student_id for p in temp_passes} | {a.student_id for a in awards})
    paid_map: dict[int, Decimal] = _ledger_paid_by_student(finance_ids) if include_finance else {}

    def paid_ugx(student_id: int) -> float | None:
        if not include_finance:
            return None
        return float(paid_map.get(student_id, Decimal("0")))

    temp_rows = []
    for p in temp_passes:
        s = p.student
        award = getattr(p, "scholarship_award", None)
        programme = getattr(award, "programme", None) if award else None
        temp_rows.append(
            {
                "student_pk": s.pk,
                "name": _student_name(s),
                "student_id": s.student_id or "",
                "reg_no": s.reg_no or "",
                "campus": s.admitted_campus.name if s.admitted_campus_id else "—",
                "program": s.admitted_program.name if s.admitted_program_id else "—",
                "intake": s.admitted_batch.name if s.admitted_batch_id else "—",
                "sponsor": p.sponsor_label or (programme.name if programme else "") or "—",
                "valid_until": p.valid_until.isoformat() if p.valid_until else None,
                "tuition_paid_ugx": paid_ugx(s.pk),
            }
        )
    temp_rows.sort(key=lambda r: (r["name"].lower(), r["reg_no"]))

    scholarship_rows = []
    for a in awards:
        s = a.student
        scholarship_rows.append(
            {
                "student_pk": s.pk,
                "name": _student_name(s),
                "student_id": s.student_id or "",
                "reg_no": s.reg_no or "",
                "campus": s.admitted_campus.name if s.admitted_campus_id else "—",
                "program": s.admitted_program.name if s.admitted_program_id else "—",
                "intake": s.admitted_batch.name if s.admitted_batch_id else "—",
                "scholarship_name": a.programme.name if a.programme_id else "—",
                "sponsor": (a.programme.sponsor if a.programme_id else "") or "—",
                "award_amount": float(a.award_amount or 0),
                "tuition_paid_ugx": paid_ugx(s.pk),
            }
        )

    temp_ids = {p.student_id for p in temp_passes}
    sch_ids = {a.student_id for a in awards}
    reported_qs = base.filter(
        Q(accounts_registration_cleared=True)
        | Q(pk__in=temp_ids)
        | Q(pk__in=sch_ids)
    )
    reported = reported_qs.count()

    return {
        "totals": {
            "admitted": admitted,
            "reported": reported,
            "reported_pct": _pct(reported, admitted),
            "enrolled": enrolled,
            "enrolled_pct": _pct(enrolled, admitted),
            "registered": registered,
            "registered_pct": _pct(registered, admitted),
            "cleared": cleared,
            "clearance_pct": _pct(cleared, admitted),
            "verified": verified,
            "verified_pct": _pct(verified, admitted),
            "temporary_passes": len(temp_rows),
            "scholarships": len(scholarship_rows),
        },
        "by_campus": _breakdown_rows(base, ["admitted_campus__name"], reported_qs),
        "by_program": _breakdown_rows(
            base,
            ["admitted_program__faculty__name", "admitted_program__name"],
            reported_qs,
        ),
        "temporary_passes": temp_rows,
        "scholarships": scholarship_rows,
        "reported_students": _total_reported_student_rows(reported_qs, temp_ids, sch_ids),
        "verified_students": _verified_student_rows(verified_qs),
        "enrolled_students": _enrolled_student_rows(base),
        "cleared_students": _cleared_student_rows(base),
        "registered_students": _identity_student_rows(base.filter(is_registered=True)),
        "can_view_finance": include_finance,
    }
