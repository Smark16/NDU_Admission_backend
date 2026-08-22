"""Moodle-facing APIs (service API key auth)."""
from __future__ import annotations

from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from Programs.models import CourseUnit, Semester
from Programs.shared_teaching import (
    moodle_shared_fields_for_course_unit,
    registered_enrollments_for_course_unit,
)

from .permissions import HasMoodleApiKey
from .services import (
    academic_batch_payload,
    finance_status_for_student,
    log_moodle_access,
    moodle_course_unit_payload,
    registered_courses_for_student,
    resolve_student_by_lookup,
    shared_course_units_registry,
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
                "finance_status": finance_status_for_student(student),
            }
        )


class MoodleStudentProfileView(APIView):
    """
    Moodle service: fetch student display fields by reg_no (no password).

    Use after SSO launch when psig/profile params are not yet handled in sso.php,
    or to refresh name/email on each login.
    """

    authentication_classes = []
    permission_classes = [HasMoodleApiKey]

    def get(self, request, reg_no: str):
        endpoint = "moodle/students/profile"
        student = resolve_student_by_lookup(reg_no)
        if not student:
            log_moodle_access(
                endpoint=endpoint,
                http_status=404,
                key_prefix=_key_prefix(request),
                detail=reg_no,
            )
            return Response(
                {"ok": False, "detail": "Student not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        user = student.student_user if student.student_user_id else None
        log_moodle_access(
            endpoint=endpoint,
            http_status=200,
            key_prefix=_key_prefix(request),
            detail=student.reg_no or "",
        )
        return Response({"ok": True, "student": student_profile_payload(student, user)})


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


class MoodleRegisteredCoursesView(APIView):
    """Courses this student registered in Steward — use this for Moodle enrolment, not the catalogue."""

    authentication_classes = []
    permission_classes = [HasMoodleApiKey]

    def get(self, request, reg_no: str):
        endpoint = "moodle/registered-courses"
        student = resolve_student_by_lookup(reg_no)
        if not student:
            log_moodle_access(
                endpoint=endpoint,
                http_status=404,
                key_prefix=_key_prefix(request),
                detail=reg_no,
            )
            return Response(
                {"ok": False, "detail": "Student not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        courses = registered_courses_for_student(student)
        log_moodle_access(
            endpoint=endpoint,
            http_status=200,
            key_prefix=_key_prefix(request),
            detail=f"{student.reg_no}:count={len(courses)}",
        )
        payload = {
            "ok": True,
            "reg_no": student.reg_no or "",
            "student_id": student.student_id or "",
            "programme": student.admitted_program.name if student.admitted_program_id else None,
            "courses": courses,
        }
        payload.update(academic_batch_payload(student))
        return Response(payload)


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
            .select_related(
                "semester",
                "program_batch",
                "program_batch__program",
                "program_batch__program__faculty",
                "shared_teaching_offering",
                "shared_teaching_offering__catalog_unit",
                "shared_teaching_offering__parent_course_unit",
            )
            .prefetch_related(
                "lecturers",
                "section_lecturers__lecturer",
                "shared_teaching_offering__lecturers",
            )
            .order_by("code", "id")
        )
        parent_ids: dict[int, str] = {}
        rows = [moodle_course_unit_payload(cu, parent_ids=parent_ids) for cu in units]
        log_moodle_access(
            endpoint=endpoint,
            http_status=200,
            key_prefix=_key_prefix(request),
            detail=f"semester={sid};count={len(rows)}",
        )
        return Response({"ok": True, "semester_id": sid, "course_units": rows})


class MoodleSharedCourseUnitsView(APIView):
    """Registry of shared teaching offerings for Moodle validation and admin UI."""

    authentication_classes = []
    permission_classes = [HasMoodleApiKey]

    def get(self, request):
        endpoint = "moodle/shared-course-units"
        semester_raw = request.query_params.get("semester_id")
        academic_year = (request.query_params.get("academic_year") or "").strip() or None
        term_raw = request.query_params.get("term_number")

        semester_id = None
        if semester_raw not in (None, ""):
            try:
                semester_id = int(semester_raw)
            except (TypeError, ValueError):
                return Response(
                    {"ok": False, "detail": "semester_id must be an integer."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        term_number = None
        if term_raw not in (None, ""):
            try:
                term_number = int(term_raw)
            except (TypeError, ValueError):
                return Response(
                    {"ok": False, "detail": "term_number must be an integer."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if semester_id is None and not academic_year:
            return Response(
                {
                    "ok": False,
                    "detail": "Provide semester_id and/or academic_year query parameter.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        shared_units = shared_course_units_registry(
            semester_id=semester_id,
            academic_year=academic_year,
            term_number=term_number,
        )
        log_moodle_access(
            endpoint=endpoint,
            http_status=200,
            key_prefix=_key_prefix(request),
            detail=f"count={len(shared_units)}",
        )
        return Response({"ok": True, "shared_units": shared_units})


class MoodleEnrolledStudentsView(APIView):
    authentication_classes = []
    permission_classes = [HasMoodleApiKey]

    def get(self, request, course_unit_id: int):
        endpoint = "moodle/enrolled-students"
        cu = (
            CourseUnit.objects.filter(pk=course_unit_id, is_active=True)
            .select_related("shared_teaching_offering")
            .first()
        )
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

        merge_shared = str(request.query_params.get("merge_shared", "false")).lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        enrollments = registered_enrollments_for_course_unit(
            cu,
            merge_shared=merge_shared,
        ).select_related(
            "student",
            "student__admitted_program",
            "student__intended_program_batch",
            "student__programme_enrollment",
            "student__programme_enrollment__program_batch",
            "course_unit",
            "course_unit__semester",
            "course_unit__program_batch",
            "course_unit__program_batch__program",
            "course_unit__shared_teaching_offering",
            "course_unit__shared_teaching_offering__catalog_unit",
            "course_unit__shared_teaching_offering__parent_course_unit",
        )
        shared_meta = moodle_shared_fields_for_course_unit(cu)
        students = []
        for enr in enrollments:
            st = enr.student
            enr_meta = moodle_shared_fields_for_course_unit(enr.course_unit)
            row = {
                "reg_no": st.reg_no or "",
                "student_id": st.student_id or "",
                "full_name": st.full_name or "",
                "programme": st.admitted_program.name if st.admitted_program_id else None,
                "course_unit_id": enr.course_unit_id,
                "offering_id": str(enr.course_unit_id),
                "registration_kind": enr.registration_kind,
                "registration_date": enr.registration_date.isoformat()
                if enr.registration_date
                else None,
            }
            row.update(academic_batch_payload(st))
            if enr_meta.get("is_shared"):
                row["is_shared"] = True
                row["shared_unit_key"] = enr_meta.get("shared_unit_key")
                row["offering_label"] = enr_meta.get("offering_label")
                row["parent_idnumber"] = enr_meta.get("parent_idnumber")
                row["group_idnumber"] = enr_meta.get("group_idnumber")
            students.append(row)
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
                **shared_meta,
                "students": students,
            }
        )
