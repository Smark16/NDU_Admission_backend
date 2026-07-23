"""Phase 3: verify workflow, bulk publish, import, transcript, reports."""
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.models import AdmittedStudent
from Programs.models import CourseUnit, Semester, StudentCourseUnitEnrollment

from .models import CourseUnitResult
from .permissions import (
    CanEnterMarksOrAssignedLecturer,
    CanPublishResults,
    CanViewAllResults,
    user_can_access_examinations_office,
    user_can_manage_course_marks,
    user_can_publish_course,
)
from .serializers import CourseUnitResultSerializer
from .services.import_marks import (
    build_marks_entry_csv,
    import_marks_for_course,
    parse_marks_upload,
)
from .services.mark_completeness import collect_incomplete_results
from .services.marks_window import assert_marks_entry_allowed
from .services.publish import publish_result, sync_enrollment_from_result, verify_result
from .services.provisional_results_pdf import (
    render_provisional_results_html,
    render_provisional_results_pdf,
)
from .services.transcript import build_student_transcript
from .views import _get_course_unit_or_404, _student_for_user


class VerifyCourseMarksView(APIView):
    """Move draft marks to verified/submitted (ready for a publisher to publish)."""

    permission_classes = [IsAuthenticated, CanEnterMarksOrAssignedLecturer]

    def post(self, request, course_unit_id):
        try:
            course_unit = _get_course_unit_or_404(course_unit_id)
        except CourseUnit.DoesNotExist:
            return Response({"detail": "Course unit not found."}, status=404)

        if not user_can_manage_course_marks(request.user, course_unit):
            return Response(
                {"detail": "You do not have permission to submit marks for this course."},
                status=403,
            )

        try:
            assert_marks_entry_allowed(course_unit, user=request.user)
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=403)

        drafts = CourseUnitResult.objects.filter(
            enrollment__course_unit=course_unit,
            status=CourseUnitResult.STATUS_DRAFT,
        ).select_related("enrollment__student", "policy")

        incomplete = collect_incomplete_results(drafts)
        if incomplete:
            return Response(
                {
                    "detail": "Cannot submit: some draft results have incomplete marks.",
                    "incomplete": incomplete,
                },
                status=400,
            )

        verified = 0
        with transaction.atomic():
            for result in drafts:
                verify_result(result, user=request.user)
                verified += 1

        return Response(
            {
                "course_unit_id": course_unit_id,
                "verified_count": verified,
                "message": f"Submitted {verified} result(s).",
            }
        )


class BulkPublishView(APIView):
    """Verify + publish all draft/verified results for a semester or program batch."""

    permission_classes = [IsAuthenticated, CanPublishResults]

    def post(self, request):
        semester_id = request.data.get("semester_id")
        program_batch_id = request.data.get("program_batch_id")
        verify_only = request.data.get("verify_only", False)
        force = request.data.get("force", False)

        if not semester_id and not program_batch_id:
            return Response(
                {"detail": "Provide semester_id or program_batch_id."},
                status=400,
            )

        qs = CourseUnitResult.objects.select_related("enrollment", "enrollment__course_unit")
        if semester_id:
            qs = qs.filter(enrollment__course_unit__semester_id=semester_id)
        if program_batch_id:
            qs = qs.filter(enrollment__course_unit__program_batch_id=program_batch_id)

        verified_count = 0
        published_count = 0

        with transaction.atomic():
            if verify_only or not force:
                draft_qs = qs.filter(status=CourseUnitResult.STATUS_DRAFT).select_related(
                    "enrollment__student", "policy"
                )
                incomplete = collect_incomplete_results(draft_qs)
                if incomplete:
                    return Response(
                        {
                            "detail": "Cannot verify: some draft results have incomplete marks.",
                            "incomplete": incomplete,
                        },
                        status=400,
                    )
                for result in draft_qs:
                    verify_result(result, user=request.user)
                    verified_count += 1

            if not verify_only:
                statuses = [CourseUnitResult.STATUS_VERIFIED]
                if force:
                    statuses.append(CourseUnitResult.STATUS_DRAFT)
                publish_qs = qs.filter(status__in=statuses).select_related(
                    "enrollment__student", "policy"
                )
                incomplete = collect_incomplete_results(publish_qs)
                if incomplete:
                    return Response(
                        {
                            "detail": "Cannot publish: some results have incomplete marks.",
                            "incomplete": incomplete,
                        },
                        status=400,
                    )
                for result in publish_qs:
                    if result.status == CourseUnitResult.STATUS_DRAFT:
                        verify_result(result, user=request.user)
                    publish_result(result, user=request.user)
                    published_count += 1

        return Response(
            {
                "verified_count": verified_count,
                "published_count": published_count,
                "message": "Bulk operation complete.",
            }
        )


class ImportCourseMarksView(APIView):
    permission_classes = [IsAuthenticated, CanEnterMarksOrAssignedLecturer]

    def post(self, request, course_unit_id):
        course_unit = get_object_or_404(CourseUnit, pk=course_unit_id, is_active=True)
        if not user_can_manage_course_marks(request.user, course_unit):
            return Response(
                {"detail": "You are not assigned to this course."},
                status=403,
            )
        try:
            assert_marks_entry_allowed(course_unit, user=request.user)
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=403)
        upload = request.FILES.get("file")
        if not upload:
            return Response({"detail": "Upload a CSV or Excel file as 'file'."}, status=400)

        try:
            rows = parse_marks_upload(upload.name, upload.read())
            outcome = import_marks_for_course(course_unit, rows, user=request.user)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=400)

        return Response(outcome)


