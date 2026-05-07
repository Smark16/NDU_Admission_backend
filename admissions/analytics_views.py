"""
Analytics Dashboard API
GET /api/admissions/analytics/dashboard
Query params: batch_id, campus_id, academic_level_id, date_from, date_to

AdmittedStudent breakdowns also respect academic_level_id and application created_at dates.
"""
from django.db.models import Count, Sum, Q, F, Value, Max
from django.db.models.functions import TruncMonth, TruncDate, Trim, Lower, Coalesce, NullIf
from django.utils.dateparse import parse_date
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from accounts.erp_drf_permissions import CanViewAdmissionsAnalytics

from .models import Application, AdmittedStudent, Batch, AcademicLevel
from accounts.models import Campus
from payments.models import ApplicationPayment
from django.db.utils import ProgrammingError
from Programs.models import Program
try:
    from Programs.models import StudentProgrammeEnrollment
    _HAS_ENROLLMENT = True
except (ImportError, ProgrammingError):
    StudentProgrammeEnrollment = None
    _HAS_ENROLLMENT = False


LOCAL_NATIONALITIES = {"Uganda", "Kenya", "Tanzania", "Rwanda", "Burundi", "South Sudan"}

_INVALID_SCHOOL_TOKENS = frozenset(
    {"", "n/a", "na", "none", "-", "--", "null", "nil", "tbd", "pending", "n.a.", "n.a"}
)


def _looks_like_centre_or_index_only(text: str) -> bool:
    """True if the string has no letters (digits, punctuation, spaces only) — treat as centre/ref, not a school name."""
    t = (text or "").strip()
    if not t:
        return True
    return not any(ch.isalpha() for ch in t)


def _display_top_school_label(group_key: str, sample_school: str, sample_index: str) -> str:
    """Pick a readable label for the chart/CSV; grouping is already normalized in SQL."""
    ss = (sample_school or "").strip()
    ix = (sample_index or "").strip()
    ix_l = ix.lower()
    if ix_l in _INVALID_SCHOOL_TOKENS:
        ix = ""
    if ss and not _looks_like_centre_or_index_only(ss):
        return ss
    if ix and ix_l not in _INVALID_SCHOOL_TOKENS:
        return f"A-Level centre / index: {ix}"
    if ss:
        return ss
    return group_key or "Unknown"


