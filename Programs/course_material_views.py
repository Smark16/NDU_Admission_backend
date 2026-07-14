"""Lecturer upload + student download of course materials (outlines)."""
from __future__ import annotations

import mimetypes
import os

from django.http import FileResponse
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.erp_drf_permissions import user_has_any_erp_perm
from accounts.super_admin import user_is_super_admin
from payments.student_portal_finance import get_admitted_student_for_user

from .attendance_views import _assert_lecturer_course_access
from .models import CourseMaterial, CourseUnit, StudentCourseUnitEnrollment

ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".ppt", ".pptx"}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB


def _is_academic_admin(user) -> bool:
    if user_is_super_admin(user):
        return True
    if user_has_any_erp_perm(
        user,
        "manage_academic_enrollment",
        "access_academics",
    ):
        return True
    return user.has_perm("Programs.change_courseunit")


def _assert_can_manage_materials(user, course_unit: CourseUnit) -> None:
    if _is_academic_admin(user):
        return
    _assert_lecturer_course_access(user, course_unit)


def _assert_student_can_view(user, course_unit: CourseUnit) -> None:
    from rest_framework.exceptions import PermissionDenied

    student = get_admitted_student_for_user(user)
    if not student:
        raise PermissionDenied("Admitted student profile required.")
    enrolled = StudentCourseUnitEnrollment.objects.filter(
        student=student,
        course_unit=course_unit,
        status="enrolled",
    ).exists()
    if not enrolled:
        raise PermissionDenied("You are not enrolled in this course unit.")


def _serialize_material(material: CourseMaterial, request=None) -> dict:
    file_url = None
    if material.file and material.file.name:
        try:
            url = material.file.url
            file_url = request.build_absolute_uri(url) if request is not None else url
        except Exception:
            file_url = None
    return {
        "id": material.id,
        "course_unit_id": material.course_unit_id,
        "material_type": material.material_type,
        "title": material.title or material.get_material_type_display(),
        "file_url": file_url,
        "file_name": os.path.basename(material.file.name) if material.file else "",
        "is_published": material.is_published,
        "uploaded_at": material.uploaded_at.isoformat() if material.uploaded_at else None,
        "uploaded_by": (
            material.uploaded_by.get_full_name()
            if material.uploaded_by_id
            else None
        ),
    }


def published_outline_for_course(course_unit_id: int, request=None) -> dict | None:
    material = (
        CourseMaterial.objects.filter(
            course_unit_id=course_unit_id,
            material_type=CourseMaterial.TYPE_OUTLINE,
            is_published=True,
        )
        .order_by("-uploaded_at")
        .first()
    )
    if not material:
        return None
    return _serialize_material(material, request)


