"""Course exemption census: paid, submitted, pending, approved, rejected."""
from __future__ import annotations

from typing import Any

from django.db.models import Count, Q

from admissions.faculty_scope import filter_admitted_students_for_user
from admissions.models import AdmittedStudent, AdmissionChangeRequest


def _student_name(student: AdmittedStudent | None) -> str:
    if not student:
        return "—"
    app = getattr(student, "application", None)
    if not app:
        return "—"
    parts = [app.first_name or "", app.middle_name or "", app.last_name or ""]
    name = " ".join(p.strip() for p in parts if p and p.strip())
    return name or "—"


def _staff_name(user) -> str:
    if not user:
        return ""
    name = (getattr(user, "full_name", None) or "").strip()
    if name:
        return name
    return (user.get_full_name() or "").strip() or user.username or user.email or ""


def _apply_filters(qs, params: dict[str, Any]):
    campus_id = params.get("campus_id")
    faculty_id = params.get("faculty_id")
    status = (params.get("status") or "").strip().lower()
    from_date = params.get("from_date")
    to_date = params.get("to_date")
    if campus_id:
        qs = qs.filter(admitted_student__admitted_campus_id=campus_id)
    if faculty_id:
        qs = qs.filter(admitted_student__admitted_program__faculty_id=faculty_id)
    if status in ("pending", "approved", "rejected"):
        qs = qs.filter(status=status)
    if from_date:
        qs = qs.filter(created_at__date__gte=from_date)
    if to_date:
        qs = qs.filter(created_at__date__lte=to_date)
    return qs


def exemption_report_filter_options(user) -> dict[str, Any]:
    from accounts.models import Campus
    from admissions.faculty_scope import filter_faculties_for_user
    from admissions.models import Faculty

    campuses = list(Campus.objects.order_by("name").values("id", "name"))
    faculties = list(
        filter_faculties_for_user(
            Faculty.objects.filter(is_active=True).order_by("name"),
            user,
        ).values("id", "name")
    )
    return {"campuses": campuses, "faculties": faculties}


