"""Phase 2: exam timetable, sitting lists, retake registration."""
import csv
import io

from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from Programs.models import CourseUnit, StudentCourseUnitEnrollment, Venue

from .models import CourseUnitResult, ExamRetakeRegistration, ExamSession
from .permissions import CanManageExamSchedule, CanManageRetakes, CanViewAllResults
from .serializers import ExamRetakeRegistrationSerializer, ExamSessionSerializer
from .services.clash import (
    evaluate_session_issues,
    wants_force,
)
from .services.eligibility import evaluate_exam_eligibility, sitting_row_for_enrollment
from .services.policy_resolver import resolve_assessment_policy
from .views import _get_course_unit_or_404, _student_for_user


def _conflict_response(conflicts):
    return Response(
        {
            "detail": "Scheduling conflicts detected. Pass force=true to save anyway.",
            "conflicts": conflicts,
        },
        status=409,
    )


def _issues_for_validated(validated, *, course_unit, exclude_session_id=None, invigilator_ids=None):
    venue = validated.get("venue")
    return evaluate_session_issues(
        course_unit=course_unit,
        exam_date=validated.get("exam_date"),
        start_time=validated.get("start_time"),
        end_time=validated.get("end_time"),
        venue=venue,
        max_candidates=validated.get("max_candidates"),
        session_type=validated.get("session_type") or ExamSession.TYPE_REGULAR,
        exclude_session_id=exclude_session_id,
        invigilator_ids=invigilator_ids,
    )


def _wants_csv(request) -> bool:
    raw = (request.query_params.get("export") or request.query_params.get("download") or "").lower()
    return raw == "csv"


def _sitting_csv_response(rows, filename: str) -> HttpResponse:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["reg_no", "student_name", "ca_mark", "eligible_to_sit", "notes"]
    )
    for row in rows:
        notes = "; ".join(
            row.get("eligibility", {}).get("blockers")
            or row.get("eligibility", {}).get("reasons")
            or []
        )
        writer.writerow(
            [
                row.get("reg_no", ""),
                row.get("student_name", ""),
                row.get("ca_mark") if row.get("ca_mark") is not None else "",
                "Yes" if row.get("eligible_to_sit") else "No",
                notes,
            ]
        )
    resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


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


