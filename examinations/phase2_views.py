"""Phase 2: exam timetable, sitting lists, retake registration."""
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.models import AdmittedStudent
from Programs.models import CourseUnit, StudentCourseUnitEnrollment

from .models import ExamRetakeRegistration, ExamSession
from .permissions import CanManageExamSchedule, CanManageRetakes, CanViewAllResults
from .serializers import ExamRetakeRegistrationSerializer, ExamSessionSerializer
from .services.eligibility import evaluate_exam_eligibility, sitting_row_for_enrollment
from .services.policy_resolver import resolve_assessment_policy
from .views import _get_course_unit_or_404, _student_for_user


def _enrollments_for_course(course_unit):
    return (
        StudentCourseUnitEnrollment.objects.filter(
            course_unit=course_unit,
            status="enrolled",
            registration_date__isnull=False,
        )
        .select_related(
            "student",
            "student__application",
            "course_result",
            "course_unit",
            "course_unit__program_batch__program__academic_level",
        )
        .order_by("student__reg_no")
    )


class CourseExamSessionsView(APIView):
    """List or create exam sessions for a course unit."""

    permission_classes = [IsAuthenticated, CanManageExamSchedule]

    def get(self, request, course_unit_id):
        try:
            course_unit = _get_course_unit_or_404(course_unit_id)
        except CourseUnit.DoesNotExist:
            return Response({"detail": "Course unit not found."}, status=404)

        sessions = (
            ExamSession.objects.filter(course_unit=course_unit)
            .select_related("course_unit", "venue")
            .order_by("exam_date", "start_time")
        )
        return Response(
            {
                "course_unit_id": course_unit.id,
                "course_code": course_unit.code,
                "course_name": course_unit.name,
                "sessions": ExamSessionSerializer(sessions, many=True).data,
            }
        )

    def post(self, request, course_unit_id):
        try:
            course_unit = _get_course_unit_or_404(course_unit_id)
        except CourseUnit.DoesNotExist:
            return Response({"detail": "Course unit not found."}, status=404)

        data = {**request.data, "course_unit": course_unit.id}
        serializer = ExamSessionSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        session = serializer.save(created_by=request.user)
        return Response(ExamSessionSerializer(session).data, status=201)


class ExamSessionDetailView(APIView):
    permission_classes = [IsAuthenticated, CanManageExamSchedule]

    def patch(self, request, session_id):
        session = get_object_or_404(
            ExamSession.objects.select_related("course_unit", "venue"),
            pk=session_id,
        )
        serializer = ExamSessionSerializer(session, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, session_id):
        session = get_object_or_404(ExamSession, pk=session_id)
        session.delete()
        return Response(status=204)


class CourseSittingListView(APIView):
    """Eligible / ineligible students for exam sitting on a course."""

    permission_classes = [IsAuthenticated, CanViewAllResults]

    def get(self, request, course_unit_id):
        try:
            course_unit = _get_course_unit_or_404(course_unit_id)
        except CourseUnit.DoesNotExist:
            return Response({"detail": "Course unit not found."}, status=404)

        policy = resolve_assessment_policy(course_unit=course_unit)
        session_type = request.query_params.get("session_type", ExamSession.TYPE_REGULAR)

        rows = []
        eligible_count = 0
        for enr in _enrollments_for_course(course_unit):
            if enr.student.application and enr.student.application.is_revoked:
                continue
            row_policy = resolve_assessment_policy(enrollment=enr) or policy
            row = sitting_row_for_enrollment(
                enr, policy=row_policy, session_type=session_type
            )
            if row["eligible_to_sit"]:
                eligible_count += 1
            rows.append(row)

        return Response(
            {
                "course_unit_id": course_unit.id,
                "course_code": course_unit.code,
                "course_name": course_unit.name,
                "session_type": session_type,
                "policy": {
                    "min_ca_to_sit_exam": str(policy.min_ca_to_sit_exam) if policy else "17.5",
                    "ca_max": str(policy.ca_max) if policy else "40",
                    "pass_mark": str(policy.pass_mark) if policy else "50",
                },
                "total_enrolled": len(rows),
                "eligible_count": eligible_count,
                "ineligible_count": len(rows) - eligible_count,
                "rows": rows,
            }
        )


class ExamSessionSittingListView(APIView):
    """Sitting list for one scheduled session (regular = all enrolled; retake = approved retakes)."""

    permission_classes = [IsAuthenticated, CanManageExamSchedule]

    def get(self, request, session_id):
        session = get_object_or_404(
            ExamSession.objects.select_related("course_unit", "venue"),
            pk=session_id,
        )
        policy = resolve_assessment_policy(course_unit=session.course_unit)
        rows = []

        if session.session_type == ExamSession.TYPE_REGULAR:
            for enr in _enrollments_for_course(session.course_unit):
                if enr.student.application and enr.student.application.is_revoked:
                    continue
                row_policy = resolve_assessment_policy(enrollment=enr) or policy
                rows.append(
                    sitting_row_for_enrollment(
                        enr, policy=row_policy, session_type=session.session_type
                    )
                )
        else:
            retakes = session.retake_registrations.filter(
                status__in=(
                    ExamRetakeRegistration.STATUS_APPROVED,
                    ExamRetakeRegistration.STATUS_SCHEDULED,
                )
            ).select_related(
                "enrollment",
                "enrollment__student",
                "enrollment__student__application",
                "enrollment__course_result",
            )
            if not retakes.exists() and session.session_type == ExamSession.TYPE_RETAKE:
                for enr in _enrollments_for_course(session.course_unit):
                    if enr.student.application and enr.student.application.is_revoked:
                        continue
                    el = evaluate_exam_eligibility(enr, policy=policy)
                    result = getattr(enr, "course_result", None)
                    if el["failed_published"] or (
                        result
                        and result.status == CourseUnitResult.STATUS_PUBLISHED
                        and result.is_pass is False
                    ):
                        rows.append(
                            sitting_row_for_enrollment(
                                enr, policy=policy, session_type=session.session_type
                            )
                        )
            else:
                for reg in retakes:
                    rows.append(
                        sitting_row_for_enrollment(
                            reg.enrollment, policy=policy, session_type=session.session_type
                        )
                    )

        eligible_count = sum(1 for r in rows if r["eligible_to_sit"])

        return Response(
            {
                "session": ExamSessionSerializer(session).data,
                "total": len(rows),
                "eligible_count": eligible_count,
                "rows": rows,
            }
        )


