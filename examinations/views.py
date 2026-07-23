from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

import logging

from admissions.models import AdmittedStudent
from Programs.models import CourseUnit, StudentCourseUnitEnrollment

from .models import AssessmentPolicy, CourseUnitResult, GradeScale
from .services.grade_scale_resolver import resolve_grade_scale
from .permissions import (
    CanAccessExaminationsOffice,
    CanEnterMarksOrAssignedLecturer,
    CanPublishResults,
    user_can_manage_course_marks,
    user_can_publish_course,
)
from .services.mark_completeness import collect_incomplete_results
from .services.marks_window import assert_marks_entry_allowed, marks_entry_status
from .services.policy_resolver import resolve_assessment_policy
from .services.publish import publish_result, verify_result
from .serializers import (
    AssessmentPolicySerializer,
    CourseUnitResultSerializer,
    GradeBandSerializer,
    SaveMarksSerializer,
)

logger = logging.getLogger(__name__)


def _get_course_unit_or_404(course_unit_id):
    return CourseUnit.objects.select_related(
        "semester", "program_batch", "program_batch__program__academic_level"
    ).get(pk=course_unit_id, is_active=True)


def _student_for_user(user):
    return (
        AdmittedStudent.objects.filter(is_admitted=True)
        .filter(student_user=user)
        .first()
        or AdmittedStudent.objects.filter(is_admitted=True, reg_no=user.username).first()
    )


