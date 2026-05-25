from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.models import AcademicYear, Batch
from admissions.serializers import AcademicYearSerializer
from admissions.utils.academic_year import (
    format_academic_year_from_start,
    get_current_academic_year,
    get_default_academic_year_label,
    normalize_academic_year_label,
    suggest_academic_year_options,
    suggest_next_academic_year_label,
)
from Programs.models import ProgramBatch


def _sync_years_from_batches():
    """Import distinct year strings already used on intakes / programme batches."""
    labels = set()
    labels.update(
        Batch.objects.exclude(academic_year="").values_list("academic_year", flat=True)
    )
    labels.update(
        ProgramBatch.objects.exclude(academic_year="").values_list("academic_year", flat=True)
    )
    created = 0
    for raw in labels:
        try:
            label = normalize_academic_year_label(raw)
        except DjangoValidationError:
            continue
        _, was_created = AcademicYear.objects.get_or_create(
            label=label,
            defaults={"is_active": True, "is_current": False},
        )
        if was_created:
            created += 1
    if created and not AcademicYear.objects.filter(is_current=True).exists():
        latest = AcademicYear.objects.order_by("-label").first()
        if latest:
            latest.is_current = True
            latest.save(update_fields=["is_current", "updated_at"])
    return created


class AcademicYearListCreateView(APIView):
    """GET list (active by default); POST create; POST ?sync=1 imports from existing batches."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        include_inactive = request.query_params.get("include_inactive", "").lower() in (
            "1",
            "true",
            "yes",
        )
        qs = AcademicYear.objects.all()
        if not include_inactive:
            qs = qs.filter(is_active=True)
        years = AcademicYearSerializer(qs, many=True).data
        current = (
            AcademicYear.objects.filter(is_current=True, is_active=True)
            .values_list("label", flat=True)
            .first()
        )
        calendar = get_current_academic_year()
        return Response(
            {
                "years": years,
                "current_label": current or get_default_academic_year_label(),
                "calendar_label": calendar,
                "suggested_next": suggest_next_academic_year_label(),
                "picker_options": suggest_academic_year_options(),
                "calendar_in_registry": AcademicYear.objects.filter(
                    label=calendar, is_active=True
                ).exists(),
            }
        )

    def post(self, request):
        if request.query_params.get("sync"):
            created = _sync_years_from_batches()
            return Response(
                {"detail": f"Synced {created} year(s) from existing batch records."},
                status=status.HTTP_200_OK,
            )

        if request.query_params.get("ensure_calendar"):
            calendar = get_current_academic_year()
            row, was_created = AcademicYear.objects.get_or_create(
                label=calendar,
                defaults={"is_active": True, "is_current": True},
            )
            if not was_created:
                row.is_active = True
                row.is_current = True
                row.save(update_fields=["is_active", "is_current", "updated_at"])
            return Response(
                {
                    "detail": (
                        f'{"Added" if was_created else "Updated"} calendar year '
                        f'"{calendar}" as current.'
                    ),
                    "year": AcademicYearSerializer(row).data,
                },
                status=status.HTTP_200_OK if not was_created else status.HTTP_201_CREATED,
            )

        start_year_raw = request.data.get("start_year")
        if start_year_raw is not None and str(start_year_raw).strip() != "":
            try:
                start_year = int(start_year_raw)
                label = format_academic_year_from_start(start_year)
            except (TypeError, ValueError):
                return Response(
                    {"detail": "start_year must be a four-digit year (e.g. 2026)."},
                    status=400,
                )
            except DjangoValidationError as exc:
                return Response({"detail": str(exc)}, status=400)
        else:
            label = (request.data.get("label") or "").strip()
            if not label:
                return Response(
                    {"detail": "label or start_year is required (e.g. 2025/2026)."},
                    status=400,
                )
            try:
                label = normalize_academic_year_label(label)
            except DjangoValidationError as exc:
                return Response({"detail": str(exc)}, status=400)

        if AcademicYear.objects.filter(label=label).exists():
            return Response(
                {"detail": f'Academic year "{label}" already exists.'},
                status=400,
            )

        is_current = bool(request.data.get("is_current", False))
        row = AcademicYear.objects.create(
            label=label,
            is_current=is_current,
            is_active=True,
        )
        return Response(AcademicYearSerializer(row).data, status=status.HTTP_201_CREATED)


class AcademicYearDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        row = get_object_or_404(AcademicYear, pk=pk)
        if "is_current" in request.data and request.data["is_current"]:
            row.is_current = True
            row.is_active = True
            row.save()
            return Response(AcademicYearSerializer(row).data)

        if "is_active" in request.data:
            row.is_active = bool(request.data["is_active"])
            if not row.is_active and row.is_current:
                row.is_current = False
            row.save(update_fields=["is_active", "is_current", "updated_at"])
            return Response(AcademicYearSerializer(row).data)

        return Response({"detail": "Nothing to update."}, status=400)

    def delete(self, request, pk):
        row = get_object_or_404(AcademicYear, pk=pk)
        in_use = (
            Batch.objects.filter(academic_year=row.label).exists()
            or ProgramBatch.objects.filter(academic_year=row.label).exists()
        )
        if in_use:
            row.is_active = False
            row.is_current = False
            row.save(update_fields=["is_active", "is_current", "updated_at"])
            return Response(
                {
                    "detail": (
                        f'"{row.label}" is in use; marked inactive instead of deleted.'
                    )
                }
            )
        row.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
