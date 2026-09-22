"""Admitted students who have paid the commitment fee (UGX 150,000+) by programme."""
from __future__ import annotations

from typing import Any

from django.db.models import Count, Q, Sum

from admissions.faculty_scope import filter_admitted_students_for_user
from admissions.models import AdmittedStudent, Batch
from payments.commitment_queryset import annotate_commitment_ugx_paid
from payments.student_payment_allocation import COMMITMENT_FEE_THRESHOLD


def _student_name(student: AdmittedStudent) -> str:
    app = getattr(student, "application", None)
    if not app:
        return "—"
    parts = [app.first_name or "", app.middle_name or "", app.last_name or ""]
    name = " ".join(p.strip() for p in parts if p and p.strip())
    return name or "—"


def commitment_fee_report_filter_options(user) -> dict[str, Any]:
    from accounts.models import Campus
    from Programs.models import Program

    scoped = filter_admitted_students_for_user(
        AdmittedStudent.objects.filter(is_admitted=True),
        user,
    )
    program_ids = (
        scoped.exclude(admitted_program_id=None)
        .values_list("admitted_program_id", flat=True)
        .distinct()
    )
    programs = list(
        Program.objects.filter(pk__in=program_ids)
        .order_by("name")
        .values("id", "name", "code")
    )
    campuses = list(Campus.objects.order_by("name").values("id", "name"))
    intakes = list(
        Batch.objects.order_by("-academic_year", "name").values(
            "id", "name", "academic_year", "is_active"
        )
    )
    return {
        "programs": programs,
        "campuses": campuses,
        "intakes": intakes,
        "commitment_threshold": float(COMMITMENT_FEE_THRESHOLD),
    }


def _apply_filters(qs, params: dict[str, Any]):
    program_id = params.get("program_id")
    campus_id = params.get("campus_id")
    batch_id = params.get("batch_id")
    search = (params.get("search") or "").strip()

    if program_id:
        qs = qs.filter(admitted_program_id=program_id)
    if campus_id:
        qs = qs.filter(admitted_campus_id=campus_id)
    if batch_id:
        qs = qs.filter(admitted_batch_id=batch_id)

    if search:
        tokens = [t for t in search.split() if t]
        name_q = Q()
        for token in tokens:
            name_q &= (
                Q(application__first_name__icontains=token)
                | Q(application__middle_name__icontains=token)
                | Q(application__last_name__icontains=token)
            )
        qs = qs.filter(
            name_q
            | Q(reg_no__icontains=search)
            | Q(student_id__icontains=search)
            | Q(schoolpay_code__icontains=search)
            | Q(admitted_program__name__icontains=search)
            | Q(admitted_program__code__icontains=search)
        )
    return qs


