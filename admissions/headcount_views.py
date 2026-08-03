"""University-wide student headcount (census) vs commitment-fee status."""
from __future__ import annotations

from collections import defaultdict

from django.db.models import Count, Q
from django.db.models.functions import Coalesce
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.faculty_scope import filter_admitted_students_for_user
from admissions.models import AdmittedStudent, Application, Batch
from payments.commitment_queryset import filter_by_commitment_met
from payments.student_payment_allocation import COMMITMENT_FEE_THRESHOLD

# Same QA-batch exclusion convention used by GetActiveAdmissionBatch, so
# smoke-test intakes never pollute the real headcount or trigger a false
# "multiple active intakes" warning.
_QA_BATCH_EXCLUDE = Q(code__istartswith="QA-") | Q(name__icontains="[QA-INTAKE-BATCH]")


def _nest_cohorts_by_batch(by_cohort: list[dict]) -> list[dict]:
    """Group flat batch×programme rows into batches with nested programmes (+ faculty)."""
    grouped: dict[str, dict[str, dict]] = defaultdict(dict)
    batch_totals: dict[str, int] = defaultdict(int)
    for row in by_cohort:
        batch = row["effective_batch"] or "Unplaced (no batch on record)"
        program = row["admitted_program__name"] or "—"
        faculty = row.get("admitted_program__faculty__name") or "—"
        count = int(row["count"] or 0)
        entry = grouped[batch].get(program)
        if not entry:
            entry = {"faculty": faculty, "count": 0}
            grouped[batch][program] = entry
        entry["count"] += count
        batch_totals[batch] += count

    by_batch = []
    for batch, total in sorted(batch_totals.items(), key=lambda x: (-x[1], x[0])):
        programs = [
            {"program": program, "faculty": data["faculty"], "count": data["count"]}
            for program, data in sorted(
                grouped[batch].items(), key=lambda item: (-item[1]["count"], item[0])
            )
        ]
        by_batch.append({"batch": batch, "count": total, "programs": programs})
    return by_batch


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

        # Intake split. Legacy imports are identified by application source,
        # not by which admission batch they carry, so a legacy row mistakenly
        # tagged onto a live intake can never inflate that intake.
        # "Continuing" = everyone not admitted through the current intake —
        # prior real intakes AND bulk-imported continuing students; the
        # legacy_imported figure is the "of which imported" subset.
        legacy_q = Q(application__source=Application.SOURCE_LEGACY)
        intake_split = base.aggregate(
            current_intake_new=Count(
                "id", filter=Q(admitted_batch__is_active=True) & ~legacy_q
            ),
            continuing_total=Count(
                "id", filter=Q(admitted_batch__is_active=False) | legacy_q
            ),
            legacy_imported=Count("id", filter=legacy_q),
        )

        by_intake = list(
            base.values("admitted_batch__name", "admitted_batch__is_active")
            .annotate(
                count=Count("id"),
                new_admits=Count("id", filter=~legacy_q),
                legacy_imported=Count("id", filter=legacy_q),
            )
            .order_by("-admitted_batch__is_active", "-count")
        )

        by_campus = list(
            base.values("admitted_campus__name")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        by_faculty = list(
            base.values("admitted_program__faculty__name")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        # Fall back to the student's actual academic enrollment batch when
        # intended_program_batch was never stamped on the admission record
        # (a data-entry gap, not a real "no cohort" student) so they show up
        # under their real class instead of silently vanishing into "—".
        by_cohort = list(
            base.annotate(
                effective_batch=Coalesce(
                    "intended_program_batch__name",
                    "programme_enrollment__program_batch__name",
                )
            )
            .values(
                "effective_batch",
                "admitted_program__name",
                "admitted_program__faculty__name",
            )
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        by_batch = _nest_cohorts_by_batch(by_cohort)

        # Warn (never silently auto-fix) if more than one real admission
        # intake is active at once - that would double-count "current
        # intake" figures. QA/smoke-test batches are excluded since they
        # are deliberately allowed to coexist with the real active intake.
        active_intakes = list(
            Batch.objects.filter(is_active=True).exclude(_QA_BATCH_EXCLUDE).values("id", "name")
        )
        multiple_active_intakes = len(active_intakes) > 1

        unpaid_by_campus = list(
            unpaid_qs.values("admitted_campus__name")
            .annotate(count=Count("id"))
            .order_by("-count")
        )

        return Response(
            {
                "total_admitted": total,
                "intake_split": {
                    "current_intake_new": intake_split["current_intake_new"],
                    "continuing_total": intake_split["continuing_total"],
                    "legacy_imported": intake_split["legacy_imported"],
                },
                "by_intake": [
                    {
                        "intake": r["admitted_batch__name"] or "—",
                        "is_active": bool(r["admitted_batch__is_active"]),
                        "count": r["count"],
                        "new_admits": r["new_admits"],
                        "legacy_imported": r["legacy_imported"],
                    }
                    for r in by_intake
                ],
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
                        "batch": r["effective_batch"] or "Unplaced (no batch on record)",
                        "program": r["admitted_program__name"] or "—",
                        "faculty": r["admitted_program__faculty__name"] or "—",
                        "count": r["count"],
                    }
                    for r in by_cohort
                ],
                "by_batch": by_batch,
                "multiple_active_intakes": multiple_active_intakes,
                "active_intakes": [
                    {"id": r["id"], "name": r["name"]} for r in active_intakes
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
