"""
Analytics Dashboard API
GET /api/admissions/analytics/dashboard
Query params: batch_id, campus_id, academic_level_id, date_from, date_to

AdmittedStudent breakdowns also respect academic_level_id and application created_at dates.
"""
from django.db.models import Count, Sum, Q, F, Value, Max, Case, When, CharField
from django.db.models.functions import TruncMonth, Trim, Lower, Coalesce
from django.utils.dateparse import parse_date
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from accounts.erp_drf_permissions import CanViewAdmissionsAnalytics

from .models import Application, AdmittedStudent, Batch, AcademicLevel
from .utils.batch_offer_filters import batch_offer_window_q
from .utils.school_name_normalize import aggregate_top_schools
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


def _display_gender_label(group_key: str) -> str:
    """Readable chart/CSV label from a normalized gender bucket key."""
    gk = (group_key or "").strip().lower()
    if not gk:
        return "Unknown"
    if gk == "female":
        return "Female"
    if gk == "male":
        return "Male"
    if gk == "other":
        return "Other"
    return group_key.strip().title()


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

        active_batches = Batch.objects.filter(is_active=True).filter(batch_offer_window_q()).count()

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
        # Accepted = Application with status accepted; faculty via ApplicationProgramChoice.
        accepted_applications_by_faculty = list(
            submitted_qs.filter(status="accepted")
            .values(faculty_name=F("program_choices__program__faculty__name"))
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
            .values(program_name=F("program_choices__program__name"))
            .annotate(count=Count("id", distinct=True))
            .exclude(program_name=None)
            .order_by("-count")[:10]
        )

        # ── Top 10 A-Level schools / centres (normalized grouping) ─────────────
        # Merges Mengo ss / MENGO SS / mengo, Lubiri ss, Ndejje ss, etc.
        top_schools = aggregate_top_schools(submitted_qs, limit=10)

        # ── Gender Breakdown (pie) ────────────────────────────────────────────
        # Group case-insensitively; merge F/female/FEMALE and M/male/MALE.
        gender_breakdown_rows = list(
            submitted_qs.annotate(
                _gender_raw=Lower(Trim(Coalesce(F("gender"), Value("")))),
            )
            .annotate(
                gender_key=Case(
                    When(_gender_raw__in=["f", "female"], then=Value("female")),
                    When(_gender_raw__in=["m", "male"], then=Value("male")),
                    When(_gender_raw="other", then=Value("other")),
                    default=F("_gender_raw"),
                    output_field=CharField(),
                ),
            )
            .values("gender_key")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        gender_breakdown = [
            {"gender": _display_gender_label(r["gender_key"]), "count": r["count"]}
            for r in gender_breakdown_rows
        ]

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
