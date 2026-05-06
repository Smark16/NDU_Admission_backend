"""REST endpoints for Course Units admin (list, create, update)."""
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import CourseUnit


def serialize_course_unit(cu: CourseUnit) -> dict:
    return {
        "id": cu.id,
        "name": cu.name,
        "code": cu.code,
        "credit_units": float(cu.credit_units) if cu.credit_units is not None else None,
        "is_active": cu.is_active,
        "semester_id": cu.semester_id,
        "program_batch_id": cu.program_batch_id,
    }


class ListCourseUnitsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = CourseUnit.objects.all().order_by("code", "name")
        raw = request.query_params.get("catalog_only", "")
        if raw.lower() in ("1", "true", "yes"):
            qs = qs.filter(semester__isnull=True, program_batch__isnull=True)
        return Response([serialize_course_unit(c) for c in qs])


class CreateCourseUnitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        name = (request.data.get("name") or "").strip()
        code = (request.data.get("code") or "").strip()
        if not name or not code:
            return Response(
                {"detail": "Name and code are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        is_active = request.data.get("is_active", True)
        kwargs = {"name": name, "code": code, "is_active": bool(is_active)}
        cu_raw = request.data.get("credit_units")
        if cu_raw not in (None, ""):
            try:
                kwargs["credit_units"] = Decimal(str(cu_raw))
            except (InvalidOperation, TypeError, ValueError):
                pass
        try:
            cu = CourseUnit.objects.create(**kwargs)
        except IntegrityError:
            return Response(
                {"detail": "A course unit with this code already exists in this context."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(serialize_course_unit(cu), status=status.HTTP_201_CREATED)


class UpdateCourseUnitView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request, pk):
        try:
            cu = CourseUnit.objects.get(pk=pk)
        except CourseUnit.DoesNotExist:
            return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        name = (request.data.get("name") or "").strip()
        code = (request.data.get("code") or "").strip()
        if not name or not code:
            return Response(
                {"detail": "Name and code are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        cu.name = name
        cu.code = code
        cu_raw = request.data.get("credit_units")
        if cu_raw in (None, ""):
            cu.credit_units = None
        else:
            try:
                cu.credit_units = Decimal(str(cu_raw))
            except (InvalidOperation, TypeError, ValueError):
                cu.credit_units = None
        if "is_active" in request.data:
            cu.is_active = bool(request.data["is_active"])
        try:
            cu.save()
        except IntegrityError:
            return Response(
                {"detail": "A course unit with this code already exists in this context."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(serialize_course_unit(cu))
