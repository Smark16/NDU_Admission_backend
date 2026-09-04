"""Read-only eligible-student list for e-voting import (X-API-Key)."""
from __future__ import annotations

from django.core.paginator import Paginator
from django.db.models import Q
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.models import AdmittedStudent
from payments.models import RegistrationSettings
from payments.tuition_pct_queryset import filter_by_tuition_pct_met

from .permissions import HasEvotingApiKey

MAX_PAGE_SIZE = 500
_CAMPUS_ALIASES = {
    "LWE": ("MN", "LWE", "MAIN"),
    "MN": ("MN", "LWE", "MAIN"),
    "MAIN": ("MN", "LWE", "MAIN"),
    "KLA": ("KLA",),
    "KAMPALA": ("KLA",),
}


def _registration_threshold() -> tuple[float, bool]:
    """Same gate as Student course registration (portal) → minimum tuition %."""
    settings = RegistrationSettings.get_settings()
    return float(settings.min_tuition_payment_percentage or 0), bool(settings.skip_tuition_check)


def _campus_codes(request) -> list[str]:
    raw = (request.query_params.get("campus") or request.query_params.get("campus_code") or "").strip()
    if not raw:
        return []
    codes: list[str] = []
    for part in raw.split(","):
        code = part.strip().upper()
        if not code:
            continue
        codes.extend(_CAMPUS_ALIASES.get(code, (code,)))
    return list(dict.fromkeys(codes))


def _campus_q(campus_codes: list[str]) -> Q:
    """Match ERP campuses by code or name. myvote codes (KLA/LWE) often differ from ERP codes."""
    q = Q(admitted_campus__code__in=campus_codes)
    codes = {code.upper() for code in campus_codes}
    if codes & {"KLA", "KAMPALA"}:
        q |= Q(admitted_campus__name__icontains="kampala")
        q |= Q(admitted_campus__code__icontains="kla")
        q |= Q(admitted_campus__code__icontains="kampala")
    if codes & {"MN", "LWE", "MAIN"}:
        main_q = (
            Q(admitted_campus__name__icontains="main")
            | Q(admitted_campus__name__icontains="lwe")
            | Q(admitted_campus__name__icontains="ndejje")
            | Q(admitted_campus__code__icontains="main")
            | Q(admitted_campus__code__icontains="lwe")
            | Q(admitted_campus__code__iexact="mn")
        )
        q |= main_q & ~Q(admitted_campus__name__icontains="kampala") & ~Q(
            admitted_campus__code__icontains="kla"
        )
    return q


def _eligible_queryset(campus_codes: list[str], skip_tuition: bool):
    qs = (
        AdmittedStudent.objects.filter(is_admitted=True)
        .exclude(reg_no__isnull=True)
        .exclude(reg_no__exact="")
        .select_related(
            "admitted_campus",
            "admitted_program",
            "admitted_program__faculty",
            "application",
            "student_user",
        )
    )
    if campus_codes:
        qs = qs.filter(_campus_q(campus_codes))
    if skip_tuition:
        return qs
    return filter_by_tuition_pct_met(qs, True)


def _row(student: AdmittedStudent) -> dict:
    campus = student.admitted_campus
    program = student.admitted_program
    faculty = getattr(program, "faculty", None) if program else None
    email = ""
    if getattr(student, "application_id", None) and student.application:
        email = (student.application.email or "").strip()
    if not email and getattr(student, "student_user", None):
        email = (student.student_user.email or "").strip()
    return {
        "student_number": (student.reg_no or "").strip(),
        "campus_code": (campus.code or "").strip() if campus else "",
        "campus_name": (campus.name or "").strip() if campus else "",
        "faculty_code": (faculty.code or "").strip() if faculty else "",
        "faculty_name": (faculty.name or "").strip() if faculty else "",
        "university_email": email or None,
    }


class EvotingEligibleVotersView(APIView):
    """Students who meet the ERP course-registration tuition % gate. Never writes ERP data."""

    permission_classes = [HasEvotingApiKey]
    authentication_classes = []

    def get(self, request):
        min_pct, skip_tuition = _registration_threshold()
        if str(request.query_params.get("config_only") or "").lower() in ("1", "true", "yes"):
            return Response(
                {
                    "min_pct": min_pct,
                    "skip_tuition_check": skip_tuition,
                    "count": 0,
                    "page": 1,
                    "page_size": 0,
                    "next": None,
                    "results": [],
                }
            )

        campus_codes = _campus_codes(request)
        try:
            page = max(int(request.query_params.get("page") or 1), 1)
        except (TypeError, ValueError):
            page = 1
        try:
            page_size = int(request.query_params.get("page_size") or 200)
        except (TypeError, ValueError):
            page_size = 200
        page_size = max(1, min(page_size, MAX_PAGE_SIZE))

        qs = _eligible_queryset(campus_codes, skip_tuition)
        paginator = Paginator(qs.order_by("id"), page_size)
        page_obj = paginator.get_page(page)
        results = [_row(student) for student in page_obj.object_list]

        return Response(
            {
                "min_pct": min_pct,
                "skip_tuition_check": skip_tuition,
                "count": paginator.count,
                "page": page_obj.number,
                "page_size": page_size,
                "next": page_obj.next_page_number() if page_obj.has_next() else None,
                "results": results,
            }
        )
