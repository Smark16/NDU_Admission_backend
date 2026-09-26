"""Phase 3: verify workflow, bulk publish, import, transcript, reports."""
import logging

from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.faculty_scope import (
    filter_course_unit_results_for_user,
    filter_course_units_for_user,
)
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
from .services.academic_broadsheet import (
    academic_broadsheet_xlsx,
    build_academic_broadsheet,
)
from .services.transcript import (
    TRANSCRIPT_REQUIRES_PUBLISHED_MARKS,
    build_student_transcript,
    student_has_published_marks,
)
from .views import _get_course_unit_or_404, _student_for_user

logger = logging.getLogger(__name__)


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

        raw_ids = request.data.get("enrollment_ids") if hasattr(request.data, "get") else None
        if raw_ids is not None:
            if not isinstance(raw_ids, list) or not raw_ids:
                return Response(
                    {"detail": "enrollment_ids must be a non-empty list of enrollment ids."},
                    status=400,
                )
            try:
                enrollment_ids = [int(x) for x in raw_ids]
            except (TypeError, ValueError):
                return Response(
                    {"detail": "enrollment_ids must contain integers."},
                    status=400,
                )
            drafts = drafts.filter(enrollment_id__in=enrollment_ids)

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

        if verified:
            from .utils.email import send_marks_submitted_email

            try:
                send_marks_submitted_email(
                    course_unit, submitted_by=request.user, submitted_count=verified,
                )
            except Exception:
                logger.exception(
                    "Failed to send marks-submitted notification for course_unit id=%s",
                    course_unit_id,
                )

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
        qs = filter_course_unit_results_for_user(qs, request.user)
        if semester_id:
            qs = qs.filter(enrollment__course_unit__semester_id=semester_id)
        if program_batch_id:
            qs = qs.filter(enrollment__course_unit__program_batch_id=program_batch_id)

        verified_count = 0
        published_count = 0
        not_dean_approved_count = 0
        from accounts.super_admin import user_is_super_admin
        override = user_is_super_admin(request.user)

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
                    try:
                        publish_result(result, user=request.user, override=override)
                        published_count += 1
                    except PermissionError:
                        not_dean_approved_count += 1

        message = "Bulk operation complete."
        if not_dean_approved_count:
            message += (
                f" {not_dean_approved_count} result(s) skipped -- awaiting Dean approval."
            )
        return Response(
            {
                "verified_count": verified_count,
                "published_count": published_count,
                "not_dean_approved_count": not_dean_approved_count,
                "message": message,
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
            outcome = import_marks_for_course(
                course_unit,
                rows,
                user=request.user,
                filename=upload.name or "",
            )
        except Exception as exc:
            return Response({"detail": str(exc)}, status=400)

        return Response(outcome)


class CourseMarksImportListView(APIView):
    permission_classes = [IsAuthenticated, CanEnterMarksOrAssignedLecturer]

    def get(self, request, course_unit_id):
        course_unit = get_object_or_404(CourseUnit, pk=course_unit_id, is_active=True)
        if not user_can_manage_course_marks(request.user, course_unit):
            return Response(
                {"detail": "You are not assigned to this course."},
                status=403,
            )
        from .models import MarksImportBatch

        batches = MarksImportBatch.objects.filter(course_unit=course_unit)[:20]
        return Response(
            {
                "imports": [
                    {
                        "id": batch.id,
                        "filename": batch.filename,
                        "saved_count": batch.saved_count,
                        "created_at": batch.created_at.isoformat() if batch.created_at else None,
                        "purged_at": batch.purged_at.isoformat() if batch.purged_at else None,
                    }
                    for batch in batches
                ]
            }
        )


class PurgeMarksImportView(APIView):
    permission_classes = [IsAuthenticated, CanEnterMarksOrAssignedLecturer]

    def post(self, request, batch_id):
        from django.core.exceptions import ValidationError

        from .models import MarksImportBatch
        from .services.import_marks import purge_marks_import

        batch = get_object_or_404(
            MarksImportBatch.objects.select_related("course_unit"),
            pk=batch_id,
        )
        if not user_can_manage_course_marks(request.user, batch.course_unit):
            return Response(
                {"detail": "You are not assigned to this course."},
                status=403,
            )
        try:
            assert_marks_entry_allowed(batch.course_unit, user=request.user)
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=403)
        try:
            return Response(purge_marks_import(batch))
        except ValidationError as exc:
            detail = exc.messages[0] if getattr(exc, "messages", None) else str(exc)
            return Response({"detail": detail}, status=400)


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
            if not student_has_published_marks(student):
                return Response(
                    {"detail": TRANSCRIPT_REQUIRES_PUBLISHED_MARKS},
                    status=400,
                )

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
            filename = doc_meta.get("download_name") or "steward.pdf"
            response = HttpResponse(pdf_bytes, content_type="application/pdf")
            response["Content-Disposition"] = (
                f'attachment; filename="{filename}"'
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
        qs = filter_course_unit_results_for_user(qs, request.user)
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

        # Pre-publish visibility (super admin / HOD / exam coordinator, via
        # CanViewAllResults) — same breakdown but across ALL statuses, so
        # reviewers can see pass/fail and grade spread before publishing,
        # not just after. Published numbers above remain the official ones.
        all_pass_count = qs.filter(is_pass=True).count()
        all_fail_count = qs.filter(is_pass=False).count()
        all_total = all_pass_count + all_fail_count
        all_pass_rate = (
            round(100.0 * all_pass_count / all_total, 1) if all_total else None
        )
        all_grade_distribution = list(
            qs.exclude(grade_letter="")
            .exclude(grade_letter__isnull=True)
            .values("grade_letter")
            .annotate(count=Count("id"))
            .order_by("grade_letter")
        )

        courses = []
        if semester_id or program_batch_id or course_unit_id:
            cu_qs = filter_course_units_for_user(CourseUnit.objects.filter(is_active=True), request.user)
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
                cu_all_pass = cu_results.filter(is_pass=True).count()
                cu_all_fail = cu_results.filter(is_pass=False).count()
                cu_all_total = cu_all_pass + cu_all_fail
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
                        "all_pass": cu_all_pass,
                        "all_fail": cu_all_fail,
                        "all_pass_rate": (
                            round(100.0 * cu_all_pass / cu_all_total, 1) if cu_all_total else None
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
                "all_pass": all_pass_count,
                "all_fail": all_fail_count,
                "all_total": all_total,
                "all_pass_rate": all_pass_rate,
                "all_grade_distribution": all_grade_distribution,
                "courses": courses,
            }
        )


class AcademicBroadsheetView(APIView):
    """Programme results grid: Registration Number, Name, then Score / Grade / GP per course."""

    permission_classes = [IsAuthenticated, CanViewAllResults]

    def get(self, request):
        def _int_param(name):
            raw = (request.query_params.get(name) or "").strip()
            if not raw:
                return None
            try:
                return int(raw)
            except (TypeError, ValueError):
                return None

        try:
            def _flag(name):
                return (request.query_params.get(name) or "").strip().lower() in (
                    "1",
                    "true",
                    "yes",
                )

            payload = build_academic_broadsheet(
                request.user,
                program_id=_int_param("program_id"),
                program_batch_id=_int_param("program_batch_id"),
                semester_id=_int_param("semester_id"),
                first_sitting_only=_flag("first_sitting_only"),
                include_semester_one=_flag("include_semester_one"),
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)

        if (request.query_params.get("format") or "").strip().lower() == "xlsx":
            label = (payload.get("program_name") or "programme").replace(" ", "_")
            semester = (payload.get("semester_name") or "all_semesters").replace(" ", "_")
            safe = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in f"{label}_{semester}")
            response = HttpResponse(
                academic_broadsheet_xlsx(payload),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            response["Content-Disposition"] = f'attachment; filename="academic_report_{safe[:80]}.xlsx"'
            return response
        return Response(payload)
