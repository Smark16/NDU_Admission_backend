"""University-wide student headcount (census) vs commitment-fee status."""
from __future__ import annotations

from django.db.models import Count
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.faculty_scope import filter_admitted_students_for_user
from admissions.models import AdmittedStudent
from payments.commitment_queryset import filter_by_commitment_met
from payments.student_payment_allocation import COMMITMENT_FEE_THRESHOLD


class UniversityHeadcountView(APIView):
    """
    Census dashboard data (Fedena/OpenEduCat-style).

    - total_admitted = university register (non-revoked admitted)
    - commitment_met / unpaid = finance overlay, not membership
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not request.user.has_perm("admissions.view_admittedstudent"):
            return Response({"detail": "Forbidden."}, status=403)

        base = filter_admitted_students_for_user(
            AdmittedStudent.objects.filter(is_admitted=True).select_related(
                "admitted_campus",
                "admitted_program__faculty",
                "intended_program_batch",
            ),
            request.user,
        )

        total = base.count()
        met_qs = filter_by_commitment_met(base, True, strict=False)
        unpaid_qs = filter_by_commitment_met(base, False, strict=False)
        commitment_met = met_qs.count()
        commitment_unpaid = unpaid_qs.count()

        by_campus = list(
            base.values("admitted_campus__name")
            .annotate(count=Count("id"))
            .order_by("-count")[:20]
        )
        by_faculty = list(
            base.values("admitted_program__faculty__name")
            .annotate(count=Count("id"))
            .order_by("-count")[:20]
        )
        by_cohort = list(
            base.values("intended_program_batch__name", "admitted_program__name")
            .annotate(count=Count("id"))
            .order_by("-count")[:25]
        )

        unpaid_by_campus = list(
            unpaid_qs.values("admitted_campus__name")
            .annotate(count=Count("id"))
            .order_by("-count")[:15]
        )

        return Response(
            {
                "total_admitted": total,
                "commitment_met": commitment_met,
                "commitment_unpaid": commitment_unpaid,
                "commitment_threshold_ugx": float(COMMITMENT_FEE_THRESHOLD),
                "commitment_met_pct": round(
                    (100.0 * commitment_met / total) if total else 0.0, 1
                ),
                "by_campus": [
                    {
                        "name": r["admitted_campus__name"] or "—",
                        "count": r["count"],
                    }
                    for r in by_campus
                ],
                "by_faculty": [
                    {
                        "name": r["admitted_program__faculty__name"] or "—",
                        "count": r["count"],
                    }
                    for r in by_faculty
                ],
                "by_cohort": [
                    {
                        "batch": r["intended_program_batch__name"] or "—",
                        "program": r["admitted_program__name"] or "—",
                        "count": r["count"],
                    }
                    for r in by_cohort
                ],
                "unpaid_by_campus": [
                    {
                        "name": r["admitted_campus__name"] or "—",
                        "count": r["count"],
                    }
                    for r in unpaid_by_campus
                ],
                "notes": (
                    "total_admitted is the university register. "
                    "commitment_met is finance status (bonafide ops default)."
                ),
            }
        )
