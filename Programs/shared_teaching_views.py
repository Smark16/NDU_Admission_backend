"""API for SharedTeachingOffering — common courses across programmes."""
from __future__ import annotations

from django.db import transaction
from django.db.models import Count
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import CourseUnit, SharedTeachingOffering
from .permissions import ProgramSchedulingAPIPermission
from .shared_teaching import (
    create_shared_offering_from_course_units,
    search_course_units_for_share,
    serialize_shared_offering,
)


def _parse_int_list(raw) -> list[int]:
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [x.strip() for x in raw.replace(";", ",").split(",") if x.strip()]
    elif not isinstance(raw, list):
        raw = [raw]
    out = []
    for x in raw:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


class SharedTeachingOfferingListCreateView(APIView):
    """GET list / POST create a shared teaching offering from course_unit_ids."""

    permission_classes = [ProgramSchedulingAPIPermission]

    def get(self, request):
        qs = (
            SharedTeachingOffering.objects.all()
            .annotate(linked_count=Count("course_units", distinct=True))
            .prefetch_related(
                "lecturers",
                "course_units__program_batch__program",
                "course_units__semester",
            )
            .order_by("-updated_at")
        )
        code = (request.query_params.get("code") or "").strip()
        if code:
            qs = qs.filter(code__icontains=code)
        active = request.query_params.get("is_active")
        if active is not None and str(active).lower() in ("0", "false", "no"):
            qs = qs.filter(is_active=False)
        elif active is not None and str(active).lower() in ("1", "true", "yes"):
            qs = qs.filter(is_active=True)

        year = (request.query_params.get("academic_year_label") or "").strip()
        if year:
            qs = qs.filter(academic_year_label__icontains=year)

        return Response(
            {
                "count": qs.count(),
                "results": [serialize_shared_offering(o) for o in qs[:200]],
            }
        )

    def post(self, request):
        ids = _parse_int_list(request.data.get("course_unit_ids"))
        if len(ids) < 2:
            return Response(
                {"detail": "course_unit_ids must include at least two course units."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            yos = request.data.get("year_of_study")
            term = request.data.get("term_number")
            parent_raw = request.data.get("parent_course_unit_id")
            parent_course_unit_id = (
                int(parent_raw) if parent_raw not in (None, "") else ids[0]
            )
            with transaction.atomic():
                offering = create_shared_offering_from_course_units(
                    course_unit_ids=ids,
                    code=(request.data.get("code") or None),
                    name=(request.data.get("name") or None),
                    academic_year_label=(request.data.get("academic_year_label") or ""),
                    year_of_study=int(yos) if yos not in (None, "") else None,
                    term_number=int(term) if term not in (None, "") else None,
                    exam_paper_code=(request.data.get("exam_paper_code") or ""),
                    notes=(request.data.get("notes") or ""),
                    lecturer_ids=_parse_int_list(request.data.get("lecturer_ids")) or None,
                    parent_course_unit_id=parent_course_unit_id,
                )
        except (TypeError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        offering = (
            SharedTeachingOffering.objects.filter(pk=offering.pk)
            .prefetch_related(
                "lecturers",
                "course_units__program_batch__program",
                "course_units__semester",
            )
            .get()
        )
        return Response(serialize_shared_offering(offering), status=status.HTTP_201_CREATED)


class SharedTeachingOfferingDetailView(APIView):
    permission_classes = [ProgramSchedulingAPIPermission]

    def get(self, request, offering_id: int):
        offering = (
            SharedTeachingOffering.objects.filter(pk=offering_id)
            .prefetch_related(
                "lecturers",
                "course_units__program_batch__program",
                "course_units__semester",
            )
            .first()
        )
        if not offering:
            return Response({"detail": "Shared teaching offering not found."}, status=404)
        return Response(serialize_shared_offering(offering))

    def patch(self, request, offering_id: int):
        offering = SharedTeachingOffering.objects.filter(pk=offering_id).first()
        if not offering:
            return Response({"detail": "Shared teaching offering not found."}, status=404)

        data = request.data

        # Validate add conflicts before any writes so a rejected request is a no-op.
        add_ids: list[int] = []
        if "add_course_unit_ids" in data:
            add_ids = _parse_int_list(data.get("add_course_unit_ids"))
            if add_ids:
                conflict = (
                    CourseUnit.objects.filter(id__in=add_ids, is_active=True)
                    .exclude(shared_teaching_offering_id__isnull=True)
                    .exclude(shared_teaching_offering_id=offering.id)
                    .values_list("id", "code", "shared_teaching_offering_id")[:5]
                )
                conflict_list = list(conflict)
                if conflict_list:
                    detail_parts = [
                        f"CU#{cid} ({code or '—'}) already on shared #{sto_id}"
                        for cid, code, sto_id in conflict_list
                    ]
                    return Response(
                        {
                            "detail": (
                                "Cannot add course units that are already linked to "
                                "another shared teaching offering. Unlink them first, "
                                "or pick unlinked units. "
                                + "; ".join(detail_parts)
                            )
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

        for field in ("code", "name", "academic_year_label", "exam_paper_code", "notes"):
            if field in data:
                setattr(offering, field, (data.get(field) or "").strip())
        for field in ("year_of_study", "term_number"):
            if field in data:
                raw = data.get(field)
                if raw in (None, ""):
                    setattr(offering, field, None)
                else:
                    try:
                        setattr(offering, field, int(raw))
                    except (TypeError, ValueError):
                        return Response(
                            {"detail": f"{field} must be an integer."},
                            status=status.HTTP_400_BAD_REQUEST,
                        )
        if "is_active" in data:
            offering.is_active = bool(data.get("is_active"))
        if "catalog_unit_id" in data:
            raw = data.get("catalog_unit_id")
            offering.catalog_unit_id = int(raw) if raw not in (None, "") else None
        # Save scalar fields first; parent is applied after link/unlink so a new
        # parent can be added in the same request as add_course_unit_ids.
        offering.save()

        if "lecturer_ids" in data:
            offering.lecturers.set(_parse_int_list(data.get("lecturer_ids")))

        # Link / unlink course units BEFORE parent validation
        if add_ids:
            CourseUnit.objects.filter(id__in=add_ids, is_active=True).update(
                shared_teaching_offering_id=offering.id
            )
        if "remove_course_unit_ids" in data:
            remove_ids = _parse_int_list(data.get("remove_course_unit_ids"))
            if remove_ids:
                CourseUnit.objects.filter(
                    id__in=remove_ids,
                    shared_teaching_offering_id=offering.id,
                ).update(shared_teaching_offering_id=None)
                if (
                    offering.parent_course_unit_id
                    and offering.parent_course_unit_id in remove_ids
                ):
                    offering.parent_course_unit_id = None
                    offering.save(update_fields=["parent_course_unit_id", "updated_at"])

        if "parent_course_unit_id" in data:
            raw = data.get("parent_course_unit_id")
            if raw in (None, ""):
                offering.parent_course_unit_id = None
            else:
                try:
                    parent_id = int(raw)
                except (TypeError, ValueError):
                    return Response(
                        {"detail": "parent_course_unit_id must be an integer."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                if not CourseUnit.objects.filter(
                    pk=parent_id,
                    shared_teaching_offering_id=offering.id,
                    is_active=True,
                ).exists():
                    return Response(
                        {
                            "detail": (
                                "parent_course_unit_id must be an active course unit "
                                "linked to this shared offering."
                            )
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                offering.parent_course_unit_id = parent_id
            offering.save(update_fields=["parent_course_unit_id", "updated_at"])

        offering = (
            SharedTeachingOffering.objects.filter(pk=offering.pk)
            .prefetch_related(
                "lecturers",
                "course_units__program_batch__program",
                "course_units__semester",
            )
            .get()
        )
        return Response(serialize_shared_offering(offering))

    def delete(self, request, offering_id: int):
        offering = SharedTeachingOffering.objects.filter(pk=offering_id).first()
        if not offering:
            return Response({"detail": "Shared teaching offering not found."}, status=404)
        CourseUnit.objects.filter(shared_teaching_offering_id=offering.id).update(
            shared_teaching_offering_id=None
        )
        offering.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SuggestCommonCourseUnitsView(APIView):
    """Find active CourseUnits that share a code (candidates for a shared offering)."""

    permission_classes = [ProgramSchedulingAPIPermission]

    def get(self, request):
        code = (request.query_params.get("code") or "").strip()
        min_count = int(request.query_params.get("min_count") or 2)

        qs = CourseUnit.objects.filter(is_active=True)
        if code:
            qs = qs.filter(code__icontains=code)

        # Group by exact code
        from collections import defaultdict

        by_code = defaultdict(list)
        for cu in qs.select_related(
            "program_batch",
            "program_batch__program",
            "semester",
            "shared_teaching_offering",
        ).order_by("code", "id")[:2000]:
            by_code[cu.code].append(cu)

        groups = []
        for c, units in sorted(by_code.items()):
            if len(units) < min_count:
                continue
            already = {u.shared_teaching_offering_id for u in units if u.shared_teaching_offering_id}
            groups.append(
                {
                    "code": c,
                    "count": len(units),
                    "already_linked_offering_ids": sorted(x for x in already if x),
                    "course_units": [
                        {
                            "id": u.id,
                            "name": u.name,
                            "semester_id": u.semester_id,
                            "semester_name": u.semester.name if u.semester_id else None,
                            "program_batch_id": u.program_batch_id,
                            "program_batch_name": (
                                u.program_batch.name if u.program_batch_id else None
                            ),
                            "program_name": (
                                u.program_batch.program.name
                                if u.program_batch_id and u.program_batch.program_id
                                else None
                            ),
                            "shared_teaching_offering_id": u.shared_teaching_offering_id,
                        }
                        for u in units
                    ],
                }
            )

        return Response({"count": len(groups), "groups": groups[:100]})


class SearchCourseUnitsForShareView(APIView):
    """Search course units on other programmes to add to a shared / cross-cutting class.

    ``study_mode`` query param ranks same-mode results first; all modes are returned.
    """

    permission_classes = [ProgramSchedulingAPIPermission]

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        exclude_semester = request.query_params.get("exclude_semester_id")
        try:
            exclude_semester_id = int(exclude_semester) if exclude_semester not in (None, "") else None
        except (TypeError, ValueError):
            exclude_semester_id = None
        exclude_ids = _parse_int_list(request.query_params.get("exclude_ids"))
        study_mode = (request.query_params.get("study_mode") or "").strip() or None
        campus_raw = request.query_params.get("campus_id")
        try:
            campus_id = int(campus_raw) if campus_raw not in (None, "") else None
        except (TypeError, ValueError):
            campus_id = None
        results = search_course_units_for_share(
            query=q,
            exclude_semester_id=exclude_semester_id,
            exclude_ids=exclude_ids,
            study_mode=study_mode,
            campus_id=campus_id,
            limit=60,
        )
        return Response({"count": len(results), "results": results})
