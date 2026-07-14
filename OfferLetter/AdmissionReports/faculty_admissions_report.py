"""Shared helpers for faculty / admitted-students admission reports."""
from __future__ import annotations

from collections import defaultdict

from django.db.models import Q

from admissions.faculty_scope import filter_admitted_students_for_user
from admissions.models import (
    AdmittedStudent,
    ALevelResult,
    ApplicationProgramChoice,
    OLevelResult,
)
from admissions.models import AdditionalQualifications

from .utils.calculate_passes import calculate_pp_sp


def parse_report_pagination(request, *, default_size: int = 25, max_size: int = 100):
    try:
        page = max(1, int(request.query_params.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = min(max_size, max(1, int(request.query_params.get("page_size", default_size))))
    except (TypeError, ValueError):
        page_size = default_size
    return page, page_size


def faculty_admissions_filtered_qs(request):
    academic_year = (request.query_params.get("academic_year") or "").strip()
    admission_period = (request.query_params.get("admission_period") or "").strip()
    campus_id = (request.query_params.get("campus") or "").strip()
    program_id = (request.query_params.get("program") or "").strip()
    faculty_id = (request.query_params.get("faculty") or "").strip()
    study_mode = (request.query_params.get("study_mode") or "").strip()
    documents_verified = (request.query_params.get("documents_verified") or "").lower()
    is_registered = (request.query_params.get("is_registered") or "").lower()
    search = (request.query_params.get("search") or "").strip()

    qs = AdmittedStudent.objects.select_related(
        "application",
        "admitted_program",
        "admitted_program__faculty",
        "admitted_campus",
        "admitted_batch",
    ).filter(is_admitted=True)

    if academic_year:
        qs = qs.filter(admitted_batch__academic_year=academic_year)
    if admission_period:
        qs = qs.filter(admitted_batch__name=admission_period)
    if campus_id:
        qs = qs.filter(admitted_campus_id=campus_id)
    if program_id:
        qs = qs.filter(admitted_program_id=program_id)
    if faculty_id:
        qs = qs.filter(admitted_program__faculty_id=faculty_id)
    if study_mode:
        qs = qs.filter(study_mode__iexact=study_mode)
    if documents_verified in ("1", "true", "yes"):
        qs = qs.filter(physical_documents_verified=True)
    elif documents_verified in ("0", "false", "no"):
        qs = qs.filter(physical_documents_verified=False)
    if is_registered in ("1", "true", "yes"):
        qs = qs.filter(is_registered=True)
    elif is_registered in ("0", "false", "no"):
        qs = qs.filter(is_registered=False)
    if search:
        qs = qs.filter(
            Q(application__first_name__icontains=search)
            | Q(application__last_name__icontains=search)
            | Q(application__middle_name__icontains=search)
            | Q(reg_no__icontains=search)
            | Q(student_id__icontains=search)
            | Q(admitted_program__name__icontains=search)
            | Q(admitted_program__short_form__icontains=search)
        )

    qs = filter_admitted_students_for_user(qs, request.user)
    return qs.order_by(
        "-admitted_batch__academic_year",
        "admitted_batch__name",
        "application__last_name",
        "application__first_name",
    )


def _bulk_row_context(app_ids: list[int]) -> dict:
    if not app_ids:
        return {
            "program_data": {},
            "olevel_data": {},
            "alevel_for_pp_sp": {},
            "alevel_scores": {},
            "qualifications_data": {},
        }

    program_data = defaultdict(list)
    for choice in ApplicationProgramChoice.objects.filter(
        application_id__in=app_ids
    ).select_related("program").order_by("choice_order"):
        program_data[choice.application_id].append(choice.program.name)

    olevel_data = defaultdict(list)
    for res in OLevelResult.objects.filter(application_id__in=app_ids).select_related(
        "subject"
    ).values("application_id", "subject__code", "grade"):
        olevel_data[res["application_id"]].append(
            f"{res['subject__code']}:{res['grade']}"
        )

    alevel_for_pp_sp = defaultdict(list)
    alevel_scores = defaultdict(list)
    for res in ALevelResult.objects.filter(application_id__in=app_ids).select_related(
        "subject"
    ).values("application_id", "subject__code", "grade"):
        app_id = res["application_id"]
        alevel_for_pp_sp[app_id].append(
            {"subject_name": res["subject__code"], "grade": res["grade"]}
        )
        alevel_scores[app_id].append(f"{res['subject__code']}:{res['grade']}")

    qualifications_data = defaultdict(list)
    for qual in AdditionalQualifications.objects.filter(
        application_id__in=app_ids
    ).values(
        "application_id",
        "additional_qualification_institution",
        "additional_qualification_type",
        "additional_qualification_year",
        "class_of_award",
    ):
        qualifications_data[qual["application_id"]].append(qual)

    return {
        "program_data": program_data,
        "olevel_data": olevel_data,
        "alevel_for_pp_sp": alevel_for_pp_sp,
        "alevel_scores": alevel_scores,
        "qualifications_data": qualifications_data,
    }


def admitted_student_report_row(adm: AdmittedStudent, ctx: dict) -> dict:
    app = adm.application
    program_data = ctx["program_data"]
    olevel_data = ctx["olevel_data"]
    alevel_for_pp_sp = ctx["alevel_for_pp_sp"]
    alevel_scores = ctx["alevel_scores"]
    qualifications_data = ctx["qualifications_data"]

    programs = program_data.get(app.id, [])
    course_applied_for = programs[0] if programs else ""
    other_choices = ", ".join(programs[1:]) if len(programs) > 1 else ""

    olevel_scores_str = "; ".join(olevel_data.get(app.id, []))
    alevel_scores_str = "; ".join(alevel_scores.get(app.id, []))

    pp, sp = calculate_pp_sp(alevel_for_pp_sp.get(app.id, []))
    principal_sub = f"{pp}PP, {sp}SP"

    quals = qualifications_data.get(app.id, [])
    other_qual_parts = []
    institutions = []
    class_of_awards = []
    for q in quals:
        if q.get("additional_qualification_institution"):
            qual_str = (
                f"{q['additional_qualification_institution']} - "
                f"{q.get('additional_qualification_type', '')} "
                f"({q.get('additional_qualification_year', '')}) - "
                f"{q.get('class_of_award', '')}"
            )
            other_qual_parts.append(qual_str)
            institutions.append(q["additional_qualification_institution"])
            class_of_awards.append(q.get("class_of_award", ""))

    origin = "DIRECT ENTRY" if getattr(app, "is_direct_entry", False) else "APPLIED ONLINE"
    if getattr(app, "source", None):
        origin = str(app.source).replace("_", " ").upper()

    return {
        "id": adm.id,
        "student_names": f"{app.first_name} {app.last_name}".strip(),
        "gender": app.gender,
        "nationality": app.nationality,
        "contact_address": app.address or "",
        "course_applied_for": course_applied_for,
        "other_choices": other_choices,
        "program": adm.admitted_program.name if adm.admitted_program else "",
        "program_id": adm.admitted_program_id,
        "faculty": (
            adm.admitted_program.faculty.name
            if adm.admitted_program and adm.admitted_program.faculty_id
            else ""
        ),
        "study_mode": getattr(adm, "study_mode", ""),
        "campus": adm.admitted_campus.name if adm.admitted_campus else "",
        "campus_id": adm.admitted_campus_id,
        "academic_year": adm.admitted_batch.academic_year if adm.admitted_batch else "",
        "admission_period": adm.admitted_batch.name if adm.admitted_batch else "",
        "reg_no": adm.reg_no or "",
        "student_id": adm.student_id or "",
        "olevel_school": app.olevel_school or "",
        "olevel_year": app.olevel_year or "",
        "olevel_index_number": app.olevel_index_number or "",
        "olevel_scores": olevel_scores_str,
        "alevel_school": app.alevel_school or "",
        "alevel_year": app.alevel_year or "",
        "alevel_index_number": app.alevel_index_number or "",
        "alevel_combination": app.alevel_combination or "",
        "alevel_scores": alevel_scores_str,
        "principal_subsidiaries": principal_sub,
        "other_qualifications": " | ".join(other_qual_parts) if other_qual_parts else "None",
        "institution": ", ".join(institutions) if institutions else "",
        "class_of_award": ", ".join([c for c in class_of_awards if c]) if class_of_awards else "",
        "course_admitted_for": adm.admitted_program.name if adm.admitted_program else "",
        "remarks": adm.admission_notes or "",
        "payments": "PAID" if app.application_fee_paid else "NOT PAID",
        "admission_date": adm.admission_date.strftime("%Y-%m-%d") if adm.admission_date else "",
        "origin": origin,
        "is_registered": bool(adm.is_registered),
        "physical_documents_verified": bool(adm.physical_documents_verified),
    }


def paginated_admitted_students_report(request):
    qs = faculty_admissions_filtered_qs(request)
    total = qs.count()
    page, page_size = parse_report_pagination(request)
    offset = (page - 1) * page_size
    page_qs = list(qs[offset : offset + page_size])
    app_ids = [adm.application_id for adm in page_qs]
    ctx = _bulk_row_context(app_ids)
    results = [admitted_student_report_row(adm, ctx) for adm in page_qs]
    return {
        "count": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if page_size else 0,
        "results": results,
    }