def build_exemption_report(user, params: dict[str, Any]) -> dict[str, Any]:
    scoped = filter_admitted_students_for_user(
        AdmittedStudent.objects.filter(is_admitted=True).exclude(application__is_revoked=True),
        user,
    )
    base = (
        AdmissionChangeRequest.objects.filter(
            change_type="exemption",
            admitted_student_id__in=scoped.values("pk"),
        )
        .select_related(
            "admitted_student__application",
            "admitted_student__admitted_program",
            "admitted_student__admitted_campus",
            "admitted_student__admitted_batch",
            "reviewed_by",
            "requested_by",
        )
        .prefetch_related("exemption_lines")
        .order_by("-created_at", "-id")
    )
    base = _apply_filters(base, params)

    totals_row = base.aggregate(
        submitted=Count("id"),
        pending=Count("id", filter=Q(status="pending")),
        approved=Count("id", filter=Q(status="approved")),
        rejected=Count("id", filter=Q(status="rejected")),
    )

    from admissions.exemption_services import exemption_form_fee_report

    all_charges = exemption_form_fee_report(None)
    campus_id = params.get("campus_id")
    faculty_id = params.get("faculty_id")
    from_date = params.get("from_date")
    to_date = params.get("to_date")
    fee_pks = [r.get("student_pk") for r in all_charges if r.get("student_pk")]
    fee_students = {
        s.pk: s
        for s in AdmittedStudent.objects.filter(pk__in=fee_pks).select_related(
            "application", "admitted_program", "admitted_campus", "admitted_batch"
        )
    }
    allowed = set(scoped.values_list("pk", flat=True))

    def _fee_in_scope(r: dict) -> bool:
        pk = r.get("student_pk")
        if pk not in allowed:
            return False
        s = fee_students.get(pk)
        if campus_id and (not s or s.admitted_campus_id != campus_id):
            return False
        if faculty_id and (not s or not s.admitted_program_id or s.admitted_program.faculty_id != faculty_id):
            return False
        charged = (r.get("charged_at") or "")[:10]
        if from_date and charged and charged < from_date.isoformat():
            return False
        if to_date and charged and charged > to_date.isoformat():
            return False
        return True

    def _tracking(r: dict) -> str:
        paid = r.get("status") == "completed" and not r.get("is_waived")
        pending = r.get("status") == "pending" and not r.get("is_waived")
        applied = bool(r.get("change_request_id"))
        if r.get("is_waived"):
            return "waived"
        if paid and applied:
            return "paid_submitted"
        if paid and not applied:
            return "paid_unsubmitted"
        if pending and applied:
            return "submitted_unpaid"
        return "billed_unpaid"

    form_fee_rows = []
    paid_rows = []
    for r in all_charges:
        if not _fee_in_scope(r):
            continue
        pk = r.get("student_pk")
        s = fee_students.get(pk)
        track = _tracking(r)
        row = {
            "charge_id": r.get("charge_id"),
            "student_pk": pk,
            "name": _student_name(s) if s else (r.get("student_name") or "—"),
            "student_id": (s.student_id if s else r.get("student_id")) or "",
            "reg_no": (s.reg_no if s else r.get("reg_no")) or "",
            "campus": s.admitted_campus.name if s and s.admitted_campus_id else "—",
            "program": s.admitted_program.name if s and s.admitted_program_id else "—",
            "intake": s.admitted_batch.name if s and s.admitted_batch_id else "—",
            "amount": r.get("amount"),
            "currency": r.get("currency") or "UGX",
            "charge_status": r.get("status"),
            "tracking": track,
            "status": track,
            "applied": bool(r.get("change_request_id")),
            "change_request_status": r.get("change_request_status"),
            "papers": r.get("draft_paper_count") or 0,
            "has_draft": bool(r.get("has_draft")),
            "form_ready": bool(r.get("form_ready")),
            "charged_at": r.get("charged_at"),
            "days_pending": r.get("days_pending"),
            "form_fee_paid": track in ("paid_submitted", "paid_unsubmitted"),
            "submitted_at": None,
            "submitted_by": "",
            "reviewed_by": "",
            "reviewed_at": None,
        }
        form_fee_rows.append(row)
        if track == "paid_unsubmitted":
            paid_rows.append(row)

    rows = []
    for req in base:
        s = req.admitted_student
        rows.append(
            {
                "id": req.id,
                "student_pk": s.pk if s else None,
                "name": _student_name(s),
                "student_id": (s.student_id or "") if s else "",
                "reg_no": (s.reg_no or "") if s else "",
                "campus": s.admitted_campus.name if s and s.admitted_campus_id else "—",
                "program": s.admitted_program.name if s and s.admitted_program_id else "—",
                "intake": s.admitted_batch.name if s and s.admitted_batch_id else "—",
                "status": req.status,
                "papers": req.exemption_lines.count(),
                "submitted_at": req.created_at.isoformat() if req.created_at else None,
                "submitted_by": _staff_name(req.requested_by),
                "reviewed_by": _staff_name(req.reviewed_by),
                "reviewed_at": req.reviewed_at.isoformat() if req.reviewed_at else None,
                "form_fee_paid": bool(req.form_fee_paid_at),
            }
        )

    billed = [r for r in form_fee_rows if r["tracking"] != "waived"]
    billed_unpaid = [r for r in form_fee_rows if r["tracking"] == "billed_unpaid"]
    paid_all = [r for r in form_fee_rows if r["form_fee_paid"]]
    paid_submitted = [r for r in form_fee_rows if r["tracking"] == "paid_submitted"]

    by_status = [
        {"status": "pending", "count": int(totals_row["pending"] or 0)},
        {"status": "approved", "count": int(totals_row["approved"] or 0)},
        {"status": "rejected", "count": int(totals_row["rejected"] or 0)},
        {"status": "paid_unsubmitted", "count": len(paid_rows)},
        {"status": "billed_unpaid", "count": len(billed_unpaid)},
    ]

    return {
        "totals": {
            "submitted": int(totals_row["submitted"] or 0),
            "pending": int(totals_row["pending"] or 0),
            "approved": int(totals_row["approved"] or 0),
            "rejected": int(totals_row["rejected"] or 0),
            "paid_unsubmitted": len(paid_rows),
            "form_fee_billed": len(billed),
            "form_fee_unpaid": len(billed_unpaid),
            "form_fee_paid": len(paid_all),
            "form_fee_paid_submitted": len(paid_submitted),
        },
        "by_status": by_status,
        "applications": rows,
        "paid_unsubmitted": paid_rows,
        "form_fees": form_fee_rows,
    }
