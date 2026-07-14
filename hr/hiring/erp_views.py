from datetime import date, datetime

from django.shortcuts import get_object_or_404
from django.db import transaction
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Campus
from hr.staff.models import StaffProfile
from hr.staff.serializers import AllStaffSerializer
from hr.staff.tasks import queue_staff_login_provision

from .models import JobApplication, JobOpening
from .serializers import ListJobOpeningSerializer
from .utils.job_lifecycle import suggested_status_for_dates, validate_job_description_pdf


def _parse_date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()[:10]
    return date.fromisoformat(text)


class CreateJobOpeningErpView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        if not request.user.has_perm("hiring.add_jobopening"):
            return Response({"detail": "Permission denied."}, status=403)

        required = ["title", "department", "employment_type", "application_deadline", "published_date"]
        missing = [f for f in required if not request.data.get(f)]
        if missing:
            return Response({"detail": f"Missing fields: {', '.join(missing)}"}, status=400)

        description_file = request.FILES.get("description")
        try:
            validate_job_description_pdf(description_file)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)

        try:
            published_date = _parse_date(request.data.get("published_date")) or date.today()
            application_deadline = _parse_date(request.data.get("application_deadline"))
            if not application_deadline:
                return Response({"detail": "Application deadline is required."}, status=400)
            if application_deadline < published_date:
                return Response(
                    {"detail": "Application deadline must be on or after the opens-on date."},
                    status=400,
                )

            requested_status = (request.data.get("status") or "").strip().upper()
            # MANUAL overrides only for cancelled/filled; otherwise schedule-driven.
            if requested_status in ("CANCELLED", "FILLED"):
                status = requested_status
            else:
                status = suggested_status_for_dates(published_date, application_deadline)

            opening = JobOpening.objects.create(
                title=request.data["title"],
                department_id=int(request.data["department"]),
                employment_type=request.data.get("employment_type", "FULL_TIME"),
                number_of_positions=int(request.data.get("number_of_positions", 1)),
                application_deadline=application_deadline,
                published_date=published_date,
                status=status,
                description=description_file,
            )
        except Exception as exc:
            return Response({"detail": str(exc)}, status=400)

        return Response(ListJobOpeningSerializer(opening, context={"request": request}).data, status=201)


class UpdateJobOpeningErpView(APIView):
    """Multipart-friendly update for ERP UI (PDF description optional on edit)."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    http_method_names = ["put", "patch", "options", "head"]

    def put(self, request, *args, **kwargs):
        return self._update(request, *args, **kwargs)

    def patch(self, request, *args, **kwargs):
        return self._update(request, *args, **kwargs)

    def _update(self, request, *args, **kwargs):
        if not request.user.has_perm("hiring.change_jobopening"):
            return Response({"detail": "Permission denied."}, status=403)

        opening_id = kwargs.get("pk") or kwargs.get("job_id")
        if opening_id is None and args:
            opening_id = args[0]
        opening = get_object_or_404(JobOpening, pk=opening_id)
        data = request.data

        if "title" in data and data.get("title"):
            opening.title = data["title"]
        if data.get("department"):
            opening.department_id = int(data["department"])
        if data.get("employment_type"):
            opening.employment_type = data["employment_type"]
        if data.get("number_of_positions") not in (None, ""):
            opening.number_of_positions = int(data["number_of_positions"])
        if data.get("application_deadline"):
            opening.application_deadline = _parse_date(data["application_deadline"])
        if data.get("published_date"):
            opening.published_date = _parse_date(data["published_date"])

        description_file = request.FILES.get("description")
        if description_file:
            try:
                validate_job_description_pdf(description_file)
            except ValueError as exc:
                return Response({"detail": str(exc)}, status=400)
            opening.description = description_file

        if opening.application_deadline and opening.published_date:
            if opening.application_deadline < opening.published_date:
                return Response(
                    {"detail": "Application deadline must be on or after the opens-on date."},
                    status=400,
                )

        requested_status = (data.get("status") or "").strip().upper()
        if requested_status in ("CANCELLED", "FILLED", "CLOSED"):
            opening.status = requested_status
        else:
            opening.status = suggested_status_for_dates(
                opening.published_date,
                opening.application_deadline,
            )

        try:
            opening.save()
        except Exception as exc:
            return Response({"detail": str(exc)}, status=400)

        return Response(ListJobOpeningSerializer(opening, context={"request": request}).data)


class OnboardHiredCandidateView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, application_id):
        if not request.user.has_perm("staff.add_staffprofile"):
            return Response({"detail": "Permission denied."}, status=403)

        application = get_object_or_404(
            JobApplication.objects.select_related("job_opening", "job_opening__department"),
            pk=application_id,
            status="HIRED",
        )
        if application.is_staff:
            return Response({"detail": "This candidate is already onboarded to staff."}, status=400)

        # Prefer the full staff-form flow. This endpoint remains as a thin fallback.
        campus_ids = request.data.get("campus") or request.data.get("campuses") or []
        if isinstance(campus_ids, (int, str)):
            campus_ids = [int(campus_ids)]
        campuses = list(Campus.objects.filter(pk__in=campus_ids))
        if not campuses:
            default = Campus.objects.first()
            if default:
                campuses = [default]

        job_title = (application.job_opening.title or "")[:20]
        uni_email = (request.data.get("university_email") or application.email or "").strip().lower()
        staff = StaffProfile.objects.create(
            first_name=application.first_name,
            last_name=application.last_name,
            university_email=uni_email or None,
            personal_email=application.email,
            job_title=job_title or None,
            org_unit=application.job_opening.department,
            application=application,
            system_login=True,
        )
        if campuses:
            staff.campus.set(campuses)

        application.is_staff = True
        application.save(update_fields=["is_staff"])

        queue_staff_login_provision(staff.id)

        return Response(AllStaffSerializer(staff).data, status=201)