class CourseRetakeRegistrationsView(APIView):
    permission_classes = [IsAuthenticated, CanManageRetakes]

    def get(self, request, course_unit_id):
        course_unit = get_object_or_404(CourseUnit, pk=course_unit_id, is_active=True)
        qs = (
            ExamRetakeRegistration.objects.filter(enrollment__course_unit=course_unit)
            .select_related(
                "enrollment",
                "enrollment__student",
                "exam_session",
            )
            .order_by("-requested_at")
        )
        return Response(
            {
                "course_unit_id": course_unit.id,
                "registrations": ExamRetakeRegistrationSerializer(qs, many=True).data,
            }
        )

    def post(self, request, course_unit_id):
        course_unit = get_object_or_404(CourseUnit, pk=course_unit_id, is_active=True)
        enrollment_id = request.data.get("enrollment_id")
        if not enrollment_id:
            return Response({"detail": "enrollment_id is required."}, status=400)

        enrollment = get_object_or_404(
            StudentCourseUnitEnrollment,
            pk=enrollment_id,
            course_unit=course_unit,
            status="enrolled",
        )

        if ExamRetakeRegistration.objects.filter(
            enrollment=enrollment,
            status__in=(
                ExamRetakeRegistration.STATUS_PENDING,
                ExamRetakeRegistration.STATUS_APPROVED,
                ExamRetakeRegistration.STATUS_SCHEDULED,
            ),
        ).exists():
            return Response(
                {"detail": "An active retake registration already exists for this student."},
                status=400,
            )

        reg = ExamRetakeRegistration.objects.create(
            enrollment=enrollment,
            reason=(request.data.get("reason") or "").strip(),
            status=ExamRetakeRegistration.STATUS_PENDING,
        )
        return Response(ExamRetakeRegistrationSerializer(reg).data, status=201)


class ExamRetakeDetailView(APIView):
    permission_classes = [IsAuthenticated, CanManageRetakes]

    def patch(self, request, registration_id):
        reg = get_object_or_404(
            ExamRetakeRegistration.objects.select_related("enrollment", "exam_session"),
            pk=registration_id,
        )
        new_status = request.data.get("status")
        exam_session_id = request.data.get("exam_session")

        if new_status and new_status not in dict(ExamRetakeRegistration.STATUS_CHOICES):
            return Response({"detail": "Invalid status."}, status=400)

        with transaction.atomic():
            if new_status:
                reg.status = new_status
                reg.reviewed_by = request.user
                reg.reviewed_at = timezone.now()

            if exam_session_id is not None:
                if exam_session_id:
                    session = get_object_or_404(ExamSession, pk=exam_session_id)
                    if session.course_unit_id != reg.enrollment.course_unit_id:
                        return Response(
                            {"detail": "Exam session must be for the same course unit."},
                            status=400,
                        )
                    reg.exam_session = session
                    if reg.status == ExamRetakeRegistration.STATUS_APPROVED:
                        reg.status = ExamRetakeRegistration.STATUS_SCHEDULED
                else:
                    reg.exam_session = None

            if "admin_notes" in request.data:
                reg.admin_notes = (request.data.get("admin_notes") or "").strip()

            reg.save()

        return Response(ExamRetakeRegistrationSerializer(reg).data)


class StudentMyExamScheduleView(APIView):
    """Published exam sessions for courses the student is enrolled in."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        student = _student_for_user(request.user)
        if not student:
            return Response({"detail": "Student record not found."}, status=404)

        enrollment_ids = StudentCourseUnitEnrollment.objects.filter(
            student=student,
            status="enrolled",
        ).values_list("course_unit_id", flat=True)

        sessions = (
            ExamSession.objects.filter(
                course_unit_id__in=enrollment_ids,
                is_published=True,
            )
            .select_related("course_unit", "course_unit__semester", "venue")
            .order_by("exam_date", "start_time")
        )

        items = []
        for session in sessions:
            enrollment = (
                StudentCourseUnitEnrollment.objects.filter(
                    student=student,
                    course_unit=session.course_unit,
                    status="enrolled",
                )
                .select_related(
                    "course_result",
                    "course_unit",
                    "course_unit__program_batch__program__academic_level",
                )
                .first()
            )
            row_policy = (
                resolve_assessment_policy(enrollment=enrollment) if enrollment else None
            )
            eligibility = (
                evaluate_exam_eligibility(enrollment, policy=row_policy)
                if enrollment
                else {"eligible": False, "blockers": ["Not enrolled"]}
            )
            items.append(
                {
                    **ExamSessionSerializer(session).data,
                    "eligibility": eligibility,
                }
            )

        retakes = ExamRetakeRegistration.objects.filter(
            enrollment__student=student,
        ).exclude(status=ExamRetakeRegistration.STATUS_REJECTED).select_related(
            "exam_session", "enrollment__course_unit"
        )

        return Response(
            {
                "sessions": items,
                "retake_registrations": ExamRetakeRegistrationSerializer(retakes, many=True).data,
            }
        )
