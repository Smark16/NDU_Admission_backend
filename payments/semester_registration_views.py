"""
Semester tuition billing (student portal) + course registration + registration settings API.
"""
from django.utils.dateparse import parse_datetime

from Programs.permissions import FeePlanConfigurationPermission
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.models import AdmittedStudent
from Programs.models import ProgramBatch, Semester

from .models import RegistrationSettings


def _parse_optional_dt(val):
    if val is None or val == "":
        return None
    if hasattr(val, "year"):
        return val
    if isinstance(val, str):
        return parse_datetime(val)
    return val


def _parse_optional_bool(val):
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        normalized = val.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return bool(val)


class GetSemestersForProgramBatch(APIView):
    """List semesters for a Programs.ProgramBatch (academic cohort)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, program_batch_id):
        try:
            program_batch = ProgramBatch.objects.get(id=program_batch_id)
            semesters = Semester.objects.filter(program_batch=program_batch).order_by("order", "start_date", "id")
            data = [
                {
                    "id": sem.id,
                    "name": sem.name,
                    "order": sem.order,
                    "start_date": sem.start_date.isoformat(),
                    "end_date": sem.end_date.isoformat() if sem.end_date else None,
                    "is_active": sem.is_active,
                }
                for sem in semesters
            ]
            return Response(data)
        except ProgramBatch.DoesNotExist:
            return Response({"error": "Program batch not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class GetStudentTuitionStructure(APIView):
    """Tuition lines from FeePlanRule for the logged-in admitted student."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .student_portal_finance import get_admitted_student_for_user, tuition_structure_dict

        student = get_admitted_student_for_user(request.user)
        if not student:
            return Response(
                {"detail": "Admitted student profile not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(tuition_structure_dict(student))

    def post(self, request):
        return self.get(request)


class GetStudentPaymentStatus(APIView):
    """Payment totals and StudentTuitionPayment history."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .student_portal_finance import get_admitted_student_for_user, payment_status_dict

        student = get_admitted_student_for_user(request.user)
        if not student:
            return Response(
                {"detail": "Admitted student profile not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(payment_status_dict(student, request))

    def post(self, request):
        return self.get(request)


class CheckRegistrationEligibility(APIView):
    """Tuition % + registration window + admission gates."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .registration_eligibility import build_registration_eligibility_payload
        from .student_portal_finance import get_admitted_student_for_user

        student = get_admitted_student_for_user(request.user)
        if not student:
            exists = AdmittedStudent.objects.filter(application__applicant=request.user).exists()
            if not exists:
                return Response(
                    {"detail": "Admitted student profile not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            pct = float(RegistrationSettings.get_settings().min_tuition_payment_percentage)
            return Response(
                {
                    "is_eligible": False,
                    "percentage_paid": 0.0,
                    "minimum_required": pct,
                    "total_required": 0.0,
                    "total_paid": 0.0,
                    "balance": 0.0,
                    "display_currency": "UGX",
                    "message": "You must be fully admitted before you can register.",
                },
                status=status.HTTP_200_OK,
            )
        return Response(build_registration_eligibility_payload(student))

    def post(self, request):
        return self.get(request)


class RegisterForCourses(APIView):
    """Register for course units (must pass eligibility)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        from .course_registration_actions import register_student_for_course_units
        from .registration_eligibility import build_registration_eligibility_payload
        from .student_portal_finance import get_admitted_student_for_user

        student = get_admitted_student_for_user(request.user)
        if not student:
            return Response(
                {"detail": "Admitted student profile not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        payload = build_registration_eligibility_payload(student)
        if not payload.get("is_eligible"):
            return Response(
                {
                    "detail": payload.get("message") or "Not eligible to register.",
                    "eligibility": payload,
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        course_unit_ids = request.data.get("course_unit_ids") or []
        if not course_unit_ids:
            return Response({"detail": "No course unit IDs provided"}, status=status.HTTP_400_BAD_REQUEST)
        result = register_student_for_course_units(student, course_unit_ids)
        if not result["registered"] and result["errors"]:
            return Response(
                {
                    "message": "Could not complete registration",
                    "registered": result["registered"],
                    "errors": result["errors"],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {
                "message": f"Successfully registered for {len(result['registered'])} course(s)",
                "registered": result["registered"],
                "errors": result["errors"],
            },
            status=status.HTTP_201_CREATED,
        )


class GetRegistrationSettings(APIView):
    """Singleton registration policy (admin + read-only for students)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            s = RegistrationSettings.get_settings()
            return Response(
                {
                    "min_tuition_payment_percentage": float(s.min_tuition_payment_percentage),
                    "registration_start_date": s.registration_start_date,
                    "registration_end_date": s.registration_end_date,
                    "require_admission_approval": s.require_admission_approval,
                    "require_enrollment": s.require_enrollment,
                    "require_programme_enrollment": s.require_programme_enrollment,
                    "auto_enroll_on_admission": getattr(s, "auto_enroll_on_admission", False),
                    "skip_tuition_check": s.skip_tuition_check,
                    "is_active": s.is_active,
                }
            )
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class UpdateRegistrationSettings(APIView):
    """Update registration policy (typically staff)."""

    permission_classes = [FeePlanConfigurationPermission]

    def post(self, request):
        try:
            s = RegistrationSettings.get_settings()

            if "min_tuition_payment_percentage" in request.data:
                s.min_tuition_payment_percentage = request.data["min_tuition_payment_percentage"]
            if "registration_start_date" in request.data:
                s.registration_start_date = _parse_optional_dt(request.data["registration_start_date"])
            if "registration_end_date" in request.data:
                s.registration_end_date = _parse_optional_dt(request.data["registration_end_date"])
            if "require_admission_approval" in request.data:
                s.require_admission_approval = _parse_optional_bool(request.data["require_admission_approval"])
            if "require_enrollment" in request.data:
                s.require_enrollment = _parse_optional_bool(request.data["require_enrollment"])
            if "require_programme_enrollment" in request.data:
                s.require_programme_enrollment = _parse_optional_bool(request.data["require_programme_enrollment"])
            if "auto_enroll_on_admission" in request.data:
                s.auto_enroll_on_admission = _parse_optional_bool(request.data["auto_enroll_on_admission"])
            if "skip_tuition_check" in request.data:
                s.skip_tuition_check = _parse_optional_bool(request.data["skip_tuition_check"])
            if "is_active" in request.data:
                s.is_active = _parse_optional_bool(request.data["is_active"])

            s.updated_by = request.user
            s.save()

            return Response(
                {
                    "message": "Settings updated successfully",
                    "min_tuition_payment_percentage": float(s.min_tuition_payment_percentage),
                    "registration_start_date": s.registration_start_date,
                    "registration_end_date": s.registration_end_date,
                    "require_admission_approval": s.require_admission_approval,
                    "require_enrollment": s.require_enrollment,
                    "require_programme_enrollment": s.require_programme_enrollment,
                    "auto_enroll_on_admission": getattr(s, "auto_enroll_on_admission", False),
                    "skip_tuition_check": s.skip_tuition_check,
                    "is_active": s.is_active,
                }
            )
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
