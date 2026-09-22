"""Test / exam registration eligibility list + printable sheet."""
from admissions.faculty_scope import assert_course_unit_access
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from Programs.permissions import AcademicEnrollmentAdminPermission

VALID_KINDS = {"test", "exam"}


def _get_course_unit_or_404(course_unit_id):
    from .models import CourseUnit

    return CourseUnit.objects.select_related("program_batch__program", "semester").filter(
        id=course_unit_id
    ).first()


def _kind_from_request(request) -> str | None:
    kind = (request.query_params.get("kind") or "").strip().lower()
    return kind if kind in VALID_KINDS else None


def _eligible_rows_for_sheet(course_unit, kind: str) -> list[dict]:
    """Enrolled students eligible for kind, with % paid + eligibility basis, for the
    printable sheet (PDF/Excel). Used by both TestExamRegistrationPdfView and
    TestExamRegistrationExcelView."""
    from payments.registration_eligibility import build_registration_eligibility_payload
    from payments.test_exam_registration import student_has_temp_pass_bypass, test_exam_registration_block
    from .models import StudentCourseUnitEnrollment

    enrollments = (
        StudentCourseUnitEnrollment.objects.filter(course_unit=course_unit)
        .exclude(status="withdrawn")
        .select_related("student")
        .order_by("student__reg_no", "student__student_id")
    )

    rows = []
    for enrollment in enrollments:
        student = enrollment.student
        if test_exam_registration_block(student, kind):
            continue
        payload = build_registration_eligibility_payload(student)
        basis = "Temp pass" if student_has_temp_pass_bypass(student) else "Tuition paid"
        rows.append(
            {
                "reg_no": student.reg_no or student.student_id or "",
                "name": student.full_name,
                "percentage_paid": payload.get("percentage_paid", 0),
                "basis": basis,
            }
        )
    return rows


class TestExamEligibleStudentsView(APIView):
    """List enrolled students eligible (and blocked) to register for a test or exam."""

    permission_classes = [AcademicEnrollmentAdminPermission]

    def get(self, request, course_unit_id):
        from payments.registration_eligibility import build_registration_eligibility_payload
        from payments.test_exam_registration import KIND_THRESHOLDS, test_exam_registration_block
        from .models import StudentCourseUnitEnrollment

        course_unit = _get_course_unit_or_404(course_unit_id)
        if course_unit is None:
            return Response({"detail": "Course unit not found"}, status=status.HTTP_404_NOT_FOUND)
        assert_course_unit_access(request.user, course_unit)

        kind = _kind_from_request(request)
        if kind is None:
            return Response(
                {"detail": "Query param 'kind' must be 'test' or 'exam'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        enrollments = (
            StudentCourseUnitEnrollment.objects.filter(course_unit=course_unit)
            .exclude(status="withdrawn")
            .select_related("student")
            .order_by("student__reg_no", "student__student_id")
        )

        eligible, blocked = [], []
        for enrollment in enrollments:
            student = enrollment.student
            block = test_exam_registration_block(student, kind)
            pct = build_registration_eligibility_payload(student).get("percentage_paid", 0)
            row = {
                "student_id": student.student_id,
                "reg_no": student.reg_no,
                "name": student.full_name,
                "percentage_paid": pct,
            }
            if block:
                row["block_reason"] = block
                blocked.append(row)
            else:
                eligible.append(row)

        return Response(
            {
                "kind": kind,
                "minimum_required_pct": KIND_THRESHOLDS[kind],
                "eligible": eligible,
                "blocked": blocked,
                "eligible_count": len(eligible),
                "blocked_count": len(blocked),
            },
            status=status.HTTP_200_OK,
        )


class TestExamRegistrationPdfView(APIView):
    """Printable registration sheet listing eligible students, for signing."""

    permission_classes = [AcademicEnrollmentAdminPermission]

    def get(self, request, course_unit_id):
        from django.http import HttpResponse

        from payments.test_exam_registration import KIND_THRESHOLDS
        from .test_exam_registration_pdf import (
            build_test_exam_registration_context,
            render_test_exam_registration_pdf,
            safe_test_exam_pdf_filename,
        )

        course_unit = _get_course_unit_or_404(course_unit_id)
        if course_unit is None:
            return Response({"detail": "Course unit not found"}, status=status.HTTP_404_NOT_FOUND)
        assert_course_unit_access(request.user, course_unit)

        kind = _kind_from_request(request)
        if kind is None:
            return Response(
                {"detail": "Query param 'kind' must be 'test' or 'exam'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        program_batch = course_unit.program_batch
        program_name = program_batch.program.name if program_batch and program_batch.program_id else ""
        semester_name = course_unit.semester.name if course_unit.semester_id else ""
        rows = _eligible_rows_for_sheet(course_unit, kind)

        context = build_test_exam_registration_context(
            kind=kind,
            course_code=course_unit.code,
            course_name=course_unit.name,
            programme_name=program_name,
            semester_name=semester_name,
            min_pct=KIND_THRESHOLDS[kind],
            students=rows,
        )
        pdf_bytes = render_test_exam_registration_pdf(context)
        filename = safe_test_exam_pdf_filename(kind, course_unit.code)
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class TestExamRegistrationExcelView(APIView):
    """Same eligible-student registration sheet as the PDF, as an .xlsx download."""

    permission_classes = [AcademicEnrollmentAdminPermission]

    def get(self, request, course_unit_id):
        from django.http import HttpResponse

        from payments.test_exam_registration import KIND_THRESHOLDS
        from .test_exam_registration_excel import render_test_exam_registration_excel

        course_unit = _get_course_unit_or_404(course_unit_id)
        if course_unit is None:
            return Response({"detail": "Course unit not found"}, status=status.HTTP_404_NOT_FOUND)
        assert_course_unit_access(request.user, course_unit)

        kind = _kind_from_request(request)
        if kind is None:
            return Response(
                {"detail": "Query param 'kind' must be 'test' or 'exam'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        program_batch = course_unit.program_batch
        program_name = program_batch.program.name if program_batch and program_batch.program_id else ""
        semester_name = course_unit.semester.name if course_unit.semester_id else ""
        rows = _eligible_rows_for_sheet(course_unit, kind)

        xlsx_bytes, filename = render_test_exam_registration_excel(
            kind=kind,
            course_code=course_unit.code,
            course_name=course_unit.name,
            programme_name=program_name,
            semester_name=semester_name,
            min_pct=KIND_THRESHOLDS[kind],
            students=rows,
        )
        response = HttpResponse(
            xlsx_bytes,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