def build_commitment_fee_report(user, params: dict[str, Any]) -> dict[str, Any]:
    """
    Admitted students whose portal + SchoolPay credits total at least the
    commitment threshold (UGX 150,000) — i.e. commitment met / tuition paid ≥ 150k.
    """
    base = (
        AdmittedStudent.objects.filter(is_admitted=True)
        .exclude(application__is_revoked=True)
        .select_related(
            "application",
            "admitted_program",
            "admitted_program__faculty",
            "admitted_campus",
            "admitted_batch",
        )
    )
    base = filter_admitted_students_for_user(base, user)
    base = annotate_commitment_ugx_paid(base)
    paid = base.filter(commitment_paid_ugx__gte=COMMITMENT_FEE_THRESHOLD)
    paid = _apply_filters(paid, params)

    by_program_qs = (
        paid.values(
            "admitted_program_id",
            "admitted_program__name",
            "admitted_program__code",
            "admitted_program__faculty__name",
        )
        .annotate(
            students_count=Count("id"),
            total_paid_ugx=Sum("commitment_paid_ugx"),
        )
        .order_by("admitted_program__name")
    )

    by_program = []
    for row in by_program_qs:
        by_program.append(
            {
                "program_id": row["admitted_program_id"],
                "program": row["admitted_program__name"] or "—",
                "program_code": row["admitted_program__code"] or "",
                "faculty": row["admitted_program__faculty__name"] or "—",
                "students_count": int(row["students_count"] or 0),
                "total_paid_ugx": float(row["total_paid_ugx"] or 0),
            }
        )

    by_program = _filter_and_sort_programmes(by_program, params)

    # When programme student-count filters are on, limit student rows to matching programmes.
    if params.get("min_students") is not None or params.get("max_students") is not None:
        program_ids = {
            row["program_id"] for row in by_program if row.get("program_id") is not None
        }
        if program_ids:
            paid = paid.filter(admitted_program_id__in=program_ids)
        else:
            paid = paid.none()

    agg = paid.aggregate(
        students_count=Count("id"),
        total_paid_ugx=Sum("commitment_paid_ugx"),
    )
    students_count = int(agg["students_count"] or 0)
    total_paid = float(agg["total_paid_ugx"] or 0)

    students = []
    for student in paid.order_by(
        "admitted_program__name",
        "application__last_name",
        "application__first_name",
        "id",
    ):
        paid_ugx = float(getattr(student, "commitment_paid_ugx", None) or 0)
        program = student.admitted_program
        campus = student.admitted_campus
        batch = student.admitted_batch
        students.append(
            {
                "student_pk": student.pk,
                "name": _student_name(student),
                "student_id": student.student_id or "",
                "reg_no": student.reg_no or "",
                "schoolpay_code": student.schoolpay_code or "",
                "program_id": program.pk if program else None,
                "program": program.name if program else "—",
                "program_code": getattr(program, "code", "") or "",
                "faculty": (
                    program.faculty.name
                    if program and getattr(program, "faculty_id", None)
                    else "—"
                ),
                "campus": campus.name if campus else "—",
                "intake": batch.name if batch else "—",
                "academic_year": (batch.academic_year if batch else "") or "",
                "paid_ugx": paid_ugx,
                "commitment_threshold": float(COMMITMENT_FEE_THRESHOLD),
                "commitment_met": paid_ugx >= float(COMMITMENT_FEE_THRESHOLD),
                "admission_fee_paid": bool(student.admission_fee_paid),
                "admission_fee_paid_at": (
                    student.admission_fee_paid_at.isoformat()
                    if student.admission_fee_paid_at
                    else None
                ),
            }
        )

    programme_students = sum(int(r["students_count"] or 0) for r in by_program)
    programme_paid = sum(float(r["total_paid_ugx"] or 0) for r in by_program)

    return {
        "totals": {
            "students_count": students_count,
            "programs_count": len(by_program),
            "total_paid_ugx": total_paid,
            "commitment_threshold": float(COMMITMENT_FEE_THRESHOLD),
            "programme_students_count": programme_students,
            "programme_total_paid_ugx": programme_paid,
        },
        "by_program": by_program,
        "students": students,
    }


def _filter_and_sort_programmes(rows: list[dict], params: dict[str, Any]) -> list[dict]:
    """Filter by student headcount and sort by students / total paid / name."""
    min_students = params.get("min_students")
    max_students = params.get("max_students")
    sort = (params.get("program_sort") or "name").strip().lower()

    filtered = rows
    if min_students is not None:
        filtered = [r for r in filtered if int(r.get("students_count") or 0) >= int(min_students)]
    if max_students is not None:
        filtered = [r for r in filtered if int(r.get("students_count") or 0) <= int(max_students)]

    if sort == "students_asc":
        filtered.sort(key=lambda r: (int(r.get("students_count") or 0), r.get("program") or ""))
    elif sort == "students_desc":
        filtered.sort(
            key=lambda r: (-int(r.get("students_count") or 0), r.get("program") or "")
        )
    elif sort == "paid_asc":
        filtered.sort(key=lambda r: (float(r.get("total_paid_ugx") or 0), r.get("program") or ""))
    elif sort == "paid_desc":
        filtered.sort(
            key=lambda r: (-float(r.get("total_paid_ugx") or 0), r.get("program") or "")
        )
    else:
        filtered.sort(key=lambda r: (r.get("program") or "").lower())

    return filtered