def _retake_candidate_enrollments_for_course(course_unit):
    return (
        StudentCourseUnitEnrollment.objects.filter(
            course_unit=course_unit,
            course_result__status=CourseUnitResult.STATUS_PUBLISHED,
            course_result__is_pass=False,
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
        invigilator_ids = serializer.validated_data.get("invigilator_ids")
        conflicts = _issues_for_validated(
            serializer.validated_data,
            course_unit=course_unit,
            invigilator_ids=invigilator_ids,
        )
        if conflicts and not wants_force(request.data):
            return _conflict_response(conflicts)
        session = serializer.save(created_by=request.user)
        payload = ExamSessionSerializer(session).data
        if conflicts:
            payload["warnings"] = conflicts
        return Response(payload, status=201)


class ExamSessionBulkGenerateView(APIView):
    """Create one exam session per enrolled course unit in a batch/semester."""

    permission_classes = [IsAuthenticated, CanManageExamSchedule]

    def post(self, request):
        program_batch_id = request.data.get("program_batch_id")
        if not program_batch_id:
            return Response({"detail": "program_batch_id is required."}, status=400)

        exam_date = request.data.get("exam_date")
        if not exam_date:
            return Response({"detail": "exam_date is required."}, status=400)

        session_type = request.data.get("session_type") or ExamSession.TYPE_REGULAR
        valid_types = {c[0] for c in ExamSession.TYPE_CHOICES}
        if session_type not in valid_types:
            return Response({"detail": "Invalid session_type."}, status=400)

        semester_id = request.data.get("semester_id") or None
        start_time = request.data.get("start_time") or None
        end_time = request.data.get("end_time") or None
        venue_text = request.data.get("venue_text") or ""
        is_published = bool(request.data.get("is_published", False))

        # Normalize via serializer field parsers so Date/Time are real objects (not raw strings).
        try:
            exam_date = ExamSessionSerializer().fields["exam_date"].to_internal_value(exam_date)
            if start_time:
                start_time = ExamSessionSerializer().fields["start_time"].to_internal_value(start_time)
            else:
                start_time = None
            if end_time:
                end_time = ExamSessionSerializer().fields["end_time"].to_internal_value(end_time)
            else:
                end_time = None
        except Exception as exc:
            return Response({"detail": str(exc)}, status=400)

        venue = None
        venue_id = request.data.get("venue")
        if venue_id not in (None, ""):
            venue = get_object_or_404(Venue, pk=venue_id)

        qs = (
            CourseUnit.objects.filter(is_active=True, program_batch_id=program_batch_id)
            .annotate(
                students_count=Count(
                    "student_enrollments",
                    filter=Q(student_enrollments__status="enrolled"),
                    distinct=True,
                ),
            )
            .filter(students_count__gt=0)
            .order_by("semester__order", "code", "name")
        )
        if semester_id:
            qs = qs.filter(semester_id=semester_id)

        existing_ids = set(
            ExamSession.objects.filter(
                course_unit_id__in=qs.values_list("id", flat=True),
                session_type=session_type,
            ).values_list("course_unit_id", flat=True)
        )

        force = wants_force(request.data)
        created_sessions = []
        skipped = []
        all_warnings = []

        # Pre-check shared venue capacity / room for first unit only as shared fields apply to all
        sample = qs.exclude(id__in=existing_ids).first()
        if sample and not force:
            conflicts = evaluate_session_issues(
                course_unit=sample,
                exam_date=exam_date,
                start_time=start_time,
                end_time=end_time,
                venue=venue,
                session_type=session_type,
            )
            # Room-only conflicts matter for bulk shared venue; student clashes checked per unit below
            room_conflicts = [c for c in conflicts if c["type"] == "room"]
            if room_conflicts:
                return _conflict_response(room_conflicts)

        with transaction.atomic():
            for cu in qs:
                if cu.id in existing_ids:
                    skipped.append(
                        {
                            "course_unit_id": cu.id,
                            "course_code": cu.code,
                            "reason": f"Already has a {session_type} session",
                        }
                    )
                    continue
                unit_conflicts = evaluate_session_issues(
                    course_unit=cu,
                    exam_date=exam_date,
                    start_time=start_time,
                    end_time=end_time,
                    venue=venue,
                    session_type=session_type,
                )
                if unit_conflicts and not force:
                    # Soft-skip capacity/student for bulk: collect and continue only if force
                    # For warn mode without force, block entire bulk if any conflict
                    return _conflict_response(
                        [
                            {**c, "course_unit_id": cu.id, "course_code": cu.code}
                            for c in unit_conflicts
                        ]
                    )
                session = ExamSession.objects.create(
                    course_unit=cu,
                    session_type=session_type,
                    title=f"{cu.code} Examination",
                    exam_date=exam_date,
                    start_time=start_time or None,
                    end_time=end_time or None,
                    venue=venue,
                    venue_text=venue_text,
                    is_published=is_published,
                    created_by=request.user,
                )
                created_sessions.append(session)
                if unit_conflicts:
                    all_warnings.extend(
                        {**c, "course_unit_id": cu.id, "course_code": cu.code}
                        for c in unit_conflicts
                    )

        payload = {
            "created": len(created_sessions),
            "skipped": skipped,
            "sessions": ExamSessionSerializer(created_sessions, many=True).data,
        }
        if all_warnings:
            payload["warnings"] = all_warnings
        if is_published and created_sessions:
            from .tasks import notify_exam_session_published

            for s in created_sessions:
                try:
                    notify_exam_session_published.delay(s.id)
                except Exception:
                    notify_exam_session_published(s.id)
        return Response(payload, status=201)


class ExamSessionListView(APIView):
    """List all exam sessions for a programme batch (optional semester)."""

    permission_classes = [IsAuthenticated, CanManageExamSchedule]

    def get(self, request):
        program_batch_id = request.query_params.get("program_batch_id")
        if not program_batch_id:
            return Response({"detail": "program_batch_id is required."}, status=400)

        qs = (
            ExamSession.objects.filter(course_unit__program_batch_id=program_batch_id)
            .select_related("course_unit", "venue")
            .prefetch_related("invigilators")
            .order_by("exam_date", "start_time", "course_unit__code", "id")
        )
        semester_id = request.query_params.get("semester_id")
        if semester_id:
            qs = qs.filter(course_unit__semester_id=semester_id)
        course_unit_id = request.query_params.get("course_unit_id")
        if course_unit_id:
            qs = qs.filter(course_unit_id=course_unit_id)

        return Response(
            {
                "sessions": ExamSessionSerializer(qs, many=True).data,
                "total": qs.count(),
            }
        )


class ExamSessionDetailView(APIView):
    permission_classes = [IsAuthenticated, CanManageExamSchedule]

    def patch(self, request, session_id):
        session = get_object_or_404(
            ExamSession.objects.select_related("course_unit", "venue").prefetch_related(
                "invigilators"
            ),
            pk=session_id,
        )
        was_published = session.is_published
        serializer = ExamSessionSerializer(session, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        merged = {
            "exam_date": serializer.validated_data.get("exam_date", session.exam_date),
            "start_time": serializer.validated_data.get("start_time", session.start_time),
            "end_time": serializer.validated_data.get("end_time", session.end_time),
            "venue": serializer.validated_data.get("venue", session.venue),
            "max_candidates": serializer.validated_data.get(
                "max_candidates", session.max_candidates
            ),
            "session_type": serializer.validated_data.get(
                "session_type", session.session_type
            ),
        }
        invigilator_ids = serializer.validated_data.get("invigilator_ids")
        if invigilator_ids is None:
            invigilator_ids = list(session.invigilators.values_list("id", flat=True))

        conflicts = evaluate_session_issues(
            course_unit=session.course_unit,
            exam_date=merged["exam_date"],
            start_time=merged["start_time"],
            end_time=merged["end_time"],
            venue=merged["venue"],
            max_candidates=merged["max_candidates"],
            session_type=merged["session_type"],
            exclude_session_id=session.id,
            invigilator_ids=invigilator_ids,
        )
        if conflicts and not wants_force(request.data):
            return _conflict_response(conflicts)

        serializer.save()
        session.refresh_from_db()
        payload = ExamSessionSerializer(session).data
        if conflicts:
            payload["warnings"] = conflicts

        if not was_published and session.is_published:
            from .tasks import notify_exam_session_published

            try:
                notify_exam_session_published.delay(session.id)
            except Exception:
                notify_exam_session_published(session.id)

        return Response(payload)

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
        enrollments = (
            _retake_candidate_enrollments_for_course(course_unit)
            if session_type in (ExamSession.TYPE_RETAKE, ExamSession.TYPE_SUPPLEMENTARY)
            else _enrollments_for_course(course_unit)
        )

        for enr in enrollments:
            if enr.student.application and enr.student.application.is_revoked:
                continue
            row_policy = resolve_assessment_policy(enrollment=enr) or policy
            row = sitting_row_for_enrollment(
                enr, policy=row_policy, session_type=session_type
            )
            if row["eligible_to_sit"]:
                eligible_count += 1
            rows.append(row)

        if _wants_csv(request):
            return _sitting_csv_response(
                rows, f"sitting-list-{course_unit.code}-{session_type}.csv"
            )

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
                "effective_capacity": None,
                "candidate_count": len(rows),
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
                for enr in _retake_candidate_enrollments_for_course(session.course_unit):
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

        if _wants_csv(request):
            return _sitting_csv_response(
                rows,
                f"sitting-list-session-{session.id}-{session.course_unit.code}.csv",
            )

        from .services.clash import effective_capacity

        return Response(
            {
                "session": ExamSessionSerializer(session).data,
                "total": len(rows),
                "eligible_count": eligible_count,
                "ineligible_count": len(rows) - eligible_count,
                "effective_capacity": effective_capacity(session),
                "candidate_count": len(rows),
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
            StudentCourseUnitEnrollment.objects.select_related("course_result"),
            pk=enrollment_id,
            course_unit=course_unit,
        )
        result = getattr(enrollment, "course_result", None)
        if not (
            result
            and result.status == CourseUnitResult.STATUS_PUBLISHED
            and result.is_pass is False
        ):
            return Response(
                {"detail": "Only students with failed published results can be registered for retake."},
                status=400,
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


class StudentRetakeRequestView(APIView):
    """Student self-service retake request for a failed published result."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        student = _student_for_user(request.user)
        if not student:
            return Response({"detail": "Student record not found."}, status=404)

        enrollment_id = request.data.get("enrollment_id")
        if not enrollment_id:
            return Response({"detail": "enrollment_id is required."}, status=400)

        enrollment = get_object_or_404(
            StudentCourseUnitEnrollment.objects.select_related("course_result", "course_unit"),
            pk=enrollment_id,
            student=student,
        )
        result = getattr(enrollment, "course_result", None)
        if (
            not result
            or result.status != CourseUnitResult.STATUS_PUBLISHED
            or result.is_pass is not False
        ):
            return Response(
                {"detail": "Retake requests are only allowed for published failed results."},
                status=400,
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
                {"detail": "An active retake registration already exists for this course."},
                status=400,
            )

        reg = ExamRetakeRegistration.objects.create(
            enrollment=enrollment,
            reason=(request.data.get("reason") or "").strip(),
            status=ExamRetakeRegistration.STATUS_PENDING,
        )
        return Response(ExamRetakeRegistrationSerializer(reg).data, status=201)
