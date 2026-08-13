"""Moodle-facing APIs (service API key auth)."""
from __future__ import annotations

from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from Programs.models import CourseUnit, Semester, StudentCourseUnitEnrollment

from .permissions import HasMoodleApiKey
from .services import (
    finance_status_for_student,
    lecturer_payload,
    log_moodle_access,
    resolve_student_by_lookup,
    student_profile_payload,
    verify_student_credentials,
)


def _key_prefix(request) -> str:
    return getattr(request, "moodle_api_key_prefix", "") or ""


class MoodleAuthVerifyView(APIView):
    authentication_classes = []
    permission_classes = [HasMoodleApiKey]

    def post(self, request):
        username = (request.data.get("username") or "").strip()
        password = request.data.get("password") or ""
        endpoint = "moodle/auth/verify"

        if not username or not password:
            log_moodle_access(
                endpoint=endpoint,
                http_status=400,
                key_prefix=_key_prefix(request),
                detail="missing credentials",
            )
            return Response(
                {"ok": False, "detail": "username and password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user, student = verify_student_credentials(username, password)
        if not user:
            log_moodle_access(
                endpoint=endpoint,
                http_status=401,
                key_prefix=_key_prefix(request),
                detail="auth failed",
            )
            return Response(
                {"ok": False, "detail": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        if not student:
            log_moodle_access(
                endpoint=endpoint,
                http_status=404,
                key_prefix=_key_prefix(request),
                detail="no admitted student",
            )
            return Response(
                {"ok": False, "detail": "No admitted student linked to this account."},
                status=status.HTTP_404_NOT_FOUND,
            )

        log_moodle_access(
            endpoint=endpoint,
            http_status=200,
            key_prefix=_key_prefix(request),
            detail=student.reg_no or "",
        )
        return Response(
            {
                "ok": True,
                "student": student_profile_payload(student, user),
            }
        )


class MoodleFinanceStatusView(APIView):
    authentication_classes = []
    permission_classes = [HasMoodleApiKey]

    def get(self, request, reg_no: str):
        endpoint = "moodle/finance-status"
        student = resolve_student_by_lookup(reg_no)
        if not student:
            log_moodle_access(
                endpoint=endpoint,
                http_status=404,
                key_prefix=_key_prefix(request),
                detail=reg_no,
            )
            return Response(
                {"ok": False, "detail": "Student not found.", "status": "BLOCKED"},
                status=status.HTTP_404_NOT_FOUND,
            )
        payload = finance_status_for_student(student)
        log_moodle_access(
            endpoint=endpoint,
            http_status=200,
            key_prefix=_key_prefix(request),
            detail=f"{student.reg_no}:{payload['status']}",
        )
        return Response({"ok": True, **payload})


class MoodleCurrentSemestersView(APIView):
    authentication_classes = []
    permission_classes = [HasMoodleApiKey]

    def get(self, request):
        endpoint = "moodle/semesters/current"
        today = timezone.now().date()
        qs = (
            Semester.objects.filter(is_active=True)
            .select_related("program_batch", "program_batch__program")
            .order_by("program_batch_id", "order")
        )
        # Prefer currently running windows when dates exist
        running = [
            s
            for s in qs
            if s.start_date
            and s.start_date <= today
            and (s.end_date is None or s.end_date >= today)
        ]
        semesters = running or list(qs[:50])
        rows = []
        for s in semesters:
            batch = s.program_batch
            program = batch.program if batch else None
            rows.append(
                {
                    "id": s.pk,
                    "name": s.name,
                    "order": s.order,
                    "year_of_study": s.year_of_study,
                    "term_number": s.term_number,
                    "start_date": s.start_date.isoformat() if s.start_date else None,
                    "end_date": s.end_date.isoformat() if s.end_date else None,
                    "program_batch_id": batch.pk if batch else None,
                    "program_batch_name": batch.name if batch else None,
                    "program_code": getattr(program, "short_form", None) if program else None,
                    "program_name": program.name if program else None,
                }
            )
        log_moodle_access(
            endpoint=endpoint,
            http_status=200,
            key_prefix=_key_prefix(request),
            detail=f"count={len(rows)}",
        )
        return Response({"ok": True, "semesters": rows})


class MoodleCourseUnitsView(APIView):
    authentication_classes = []
    permission_classes = [HasMoodleApiKey]

    def get(self, request):
        endpoint = "moodle/course-units"
        semester_id = request.query_params.get("semester_id")
        if not semester_id:
            log_moodle_access(
                endpoint=endpoint,
                http_status=400,
                key_prefix=_key_prefix(request),
                detail="missing semester_id",
            )
            return Response(
                {"ok": False, "detail": "semester_id query parameter is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            sid = int(semester_id)
        except (TypeError, ValueError):
            return Response(
                {"ok": False, "detail": "semester_id must be an integer."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        units = (
            CourseUnit.objects.filter(semester_id=sid, is_active=True)
            .prefetch_related("lecturers", "section_lecturers__lecturer")
            .order_by("code")
        )
        rows = []
        for cu in units:
            lecturers = {u.pk: lecturer_payload(u) for u in cu.lecturers.all()}
            for link in cu.section_lecturers.all():
                if link.lecturer_id and link.lecturer_id not in lecturers:
                    lecturers[link.lecturer_id] = lecturer_payload(link.lecturer)
            rows.append(
                {
                    "id": cu.pk,
                    "code": cu.code,
                    "name": cu.name,
                    "credit_units": float(cu.credit_units) if cu.credit_units is not None else None,
                    "semester_id": cu.semester_id,
                    "program_batch_id": cu.program_batch_id,
                    "idnumber": f"{cu.code}-{cu.semester_id}",
                    "lecturers": list(lecturers.values()),
                }
            )
        log_moodle_access(
            endpoint=endpoint,
            http_status=200,
            key_prefix=_key_prefix(request),
            detail=f"semester={sid};count={len(rows)}",
        )
        return Response({"ok": True, "semester_id": sid, "course_units": rows})


class MoodleEnrolledStudentsView(APIView):
    authentication_classes = []
    permission_classes = [HasMoodleApiKey]

    def get(self, request, course_unit_id: int):
        endpoint = "moodle/enrolled-students"
        cu = CourseUnit.objects.filter(pk=course_unit_id, is_active=True).first()
        if not cu:
            log_moodle_access(
                endpoint=endpoint,
                http_status=404,
                key_prefix=_key_prefix(request),
                detail=str(course_unit_id),
            )
            return Response(
                {"ok": False, "detail": "Course unit not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        enrollments = (
            StudentCourseUnitEnrollment.objects.filter(
                course_unit=cu,
                status="enrolled",
                registration_date__isnull=False,
            )
            .select_related("student", "student__admitted_program")
            .order_by("student__reg_no")
        )
        students = []
        for enr in enrollments:
            st = enr.student
            students.append(
                {
                    "reg_no": st.reg_no or "",
                    "student_id": st.student_id or "",
                    "full_name": st.full_name or "",
                    "programme": st.admitted_program.name if st.admitted_program_id else None,
                    "registration_kind": enr.registration_kind,
                    "registration_date": enr.registration_date.isoformat()
                    if enr.registration_date
                    else None,
                }
            )
        log_moodle_access(
            endpoint=endpoint,
            http_status=200,
            key_prefix=_key_prefix(request),
            detail=f"cu={course_unit_id};count={len(students)}",
        )
        return Response(
            {
                "ok": True,
                "course_unit_id": cu.pk,
                "course_code": cu.code,
                "students": students,
            }
        )