class AnalyticsDashboardView(APIView):
    permission_classes = [IsAuthenticated, CanViewAdmissionsAnalytics]

    def get(self, request):
        # ── Filters ───────────────────────────────────────────────────────────
        batch_id         = request.GET.get("batch_id")
        campus_id        = request.GET.get("campus_id")
        academic_level_id = request.GET.get("academic_level_id")
        date_from        = request.GET.get("date_from")
        date_to          = request.GET.get("date_to")

        qs = Application.objects.all()

        if batch_id:
            qs = qs.filter(batch_id=batch_id)
        if campus_id:
            qs = qs.filter(campus_id=campus_id)
        if academic_level_id:
            qs = qs.filter(academic_level_id=academic_level_id)
        if date_from:
            d = parse_date(date_from)
            if d:
                qs = qs.filter(created_at__date__gte=d)
        if date_to:
            d = parse_date(date_to)
            if d:
                qs = qs.filter(created_at__date__lte=d)

        # Exclude drafts from most metrics
        submitted_qs = qs.exclude(status="draft")

        # ── KPI Cards ─────────────────────────────────────────────────────────
        total_submitted   = submitted_qs.count()
        total_admitted    = submitted_qs.filter(status="accepted").count()
        total_rejected    = submitted_qs.filter(status="rejected").count()
        total_pending     = submitted_qs.filter(status="submitted").count()
        total_under_review = submitted_qs.filter(status="under_review").count()

        # Online vs direct vs legacy (Application.source — same filters as other app metrics)
        apps_portal = submitted_qs.filter(source=Application.SOURCE_PORTAL).count()
        apps_direct_entry = submitted_qs.filter(source=Application.SOURCE_DIRECT).count()
        apps_legacy_import = submitted_qs.filter(source=Application.SOURCE_LEGACY).count()
        applications_by_source = list(
            submitted_qs.values("source")
            .annotate(count=Count("id"))
            .order_by("-count")
        )

        admitted_qs = AdmittedStudent.objects.all()
        if batch_id:
            admitted_qs = admitted_qs.filter(admitted_batch_id=batch_id)
        if campus_id:
            admitted_qs = admitted_qs.filter(admitted_campus_id=campus_id)
        if academic_level_id:
            admitted_qs = admitted_qs.filter(admitted_program__academic_level_id=academic_level_id)
        if date_from:
            d = parse_date(date_from)
            if d:
                admitted_qs = admitted_qs.filter(application__created_at__date__gte=d)
        if date_to:
            d = parse_date(date_to)
            if d:
                admitted_qs = admitted_qs.filter(application__created_at__date__lte=d)
        total_registered = admitted_qs.filter(is_registered=True).count()
        total_admitted_students = admitted_qs.filter(is_admitted=True).count()

        # Application fee collections
        pay_qs = ApplicationPayment.objects.all()
        if batch_id:
            pay_qs = pay_qs.filter(application__batch_id=batch_id)
        if campus_id:
            pay_qs = pay_qs.filter(application__campus_id=campus_id)

        fees_collected = pay_qs.filter(status="PAID").aggregate(
            total=Sum("amount"))["total"] or 0
        fees_pending   = pay_qs.filter(status="PENDING").aggregate(
            total=Sum("amount"))["total"] or 0

        active_batches = Batch.objects.filter(is_active=True).count()

        # ── Application Pipeline (funnel) ─────────────────────────────────────
        pipeline = [
            {"stage": "Submitted",    "count": total_submitted},
            {"stage": "Under Review", "count": total_under_review},
            {"stage": "Admitted",     "count": total_admitted},
            {"stage": "Registered",   "count": total_registered},
        ]

        # ── Status Breakdown (pie) ────────────────────────────────────────────
        status_breakdown = list(
            submitted_qs.values("status")
            .annotate(count=Count("id"))
            .order_by("-count")
        )

        # ── Monthly Trend (line chart) ────────────────────────────────────────
        monthly_trend = list(
            submitted_qs
            .annotate(month=TruncMonth("created_at"))
            .values("month")
            .annotate(count=Count("id"))
            .order_by("month")
        )
        monthly_trend_clean = [
            {"month": r["month"].strftime("%b %Y"), "count": r["count"]}
            for r in monthly_trend if r["month"]
        ]

        # ── Applications by Campus (bar) ──────────────────────────────────────
        by_campus = list(
            submitted_qs.values(campus_name=F("campus__name"))
            .annotate(count=Count("id"))
            .order_by("-count")
        )

        # ── Applications by Academic Level (bar) ──────────────────────────────
        by_level = list(
            submitted_qs.values(level=F("academic_level__name"))
            .annotate(count=Count("id"))
            .order_by("-count")
        )

        # ── Faculty: accepted applications vs admitted students ───────────────
        # Accepted = Application with status accepted, faculty from chosen programmes (M2M → distinct count).
        accepted_applications_by_faculty = list(
            submitted_qs.filter(status="accepted")
            .values(faculty_name=F("programs__faculty__name"))
            .annotate(count=Count("id", distinct=True))
            .exclude(faculty_name=None)
            .order_by("-count")
        )
        # AdmittedStudent rows (is_admitted), faculty from admitted_program (one programme per row).
        admitted_students_by_faculty = list(
            admitted_qs.filter(is_admitted=True)
            .values(faculty_name=F("admitted_program__faculty__name"))
            .annotate(count=Count("id"))
            .exclude(faculty_name=None)
            .order_by("-count")
        )

        # ── Top 10 Programs by Applications ───────────────────────────────────
        top_programs = list(
            submitted_qs
            .values(program_name=F("programs__name"))
            .annotate(count=Count("id"))
            .exclude(program_name=None)
            .order_by("-count")[:10]
        )

        # ── Top 10 A-Level schools / centres (background grouping) ─────────────
        # Applicants often type centre numbers or mixed text. We do NOT rely on raw
        # names only: group_key = lower(trim(school)) if present else lower(trim(index)).
        # Case-insensitive name merge; centre-only school text still buckets with index fallback.
        _school_qs = submitted_qs.annotate(
            _st=Trim("alevel_school"),
            _ix=Trim("alevel_index_number"),
        ).annotate(
            _group_key=Coalesce(
                NullIf(Lower(F("_st")), Value("")),
                NullIf(Lower(F("_ix")), Value("")),
                Value("__skip__"),
            )
        ).exclude(_group_key__in=["__skip__", *list(_INVALID_SCHOOL_TOKENS)])

        top_schools_rows = list(
            _school_qs.values("_group_key")
            .annotate(
                count=Count("id"),
                sample_school=Max("_st"),
                sample_index=Max("_ix"),
            )
            .order_by("-count")[:10]
        )
        top_schools = []
        for r in top_schools_rows:
            gk = (r.get("_group_key") or "").strip()
            if not gk or gk.lower() in _INVALID_SCHOOL_TOKENS:
                continue
            top_schools.append(
                {
                    "school_name": _display_top_school_label(
                        gk, r.get("sample_school") or "", r.get("sample_index") or ""
                    ),
                    "count": r["count"],
                    "group_key": gk,
                }
            )

        # ── Gender Breakdown (pie) ────────────────────────────────────────────
        gender_breakdown = list(
            submitted_qs.values("gender")
            .annotate(count=Count("id"))
            .order_by("-count")
        )

        # ── Nationality Type: Local vs International ───────────────────────────
        local_count = submitted_qs.filter(
            nationality__in=LOCAL_NATIONALITIES).count()
        intl_count  = total_submitted - local_count
        nationality_split = [
            {"type": "Local",         "count": local_count},
            {"type": "International", "count": intl_count},
        ]

        # ── Enrollment Status (bar) ───────────────────────────────────────────
        enrollment_breakdown = []
        if _HAS_ENROLLMENT and StudentProgrammeEnrollment is not None:
            try:
                enroll_qs = StudentProgrammeEnrollment.objects.all()
                if batch_id:
                    enroll_qs = enroll_qs.filter(program_batch_id=batch_id)
                enrollment_breakdown = list(
                    enroll_qs.values("status")
                    .annotate(count=Count("id"))
                    .order_by("-count")
                )
            except ProgrammingError:
                enrollment_breakdown = []

        # ── Admission by Batch ────────────────────────────────────────────────
        by_batch = list(
            submitted_qs.values(
                batch_name=F("batch__name"),
                academic_year=F("batch__academic_year"),
            )
            .annotate(
                total=Count("id"),
                admitted=Count("id", filter=Q(status="accepted")),
                rejected=Count("id", filter=Q(status="rejected")),
                pending=Count("id", filter=Q(status="submitted")),
            )
            .order_by("-total")
        )

        # ── Filter Options (for the UI dropdowns) ─────────────────────────────
        batches = list(
            Batch.objects.values("id", "name", "academic_year").order_by("-academic_year")
        )
        campuses = list(Campus.objects.values("id", "name").order_by("name"))
        levels   = list(AcademicLevel.objects.values("id", "name").order_by("name"))

        return Response({
            "kpis": {
                "total_submitted":        total_submitted,
                "total_pending":          total_pending,
                "total_under_review":     total_under_review,
                "total_admitted":         total_admitted,
                "total_rejected":         total_rejected,
                "total_registered":       total_registered,
                "total_admitted_students": total_admitted_students,
                "fees_collected":         float(fees_collected),
                "fees_pending":           float(fees_pending),
                "active_batches":         active_batches,
                "apps_portal":            apps_portal,
                "apps_direct_entry":      apps_direct_entry,
                "apps_legacy_import":     apps_legacy_import,
            },
            "applications_by_source": applications_by_source,
            "pipeline":             pipeline,
            "status_breakdown":     status_breakdown,
            "monthly_trend":        monthly_trend_clean,
            "by_campus":            by_campus,
            "by_academic_level":    by_level,
            "accepted_applications_by_faculty": accepted_applications_by_faculty,
            "admitted_students_by_faculty":      admitted_students_by_faculty,
            "top_programs":         top_programs,
            "top_schools":          top_schools,
            "gender_breakdown":     gender_breakdown,
            "nationality_split":    nationality_split,
            "enrollment_breakdown": enrollment_breakdown,
            "by_batch":             by_batch,
            "filter_options": {
                "batches":  batches,
                "campuses": campuses,
                "levels":   levels,
            },
        })