class LecturerCourseMaterialListCreateView(APIView):
    """GET/POST materials for a course the lecturer teaches."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request, course_unit_id):
        course_unit = CourseUnit.objects.filter(pk=course_unit_id).first()
        if not course_unit:
            return Response({"detail": "Course unit not found."}, status=404)
        _assert_can_manage_materials(request.user, course_unit)

        materials = CourseMaterial.objects.filter(course_unit=course_unit).select_related(
            "uploaded_by"
        )
        return Response(
            {
                "course_unit_id": course_unit.id,
                "course_code": course_unit.code,
                "course_name": course_unit.name,
                "materials": [_serialize_material(m, request) for m in materials],
            }
        )

    def post(self, request, course_unit_id):
        course_unit = CourseUnit.objects.filter(pk=course_unit_id).first()
        if not course_unit:
            return Response({"detail": "Course unit not found."}, status=404)
        _assert_can_manage_materials(request.user, course_unit)

        upload = request.FILES.get("file")
        if not upload:
            return Response({"detail": "file is required."}, status=400)

        ext = os.path.splitext(upload.name or "")[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            return Response(
                {
                    "detail": (
                        "Unsupported file type. Allowed: "
                        + ", ".join(sorted(ALLOWED_EXTENSIONS))
                    )
                },
                status=400,
            )
        if upload.size and upload.size > MAX_UPLOAD_BYTES:
            return Response({"detail": "File too large (max 15 MB)."}, status=400)

        material_type = (
            request.data.get("material_type") or CourseMaterial.TYPE_OUTLINE
        ).strip().lower()
        if material_type not in {
            CourseMaterial.TYPE_OUTLINE,
            CourseMaterial.TYPE_NOTES,
            CourseMaterial.TYPE_OTHER,
        }:
            material_type = CourseMaterial.TYPE_OUTLINE

        title = (request.data.get("title") or "").strip()
        if not title:
            title = "Course outline" if material_type == CourseMaterial.TYPE_OUTLINE else upload.name

        publish_flag = str(request.data.get("is_published", "false")).lower() in (
            "1",
            "true",
            "yes",
        )

        # V1: one outline per course — replace existing outline row if present.
        existing = None
        if material_type == CourseMaterial.TYPE_OUTLINE:
            existing = (
                CourseMaterial.objects.filter(
                    course_unit=course_unit,
                    material_type=CourseMaterial.TYPE_OUTLINE,
                )
                .order_by("-uploaded_at")
                .first()
            )

        if existing:
            if existing.file:
                existing.file.delete(save=False)
            existing.title = title
            existing.file = upload
            existing.uploaded_by = request.user
            existing.is_published = publish_flag
            existing.save()
            material = existing
        else:
            material = CourseMaterial.objects.create(
                course_unit=course_unit,
                material_type=material_type,
                title=title,
                file=upload,
                uploaded_by=request.user,
                is_published=publish_flag,
            )

        if material.is_published and material.material_type == CourseMaterial.TYPE_OUTLINE:
            CourseMaterial.objects.filter(
                course_unit=course_unit,
                material_type=CourseMaterial.TYPE_OUTLINE,
                is_published=True,
            ).exclude(pk=material.pk).update(is_published=False)

        return Response(_serialize_material(material, request), status=201)


class LecturerCourseMaterialDetailView(APIView):
    """PATCH/DELETE a material owned via course assignment."""

    permission_classes = [IsAuthenticated]

    def patch(self, request, material_id):
        material = (
            CourseMaterial.objects.select_related("course_unit", "uploaded_by")
            .filter(pk=material_id)
            .first()
        )
        if not material:
            return Response({"detail": "Material not found."}, status=404)
        _assert_can_manage_materials(request.user, material.course_unit)

        if "title" in request.data:
            title = (request.data.get("title") or "").strip()
            if title:
                material.title = title
        if "is_published" in request.data:
            material.is_published = str(request.data.get("is_published")).lower() in (
                "1",
                "true",
                "yes",
            )
        material.save()

        if material.is_published and material.material_type == CourseMaterial.TYPE_OUTLINE:
            CourseMaterial.objects.filter(
                course_unit=material.course_unit,
                material_type=CourseMaterial.TYPE_OUTLINE,
                is_published=True,
            ).exclude(pk=material.pk).update(is_published=False)

        return Response(_serialize_material(material, request))

    def delete(self, request, material_id):
        material = (
            CourseMaterial.objects.select_related("course_unit")
            .filter(pk=material_id)
            .first()
        )
        if not material:
            return Response({"detail": "Material not found."}, status=404)
        _assert_can_manage_materials(request.user, material.course_unit)
        if material.file:
            material.file.delete(save=False)
        material.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class LecturerCourseMaterialDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, material_id):
        material = (
            CourseMaterial.objects.select_related("course_unit")
            .filter(pk=material_id)
            .first()
        )
        if not material or not material.file:
            return Response({"detail": "Material not found."}, status=404)
        _assert_can_manage_materials(request.user, material.course_unit)
        inline = str(request.query_params.get("inline") or "").lower() in (
            "1",
            "true",
            "yes",
        )
        return _file_response(material, inline=inline)


class StudentCourseMaterialListView(APIView):
    """Published materials for a course the student is enrolled in."""

    permission_classes = [IsAuthenticated]

    def get(self, request, course_unit_id):
        course_unit = CourseUnit.objects.filter(pk=course_unit_id).first()
        if not course_unit:
            return Response({"detail": "Course unit not found."}, status=404)
        _assert_student_can_view(request.user, course_unit)

        materials = CourseMaterial.objects.filter(
            course_unit=course_unit, is_published=True
        ).select_related("uploaded_by")
        return Response(
            {
                "course_unit_id": course_unit.id,
                "course_code": course_unit.code,
                "course_name": course_unit.name,
                "materials": [_serialize_material(m, request) for m in materials],
                "published_outline": published_outline_for_course(course_unit.id, request),
            }
        )


class StudentCourseMaterialDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, material_id):
        material = (
            CourseMaterial.objects.select_related("course_unit")
            .filter(pk=material_id, is_published=True)
            .first()
        )
        if not material or not material.file:
            return Response({"detail": "Material not found."}, status=404)
        _assert_student_can_view(request.user, material.course_unit)
        inline = str(request.query_params.get("inline") or "").lower() in (
            "1",
            "true",
            "yes",
        )
        return _file_response(material, inline=inline)


def _file_response(material: CourseMaterial, *, inline: bool = False):
    filename = os.path.basename(material.file.name)
    content_type, _ = mimetypes.guess_type(filename)
    # Browsers only preview PDF reliably in-tab; force pdf content type when needed.
    if inline and filename.lower().endswith(".pdf"):
        content_type = "application/pdf"
    response = FileResponse(
        material.file.open("rb"),
        as_attachment=not inline,
        filename=filename,
        content_type=content_type or "application/octet-stream",
    )
    if inline:
        response["Content-Disposition"] = f'inline; filename="{filename}"'
        response["X-Content-Type-Options"] = "nosniff"
    return response
