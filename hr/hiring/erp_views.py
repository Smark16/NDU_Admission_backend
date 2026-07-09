from datetime import date

from django.core.files.base import ContentFile
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Campus
from hr.staff.models import StaffProfile
from hr.staff.serializers import AllStaffSerializer
from hr.staff.utils.create_user import create_user_for_staff

from .models import JobApplication, JobOpening
from .serializers import ListJobOpeningSerializer


class CreateJobOpeningErpView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not request.user.has_perm("hiring.add_jobopening"):
            return Response({"detail": "Permission denied."}, status=403)

        required = ["title", "department", "employment_type", "application_deadline", "published_date"]
        missing = [f for f in required if not request.data.get(f)]
        if missing:
            return Response({"detail": f"Missing fields: {', '.join(missing)}"}, status=400)

        description_file = request.FILES.get("description")
        if not description_file:
            text = request.data.get("description_text") or "Job description to be uploaded."
            description_file = ContentFile(text.encode("utf-8"), name="job_description.txt")

        try:
            opening = JobOpening.objects.create(
                title=request.data["title"],
                department_id=int(request.data["department"]),
                employment_type=request.data.get("employment_type", "FULL_TIME"),
                number_of_positions=int(request.data.get("number_of_positions", 1)),
                application_deadline=request.data["application_deadline"],
                published_date=request.data.get("published_date") or date.today(),
                status=request.data.get("status", "OPEN"),
                description=description_file,
            )
        except Exception as exc:
            return Response({"detail": str(exc)}, status=400)

        return Response(ListJobOpeningSerializer(opening).data, status=201)


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

        password = (request.data.get("initial_password") or "").strip()
        if not password:
            return Response({"detail": "Initial password is required."}, status=400)

        campus_ids = request.data.get("campus") or request.data.get("campuses") or []
        if isinstance(campus_ids, (int, str)):
            campus_ids = [int(campus_ids)]
        campuses = list(Campus.objects.filter(pk__in=campus_ids))
        if not campuses:
            default = Campus.objects.first()
            if default:
                campuses = [default]

        job_title = (application.job_opening.title or "")[:20]
        staff = StaffProfile.objects.create(
            first_name=application.first_name,
            last_name=application.last_name,
            university_email=application.email,
            job_title=job_title or None,
            org_unit=application.job_opening.department,
            application=application,
            system_login=True,
        )
        if campuses:
            staff.campus.set(campuses)

        create_user_for_staff(staff, initial_password=password)
        application.is_staff = True
        application.save(update_fields=["is_staff"])

        return Response(AllStaffSerializer(staff).data, status=201)