class StaffExaminationCoursesView(APIView):
    """List course units for the examinations office (with enrollment counts)."""

    permission_classes = [IsAuthenticated, CanAccessExaminationsOffice]

    def get(self, request):
        program_id = request.query_params.get("program_id")
        program_batch_id = request.query_params.get("program_batch_id")
        semester_id = request.query_params.get("semester_id")

        try:
            qs = (
                CourseUnit.objects.filter(is_active=True)
                .filter(Q(semester_id__isnull=False) | Q(program_batch_id__isnull=False))
                .annotate(
                    students_count=Count(
                        "student_enrollments",
                        filter=Q(student_enrollments__status="enrolled"),
                        distinct=True,
                    ),
                )
                .select_related("semester", "program_batch", "program_batch__program")
            )

            if program_id:
                qs = qs.filter(program_batch__program_id=program_id)
            if program_batch_id:
                qs = qs.filter(program_batch_id=program_batch_id)
            if semester_id:
                qs = qs.filter(semester_id=semester_id)

            qs = qs.order_by("semester__order", "code", "name")

            raw = request.query_params.get("with_students_only", "1")
            if raw.lower() in ("1", "true", "yes"):
                qs = qs.filter(students_count__gt=0)

            # Evaluate once so annotation filter errors surface clearly.
            course_units = list(qs)

            courses = []
            for cu in course_units:
                try:
                    entry_status = marks_entry_status(cu, user=request.user)
                except Exception:
                    logger.exception(
                        "marks_entry_status failed in staff courses list cu=%s", cu.pk
                    )
                    entry_status = {
                        "is_open": False,
                        "can_enter": False,
                        "override": False,
                        "detail": "Marks-entry window status unavailable.",
                        "window": None,
                    }
                courses.append(
                    {
                        "course_unit_id": cu.id,
                        "course_code": cu.code,
                        "course_name": cu.name,
                        "students_count": int(getattr(cu, "students_count", 0) or 0),
                        "semester_name": cu.semester.name if cu.semester_id else None,
                        "batch_name": cu.program_batch.name if cu.program_batch_id else None,
                        "program_name": (
                            cu.program_batch.program.name
                            if cu.program_batch_id and cu.program_batch.program_id
                            else None
                        ),
                        "marks_entry": entry_status,
                    }
                )

            return Response({"courses": courses, "total": len(courses)})
        except Exception as exc:
            logger.exception(
                "StaffExaminationCoursesView failed program=%s batch=%s semester=%s",
                program_id,
                program_batch_id,
                semester_id,
            )
            return Response(
                {"detail": f"Could not load examination courses: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

class LecturerCourseMarksView(APIView):
    """List or save draft marks for one course unit."""

    permission_classes = [IsAuthenticated, CanEnterMarksOrAssignedLecturer]

    def get(self, request, course_unit_id):
        try:
            course_unit = _get_course_unit_or_404(course_unit_id)
        except CourseUnit.DoesNotExist:
            return Response({"detail": "Course unit not found."}, status=404)

        if not user_can_manage_course_marks(request.user, course_unit):
            return Response({"detail": "You are not assigned to this course."}, status=403)

        policy = resolve_assessment_policy(course_unit=course_unit)
        if not policy:
            return Response({"detail": "No assessment policy configured."}, status=503)

        grade_scale = resolve_grade_scale(course_unit=course_unit)
        level_name = None
        if course_unit.program_batch_id:
            program = getattr(course_unit.program_batch, "program", None)
            level = getattr(program, "academic_level", None) if program else None
            level_name = level.name if level else None

        enrollments = (
            StudentCourseUnitEnrollment.objects.filter(
                course_unit=course_unit,
                status="enrolled",
            )
            .select_related("student", "student__application", "course_result")
            .order_by("student__reg_no")
        )

        rows = []
        for enr in enrollments:
            application = getattr(enr.student, "application", None)
            if application is not None and getattr(application, "is_revoked", False):
                continue
            result = getattr(enr, "course_result", None)
            try:
                student_name = enr.student.full_name or ""
            except Exception:
                student_name = ""
            rows.append(
                {
                    "enrollment_id": enr.id,
                    "reg_no": enr.student.reg_no or "",
                    "student_name": student_name,
                    "ca_mark": str(result.ca_mark) if result and result.ca_mark is not None else None,
                    "exam_mark": str(result.exam_mark) if result and result.exam_mark is not None else None,
                    "final_mark": str(result.final_mark) if result and result.final_mark is not None else None,
                    "exam_sitting_allowed": result.exam_sitting_allowed if result else False,
                    "is_pass": result.is_pass if result else None,
                    "grade_letter": result.grade_letter if result else "",
                    "grade_point": str(result.grade_point) if result and result.grade_point is not None else None,
                    "status": result.status if result else CourseUnitResult.STATUS_DRAFT,
                    "is_published": result.status == CourseUnitResult.STATUS_PUBLISHED if result else False,
                }
            )

        enrolled_count = enrollments.count()
        grade_bands = (
            list(GradeBandSerializer(grade_scale.bands.order_by("order"), many=True).data)
            if grade_scale
            else []
        )
        return Response(
            {
                "course_unit_id": course_unit.id,
                "course_code": course_unit.code,
                "course_name": course_unit.name,
                "policy": AssessmentPolicySerializer(policy).data,
                "policy_academic_level": level_name,
                "grading_scheme": grade_scale.name if grade_scale else None,
                "grade_bands": grade_bands,
                "marks_entry": marks_entry_status(course_unit, user=request.user),
                "enrolled_count": enrolled_count,
                "rows": rows,
            }
        )

    def post(self, request, course_unit_id):
        return self._save(request, course_unit_id)

    def patch(self, request, course_unit_id):
        return self._save(request, course_unit_id)

    def _save(self, request, course_unit_id):
        try:
            course_unit = _get_course_unit_or_404(course_unit_id)
        except CourseUnit.DoesNotExist:
            return Response({"detail": "Course unit not found."}, status=404)

        if not user_can_manage_course_marks(request.user, course_unit):
            return Response({"detail": "You are not assigned to this course."}, status=403)

        try:
            assert_marks_entry_allowed(course_unit, user=request.user)
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=403)

        serializer = SaveMarksSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        saved = []
        errors = []

        with transaction.atomic():
            for row in serializer.validated_data["marks"]:
                eid = row["enrollment_id"]
                try:
                    enrollment = StudentCourseUnitEnrollment.objects.select_related(
                        "student",
                        "student__application",
                        "course_result",
                        "course_unit",
                        "course_unit__program_batch__program__academic_level",
                    ).get(pk=eid, course_unit=course_unit, status="enrolled")
                except StudentCourseUnitEnrollment.DoesNotExist:
                    errors.append({"enrollment_id": eid, "detail": "Enrollment not found."})
                    continue

                if enrollment.student.application and enrollment.student.application.is_revoked:
                    errors.append({"enrollment_id": eid, "detail": "Student admission revoked."})
                    continue

                policy = resolve_assessment_policy(enrollment=enrollment)
                if not policy:
                    errors.append(
                        {"enrollment_id": eid, "detail": "No assessment policy configured."}
                    )
                    continue

                result, _ = CourseUnitResult.objects.get_or_create(
                    enrollment=enrollment,
                    defaults={"policy": policy, "entered_by": request.user},
                )

                if result.status == CourseUnitResult.STATUS_PUBLISHED and not result.edit_unlocked:
                    errors.append(
                        {
                            "enrollment_id": eid,
                            "detail": "Published — request a grade change or unlock first.",
                        }
                    )
                    continue

                result.policy = policy
                result.ca_mark = row.get("ca_mark")
                result.exam_mark = row.get("exam_mark")
                result.entered_by = request.user
                
                # Validate CA mark does not exceed policy maximum
                if result.ca_mark is not None and result.ca_mark < 0:
                    errors.append(
                        {"enrollment_id": eid, "detail": "CA mark cannot be negative."}
                    )
                    continue
                if result.ca_mark is not None and result.ca_mark > policy.ca_max:
                    errors.append(
                        {
                            "enrollment_id": eid,
                            "detail": f"CA mark ({result.ca_mark}) cannot exceed policy maximum ({policy.ca_max}).",
                        }
                    )
                    continue
                
                # Validate exam mark does not exceed 100
                if result.exam_mark is not None and result.exam_mark < 0:
                    errors.append(
                        {"enrollment_id": eid, "detail": "Exam mark cannot be negative."}
                    )
                    continue
                if result.exam_mark is not None and result.exam_mark > 100:
                    errors.append(
                        {
                            "enrollment_id": eid,
                            "detail": f"Exam mark ({result.exam_mark}) cannot exceed 100.",
                        }
                    )
                    continue
                
                if result.status in (
                    CourseUnitResult.STATUS_PUBLISHED,
                    CourseUnitResult.STATUS_VERIFIED,
                ):
                    result.status = CourseUnitResult.STATUS_VERIFIED
                    result.edit_unlocked = False
                else:
                    result.status = CourseUnitResult.STATUS_DRAFT
                try:
                    result.recompute()
                    result.full_clean()
                except Exception as exc:
                    errors.append({"enrollment_id": eid, "detail": str(exc)})
                    continue

                result.save()
                saved.append(CourseUnitResultSerializer(result).data)

        return Response(
            {"saved": saved, "errors": errors, "saved_count": len(saved)},
            status=200 if saved else 400,
        )


class PublishCourseMarksView(APIView):
    """Publish verified marks (use ?force=true to include draft)."""

    permission_classes = [IsAuthenticated, CanPublishResults]

    def post(self, request, course_unit_id):
        try:
            course_unit = _get_course_unit_or_404(course_unit_id)
        except CourseUnit.DoesNotExist:
            return Response({"detail": "Course unit not found."}, status=404)

        if not user_can_publish_course(request.user, course_unit):
            return Response(
                {"detail": "You do not have permission to publish marks for this course."},
                status=403,
            )

        force_raw = request.query_params.get("force")
        if force_raw is None and hasattr(request.data, "get"):
            force_raw = request.data.get("force")
        force = str(force_raw or "").lower() in ("1", "true", "yes")
        statuses = [CourseUnitResult.STATUS_VERIFIED]
        if force:
            statuses.append(CourseUnitResult.STATUS_DRAFT)

        published = 0
        with transaction.atomic():
            results = CourseUnitResult.objects.filter(
                enrollment__course_unit_id=course_unit_id,
                status__in=statuses,
            ).select_related("enrollment", "enrollment__student", "policy")

            incomplete = collect_incomplete_results(results)
            if incomplete:
                return Response(
                    {
                        "detail": "Cannot publish: some students have incomplete marks.",
                        "incomplete": incomplete,
                    },
                    status=400,
                )

            for result in results:
                if result.status == CourseUnitResult.STATUS_DRAFT:
                    verify_result(result, user=request.user)
                publish_result(result, user=request.user)
                published += 1

        return Response(
            {
                "course_unit_id": course_unit_id,
                "published_count": published,
                "message": f"Published {published} result(s).",
            }
        )


class StudentMyResultsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        student = _student_for_user(request.user)
        if not student:
            return Response({"detail": "Student record not found."}, status=404)

        results = (
            CourseUnitResult.objects.filter(
                enrollment__student=student,
                status=CourseUnitResult.STATUS_PUBLISHED,
            )
            .select_related("enrollment", "enrollment__course_unit", "enrollment__course_unit__semester")
            .order_by("enrollment__course_unit__semester__order", "enrollment__course_unit__code")
        )

        by_semester = {}
        for result in results:
            sem = result.enrollment.course_unit.semester
            key = sem.name if sem else "Other"
            by_semester.setdefault(key, []).append(CourseUnitResultSerializer(result).data)

        return Response(
            {
                "student": {
                    "reg_no": student.reg_no,
                    "name": student.full_name,
                },
                "semesters": [{"name": k, "courses": v} for k, v in by_semester.items()],
            }
        )