class MarksEntryTemplateView(APIView):
    """Download CSV template with enrolled students for marks entry."""

    permission_classes = [IsAuthenticated, CanEnterMarksOrAssignedLecturer]

    def get(self, request, course_unit_id):
        course_unit = get_object_or_404(CourseUnit, pk=course_unit_id, is_active=True)
        if not user_can_manage_course_marks(request.user, course_unit):
            return Response(
                {"detail": "You are not assigned to this course."},
                status=403,
            )
        filename, csv_text = build_marks_entry_csv(course_unit)
        response = HttpResponse(csv_text, content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class StudentTranscriptView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, student_id=None):
        if student_id:
            if not user_can_access_examinations_office(request.user):
                return Response({"detail": "Forbidden."}, status=403)
            student = get_object_or_404(AdmittedStudent, pk=student_id, is_admitted=True)
        else:
            student = _student_for_user(request.user)
            if not student:
                return Response({"detail": "Student not found."}, status=404)

        # Use `output=pdf` — `format=pdf` is reserved by DRF content negotiation and returns 404.
        output = request.query_params.get("output", "").lower()
        if output in ("pdf", "html"):
            from .services.graduation_status import graduation_show_scores_default

            show_param = request.query_params.get("show_scores")
            if show_param is None:
                show_scores = graduation_show_scores_default(student)
            else:
                show_scores = show_param.lower() in ("1", "true", "yes")
            printed_by = request.user.get_full_name() or request.user.username
            try:
                if output == "html":
                    html = render_provisional_results_html(
                        student,
                        show_scores=show_scores,
                        printed_by=printed_by,
                        request=request,
                    )
                    return HttpResponse(html, content_type="text/html; charset=utf-8")

                pdf_bytes, doc_meta = render_provisional_results_pdf(
                    student,
                    show_scores=show_scores,
                    printed_by=printed_by,
                    request=request,
                )
            except Exception as exc:
                return Response(
                    {"detail": f"PDF generation failed: {exc}"},
                    status=500,
                )
            safe_reg = (student.reg_no or str(student.pk)).replace("/", "-")
            prefix = doc_meta.get("filename_prefix", "Results")
            response = HttpResponse(pdf_bytes, content_type="application/pdf")
            response["Content-Disposition"] = (
                f'attachment; filename="{prefix}_{safe_reg}.pdf"'
            )
            return response

        return Response(build_student_transcript(student))


class ResultsReportView(APIView):
    """Summary report by semester or batch."""

    permission_classes = [IsAuthenticated, CanViewAllResults]

    def get(self, request):
        semester_id = request.query_params.get("semester_id")
        program_batch_id = request.query_params.get("program_batch_id")
        course_unit_id = request.query_params.get("course_unit_id")

        qs = CourseUnitResult.objects.select_related(
            "enrollment",
            "enrollment__course_unit",
            "enrollment__student",
        )
        if course_unit_id:
            qs = qs.filter(enrollment__course_unit_id=course_unit_id)
        if semester_id:
            qs = qs.filter(enrollment__course_unit__semester_id=semester_id)
        if program_batch_id:
            qs = qs.filter(enrollment__course_unit__program_batch_id=program_batch_id)

        by_status = dict(
            qs.values("status")
            .annotate(c=Count("id"))
            .values_list("status", "c")
        )
        published = qs.filter(status=CourseUnitResult.STATUS_PUBLISHED)
        pass_count = published.filter(is_pass=True).count()
        fail_count = published.filter(is_pass=False).count()
        published_total = pass_count + fail_count
        pass_rate = (
            round(100.0 * pass_count / published_total, 1) if published_total else None
        )

        grade_distribution = list(
            published.exclude(grade_letter="")
            .exclude(grade_letter__isnull=True)
            .values("grade_letter")
            .annotate(count=Count("id"))
            .order_by("grade_letter")
        )

        courses = []
        if semester_id or program_batch_id or course_unit_id:
            cu_qs = CourseUnit.objects.filter(is_active=True)
            if course_unit_id:
                cu_qs = cu_qs.filter(id=course_unit_id)
            if semester_id:
                cu_qs = cu_qs.filter(semester_id=semester_id)
            if program_batch_id:
                cu_qs = cu_qs.filter(program_batch_id=program_batch_id)
            for cu in cu_qs.order_by("code"):
                enrolled = StudentCourseUnitEnrollment.objects.filter(
                    course_unit=cu, status="enrolled"
                ).count()
                cu_results = qs.filter(enrollment__course_unit=cu)
                cu_published = cu_results.filter(status=CourseUnitResult.STATUS_PUBLISHED)
                cu_pass = cu_published.filter(is_pass=True).count()
                cu_fail = cu_published.filter(is_pass=False).count()
                cu_pub_total = cu_pass + cu_fail
                courses.append(
                    {
                        "course_unit_id": cu.id,
                        "course_code": cu.code,
                        "course_name": cu.name,
                        "enrolled": enrolled,
                        "draft": cu_results.filter(status=CourseUnitResult.STATUS_DRAFT).count(),
                        "verified": cu_results.filter(status=CourseUnitResult.STATUS_VERIFIED).count(),
                        "published": cu_published.count(),
                        "published_pass": cu_pass,
                        "published_fail": cu_fail,
                        "pass_rate": (
                            round(100.0 * cu_pass / cu_pub_total, 1) if cu_pub_total else None
                        ),
                    }
                )

        return Response(
            {
                "by_status": by_status,
                "published_pass": pass_count,
                "published_fail": fail_count,
                "published_total": published_total,
                "pass_rate": pass_rate,
                "grade_distribution": grade_distribution,
                "courses": courses,
            }
        )
