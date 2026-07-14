import json
from .models import *
from .serializers import *
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, DjangoModelPermissions
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.views import APIView
from django.db.models import Count, Q, F, Prefetch
from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view
from datetime import datetime
from django.utils import timezone
from .utils.excel import create_workbook

import io
import zipfile
from weasyprint import HTML
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from django.http import HttpResponse
from django.template.loader import render_to_string

# email
from hr.hiring.tasks import (
    queue_application_received,
    queue_hired_emails,
    queue_interview_invitation,
    queue_interview_invitations,
    queue_interview_outcome,
)
from hr.hiring.utils.job_lifecycle import is_within_application_window, public_openings_queryset
from hr.hiring.erp_views import UpdateJobOpeningErpView

# =========================================Job Openings=================================================

# list job openings
class ListJobOpenings(generics.ListAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = JobOpening.objects.select_related('department')
    serializer_class = ListJobOpeningSerializer

    def get(self, request):
        user = request.user
        if not user.has_perm('hiring.view_jobopening'):
            return Response({"detail":"you dont have permissions to view job openings"}, status=400)
        
        job_openings = self.get_queryset()
        serializer = self.get_serializer(job_openings, many=True)
        return Response(serializer.data, status=200)

# list open vacancies (public careers — status + active date window)
class ListOpenJobs(generics.ListAPIView):
    serializer_class = ListJobOpeningSerializer

    def get_queryset(self):
        return public_openings_queryset()

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['request'] = self.request
        return ctx

# single open vacancy
class RetrieveOpenJob(generics.RetrieveAPIView):
    serializer_class = ListJobOpeningSerializer
    lookup_field = "id"
    lookup_url_kwarg = "job_id"

    def get_queryset(self):
        return public_openings_queryset()

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['request'] = self.request
        return ctx

# create job openings
class CreateJobOpenings(generics.CreateAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = JobOpening.objects.all()
    serializer_class = JobOpeningSerializer
    parser_classes = [MultiPartParser, FormParser]

# update job openings — always use ERP handler (PDF optional; keep existing file)
class UpdateJobOpenings(UpdateJobOpeningErpView):
    """Backward-compatible alias of UpdateJobOpeningErpView."""

    pass

# delete job openings
class DeleteJobOpenings(generics.DestroyAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = JobOpening.objects.all()
    serializer_class = JobOpeningSerializer
    parser_classes = [MultiPartParser, FormParser]

# single job opening
class SingleJobOpening(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = JobOpening.objects.select_related('department')
    serializer_class = ListJobOpeningSerializer
    lookup_field = "id"
    lookup_url_kwarg = "job_id"

# opening stats
class OpeningStats(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from hr.hiring.utils.job_lifecycle import today_local

        day = today_local()
        openings = JobOpening.objects.annotate(
            hired_count=Count(
                'applications',
                filter=Q(applications__status='HIRED')
            )
        )

        stats = openings.aggregate(
            total_positions=Count('id'),
            open_jobs=Count(
                'id',
                filter=Q(
                    status='OPEN',
                    published_date__lte=day,
                    application_deadline__gte=day,
                ),
            ),
            filled_positions=Count(
                'id',
                filter=Q(hired_count__gte=F('number_of_positions')) | Q(status='FILLED')
            )
        )

        return Response({
            "total_positions": stats['total_positions'],
            "open_jobs": stats['open_jobs'],
            "filled_positions": stats['filled_positions'],
        })
    
# ================================================Applications=================================================

# list all applications

class ListJobApplications(generics.ListAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = ListApplicationSerilaizer

    def get_queryset(self):
        CURRENT_APPLICATION_STATUSES = [
            'APPLIED',
            'SCREENING',
            'SHORTLISTED',
            'INTERVIEWING',
        ]
        return (
            JobApplication.objects
            .select_related('job_opening', 'job_opening__department')
            .filter(status__in=CURRENT_APPLICATION_STATUSES)
            .order_by('application_date')
        )

    def list(self, request, *args, **kwargs):
        if not request.user.has_perm('hiring.view_jobapplication'):
            return Response(
                {"detail": "You don't have permission to view job applications"},
                status=403
            )
        return super().list(request, *args, **kwargs)

# create job applications
@api_view(['POST'])
def create_job_application(request):
    try:
        with transaction.atomic():
            data = request.data.copy()
            files = request.FILES

            education_data = json.loads(data.get("education_history", "[]"))
            employment_data = json.loads(data.get("employment_history", "[]"))
            projects_data = json.loads(data.get("projects", "[]"))
            references_data = json.loads(data.get("references", "[]"))
            # certificates = files.getlist("certificates", [])
            certificates = json.loads(data.get("certificates", "[]"))

            # -----------------------------
            # Validate job opening FIRST
            # -----------------------------
            job_id = data.get("job_opening")
            if not job_id:
                return Response({"detail": "Job opening is required"}, status=400)

            job = JobOpening.objects.select_for_update().filter(
                id=job_id,
                status="OPEN"
            ).first()

            if not job:
                return Response({"detail": "Job opening is closed or invalid"}, status=400)

            if not is_within_application_window(job):
                return Response(
                    {"detail": "This vacancy is not currently accepting applications (outside open dates)."},
                    status=400,
                )

            application = JobApplication(
                job_opening=job,
                first_name=data.get("first_name") or "",
                last_name=data.get("last_name") or "",
                email=data.get("email") or "",
                phone=data.get("phone") or "",
                title=(data.get("title") or "Mr")[:20],
                current_address=(data.get("current_address") or "N/A")[:255],
                religious_affiliation=(data.get("religious_affiliation") or "N/A")[:100],
                marital_status=(data.get("marital_status") or "N/A")[:50],
                dob=data.get("dob") or "N/A",
                brief_description=(data.get("brief_description") or "N/A")[:2000],
                skills=(data.get("skills") or "N/A")[:2000],
                has_declared=str(data.get("has_declared", "")).lower() in ("true", "1", "yes"),
            )

            reference_bulk = []
            for r in references_data:
                phone_raw = str(r.get("phone") or "").strip()
                if not phone_raw:
                    raise KeyError("references.phone")
                reference_bulk.append(References(
                    application=application,
                    name=(r.get("name") or "")[:100],
                    phone=phone_raw[:30],
                    email=(r.get("email") or "")[:100],
                    job_position=(r.get("job_position") or "")[:100],
                ))

            certificate_bulk = []
            for c in certificates:
                certificate_bulk.append(Certificates_and_Training(
                    application=application,
                    certificate_name=(c.get("certificate_name") or "")[:200],
                    institution=(c.get("institution") or "")[:200],
                    date_obtained=c["date_obtained"],
                ))

            # normalize nested education/employment with field length guards
            education_bulk = []
            for e in education_data:
                education_bulk.append(EducationHistory(
                    application=application,
                    institution=(e.get("institution") or "")[:200],
                    award=(e.get("award") or "")[:200],
                    start_date=e["start_date"],
                    end_date=e["end_date"],
                ))

            employment_bulk = []
            for e in employment_data:
                employment_bulk.append(Employment(
                    application=application,
                    current_employer=(e.get("current_employer") or "")[:200],
                    start_date=e["start_date"],
                    end_date=e["end_date"],
                    current_position=(e.get("current_position") or "")[:200],
                    years_of_experience=int(e.get("years_of_experience") or 0),
                    duties=(e.get("duties") or "")[:1000],
                ))

            project_bulk = []
            for p in projects_data:
                project_bulk.append(Projects(
                    application=application,
                    name=(p.get("name") or "")[:100],
                    link=(p.get("link") or "")[:200],
                    description=(p.get("description") or "")[:500],
                ))

            application.save()

            EducationHistory.objects.bulk_create(education_bulk, batch_size=50)
            Employment.objects.bulk_create(employment_bulk, batch_size=50)
            Projects.objects.bulk_create(project_bulk, batch_size=50)
            References.objects.bulk_create(reference_bulk, batch_size=50)
            Certificates_and_Training.objects.bulk_create(certificate_bulk, batch_size=50)

            # -----------------------------
            # Post-commit actions
            # -----------------------------
            queue_application_received(application.id)

            return Response(
                {
                    "message": "Job application submitted successfully",
                    "application_id": application.id,
                    "reference": application.reference
                },
                status=201
            )

    except KeyError as e:
        return Response({"detail": f"Missing field: {str(e)}"}, status=400)
    except Exception as e:
        return Response({"detail": str(e)}, status=500)
    
# Track applications
@api_view(['POST'])
def track_application(request):
    reference = request.data.get('reference')
    email = request.data.get('email')

    if not reference or not email:
        return Response(
            {"detail": "Reference and email are required"},
            status=status.HTTP_400_BAD_REQUEST
        )

    application = JobApplication.objects.select_related(
        'job_opening__department'
    ).filter(
        reference=reference,
        email=email
    ).first()

    if not application:
        return Response(
            {"detail": "Application does not exist in our database"},
            status=status.HTTP_404_NOT_FOUND
        )

    return Response({
        "first_name": application.first_name,
        "last_name": application.last_name,
        "title": application.job_opening.title,
        "department": application.job_opening.department.name, 
        "reference": application.reference,
        "date_applied": application.application_date.strftime("%d %B %Y"),
        "application_status": application.status,
    }, status=status.HTTP_200_OK)

# single Application
class SingleApplication(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = JobApplication.objects.select_related('job_opening', 'job_opening__department')
    serializer_class = ApplicationDetailSerializer
    lookup_field = "id"
    lookup_url_kwarg = "app_id"

# list job positions
class ListJobPositions(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        active_application_statuses = [
            'APPLIED',
            'SCREENING',
            'SHORTLISTED',
            'INTERVIEWING',
        ]

        job_openings = (
            JobOpening.objects
            .filter(
                applications__status__in=active_application_statuses
            )
            .distinct()
        )

        return Response({
            "job_openings": JobPositionSerializer(job_openings, many=True).data
        })

# individual shortlisting
class Shortlist(APIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = JobApplication.objects.all()

    def patch(self, request, *args, **kwargs):
        application_id = self.kwargs['pk']

        with transaction.atomic():
            application = JobApplication.objects.filter(pk=application_id).first()
            if not application:
                return Response({"detail": "Application not found"}, status=404)
            if application.status not in ('APPLIED', 'SCREENING'):
                return Response(
                    {"detail": f"Cannot shortlist application in status {application.status}"},
                    status=400,
                )
            application.status = 'SHORTLISTED'
            application.save(update_fields=['status'])

        return Response({"detail": "Application shortlisted successfully"})

class BulkShortList(APIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = JobApplication.objects

    @transaction.atomic
    def post(self, request):
        number = request.data.get("number")
        application_ids = request.data.get("application_ids", [])

        # -------- Validation --------
        if not isinstance(application_ids, list) or not application_ids:
            return Response(
                {"detail": "application_ids must be a non-empty list"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            number = int(number)
        except (TypeError, ValueError):
            return Response(
                {"detail": "number must be a valid integer"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if number <= 0:
            return Response(
                {"detail": "number must be greater than zero"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # -------- Fetch scoped applications (APPLIED + SCREENING eligible) --------
        qs = JobApplication.objects.filter(
            id__in=application_ids,
            status__in=['APPLIED', 'SCREENING'],
        ).order_by('application_date')

        total_valid = qs.count()

        if total_valid == 0:
            return Response(
                {"detail": "No valid APPLIED/SCREENING applications found in your selection"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Cannot exceed selected candidates
        if number > total_valid:
            return Response(
                {
                    "detail": "Shortlist number exceeds available applications",
                    "available": total_valid
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # -------- Shortlist --------
        shortlisted_apps = list(qs[:number])
        for app in shortlisted_apps:
            app.status = 'SHORTLISTED'
        JobApplication.objects.bulk_update(shortlisted_apps, ['status'])

        # -------- Reserve remaining --------
        remaining_ids = list(qs[number:].values_list('id', flat=True))
        print('remaining ids', remaining_ids)
        reserved_count = JobApplication.objects.filter(id__in=remaining_ids).update(status='RESERVED')

        return Response(
            {
                "detail": "Bulk shortlisting completed",
                "shortlisted": len(shortlisted_apps),
                "reserved": reserved_count,
                "total_processed": total_valid
            },
            status=status.HTTP_200_OK
        )
    
# reserved candidates
class ListReservedApplications(generics.ListAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = ListApplicationSerilaizer

    def get_queryset(self):
        return (
            JobApplication.objects
            .select_related('job_opening', 'job_opening__department')
            .filter(status='RESERVED')
            .order_by('application_date')
        )

    def list(self, request, *args, **kwargs):
        if not request.user.has_perm('hiring.view_jobapplication'):
            return Response(
                {"detail": "You don't have permission to view job applications"},
                status=403
            )
        return super().list(request, *args, **kwargs)

# Pdf download
class DownloadJobApplicationPDF(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, application_id):
        application = get_object_or_404(JobApplication, id=application_id)

        # Preload related data
        education = EducationHistory.objects.filter(application=application)
        employment = Employment.objects.filter(application=application)
        projects = Projects.objects.filter(application=application)
        certificates = Certificates_and_Training.objects.filter(application=application)
        references = References.objects.filter(application=application)

        html_string = render_to_string(
            'resume_template.html',
            {
                'app': application,
                'education': education,
                'employment': employment,
                'projects': projects,
                'certificates': certificates,
                'references': references
            }
        )

        pdf_file = HTML(string=html_string).write_pdf()

        response = HttpResponse(pdf_file, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{application.first_name}_{application.last_name}_resume.pdf"'

        return response

# Bulk pdf download
class BulkJobApplicationPDFDownloadView(APIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = JobApplication.objects.all()

    def post(self, request):
        number = request.data.get('number')
        application_ids = request.data.get("application_ids", [])
        # Optional: "SHORTLISTED" (default for legacy “Shortlisted PDFs”) or omit to download any selected IDs
        status_filter = (request.data.get("status") or "").strip().upper() or None

        try:
            number = int(number)
        except (TypeError, ValueError):
            number = len(application_ids) if isinstance(application_ids, list) else 0

        if not isinstance(application_ids, list) or not application_ids:
            return Response({"detail": "application_ids must be a non-empty list"}, status=400)
        if number <= 0:
            return Response({"detail": "number must be greater than zero"}, status=400)

        qs = JobApplication.objects.filter(id__in=application_ids).select_related(
            "job_opening", "job_opening__department"
        ).order_by("application_date")
        if status_filter:
            qs = qs.filter(status=status_filter)

        applications = list(qs[:number])

        if not applications:
            return Response(
                {"detail": "No applications found for the given filter. Shortlist candidates first, or select shortlisted rows."},
                status=404,
            )

        # Create in-memory zip
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for application in applications:

                education = EducationHistory.objects.filter(application=application)
                employment = Employment.objects.filter(application=application)
                projects = Projects.objects.filter(application=application)
                certificates = Certificates_and_Training.objects.filter(application=application)
                references = References.objects.filter(application=application)
                # Render HTML template for this applicant
                html_string = render_to_string(
                    "resume_template.html",  # your template
                    {
                    'app': application,
                    'education': education,
                    'employment': employment,
                    'projects': projects,
                    'certificates': certificates,
                    'references': references
            }
                )
                pdf_file = HTML(string=html_string).write_pdf()

                # Create a file name: lastname_firstname_job.pdf
                filename = f"{slugify(application.last_name)}_{slugify(application.first_name)}_{slugify(application.job_opening.title)}.pdf"

                # Add PDF to zip
                zip_file.writestr(filename, pdf_file)

        zip_buffer.seek(0)

        # Prepare response
        response = HttpResponse(zip_buffer, content_type="application/zip")
        response["Content-Disposition"] = "attachment; filename=job_applications.zip"
        return response

# selected candidates
class InterviewPipelineView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not request.user.has_perm('hiring.view_interview'):
            return Response({"detail": "you dont have permissions to access interviews"}, status=403)

        data = {}

        openings = JobOpening.objects.prefetch_related(
            'applications__interviews'
        )

        for opening in openings:
            position = opening.title
            buckets = {
                "shortlisted": [],
                "personality": [],
                "written": [],
                "oral": [],
            }

            for app in opening.applications.all():
                base = {
                    "id": app.id,
                    "name": app.get_full_name(),
                    "email": app.email,
                    "phone": app.phone,
                    "reference": app.reference,
                    "appliedDate": app.application_date.date(),
                }

                if app.status == 'HIRED':
                    continue

                if app.status == 'SHORTLISTED':
                    buckets["shortlisted"].append(base)
                    continue

                if app.current_stage:
                    latest_interview = (
                        app.interviews
                        .filter(interview_type=app.current_stage)
                        .order_by('-interview_date')
                        .first()
                    )

                    entry = {
                        **base,
                        "status": latest_interview.status if latest_interview else "SCHEDULED",
                        "interview_id": latest_interview.id if latest_interview else None,
                        "testDate": latest_interview.interview_date.date() if latest_interview else None,
                        "time": latest_interview.interview_date.time() if latest_interview else None,
                        "location": latest_interview.location if latest_interview else "",
                        "meeting_link": latest_interview.meeting_link if latest_interview else "",
                    }

                    key = app.current_stage.lower()
                    if key in buckets:
                        buckets[key].append(entry)

            if any(buckets[s] for s in buckets):
                data[position] = buckets

        return Response(data)


# move to next stage
class MoveCandidatesToStage(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        stage = request.data.get("interview_type")
        date = request.data.get("interview_date")
        location = request.data.get("location", "")
        meeting_link = request.data.get("meeting_link", "")
        duration = request.data.get("duration_minutes") or 60
        feed_back = request.data.get("feedback", "")
        ids = request.data.get("application_ids", [])

        STAGES = [
            "SHORTLISTED", "PERSONALITY", "WRITTEN", "ORAL"
        ]

        if stage not in STAGES:
            return Response({"detail": "Invalid stage"}, status=400)

        try:
            interview_date = datetime.fromisoformat(date.replace("Z", "+00:00") if isinstance(date, str) else date)
            if timezone.is_naive(interview_date):
                interview_date = timezone.make_aware(interview_date)
        except (ValueError, TypeError, AttributeError) as e:
            return Response({"detail": f"Invalid date format: {str(e)}"}, status=400)

        applications = JobApplication.objects.filter(
            id__in=ids,
            status__in=['SHORTLISTED', 'INTERVIEWING']
        )

        created = 0
        invite_interview_ids = []
        send_emails = str(request.data.get("send_emails", "true")).lower() in ("1", "true", "yes")

        for app in applications:
            existing = (
                Interview.objects
                .filter(application=app, interview_type=stage)
                .order_by('-interview_date')
                .first()
            )
            if existing:
                existing.interview_date = interview_date
                existing.location = location or ""
                existing.meeting_link = meeting_link or ""
                existing.duration_minutes = int(duration) if duration else 60
                existing.feedback = feed_back or ""
                existing.status = "SCHEDULED"
                existing.save()
                obj = existing
                is_new = False
            else:
                obj = Interview.objects.create(
                    application=app,
                    interview_type=stage,
                    interview_date=interview_date,
                    location=location or "",
                    meeting_link=meeting_link or "",
                    duration_minutes=int(duration) if duration else 60,
                    feedback=feed_back or "",
                    status="SCHEDULED",
                )
                is_new = True

            invite_interview_ids.append(obj.id)

            if is_new:
                created += 1

            app.current_stage = stage
            app.status = 'INTERVIEWING'
            app.save(update_fields=['current_stage', 'status'])

        if send_emails and invite_interview_ids:
            queue_interview_invitations(invite_interview_ids)

        return Response({
            "moved": created,
            "scheduled": len(invite_interview_ids),
            "emails_queued": len(invite_interview_ids) if send_emails else 0,
            "stage": stage,
        })

# change interview status
class ChangeInterviewStatus(APIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = Interview.objects.all()

    @transaction.atomic
    def patch(self, request, interview_id):
        status_value = request.data.get("status")

        VALID_STATUSES = ["PASSED", "FAILED"]

        if status_value not in VALID_STATUSES:
            return Response(
                {"detail": "Status must be PASSED or FAILED"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            interview = Interview.objects.select_related("application").get(id=interview_id)
        except Interview.DoesNotExist:
            return Response(
                {"detail": "Interview not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        # Prevent changing already completed interviews
        if interview.status in ["PASSED", "FAILED"]:
            return Response(
                {"detail": "Interview already completed"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Update interview
        interview.status = status_value
        interview.save(update_fields=["status"])

        application = interview.application

        if status_value == "FAILED":
            application.status = "REJECTED"
            application.current_stage = None

        application.save(update_fields=["status", "current_stage"])

        send_emails = str(request.data.get("send_emails", "true")).lower() in ("1", "true", "yes")
        if send_emails and (application.email or "").strip():
            queue_interview_outcome(interview.id, status_value)

        return Response(
            {
                "detail": "Interview status updated successfully",
                "interview_status": interview.status,
                "email_queued": bool(send_emails and (application.email or "").strip()),
            },
            status=status.HTTP_200_OK
        )


class ResendInterviewInvitation(APIView):
    """Queue a fresh interview invitation email for one interview record."""

    permission_classes = [IsAuthenticated]

    def post(self, request, interview_id):
        if not (
            request.user.is_superuser
            or request.user.has_perm("hiring.change_interview")
            or request.user.has_perm("hiring.view_interview")
        ):
            return Response({"detail": "Permission denied."}, status=403)

        interview = Interview.objects.filter(pk=interview_id).select_related("application").first()
        if not interview:
            return Response({"detail": "Interview not found."}, status=404)
        if not (interview.application.email or "").strip():
            return Response({"detail": "Applicant has no email address."}, status=400)

        queue_interview_invitation(interview.id)
        return Response({"detail": "Interview invitation email queued.", "interview_id": interview.id})


# mark as hired
class MarkAsHired(APIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = JobApplication.objects.all()

    def patch(self, request, *args, **kwargs):
        with transaction.atomic():
            application_ids = request.data.get('ids') or []
            if not application_ids:
                return Response({"detail": "ids is required"}, status=400)

            applications = JobApplication.objects.filter(id__in=application_ids).prefetch_related('interviews')
            hired_ids: list[int] = []

            for app in applications:
                if app.status == 'HIRED':
                    return Response({"detail": "These candidates are already hired"}, status=400)

                # Hiring may occur after Written or Oral — not every role requires oral.
                interviews = list(app.interviews.all())
                written_ok = any(
                    i.interview_type == "WRITTEN" and i.status == "PASSED" for i in interviews
                )
                oral_ok = any(
                    i.interview_type == "ORAL" and i.status == "PASSED" for i in interviews
                )
                if not (written_ok or oral_ok):
                    return Response(
                        {
                            "detail": (
                                f"{app.get_full_name()} must pass the written or oral interview "
                                "before being hired."
                            )
                        },
                        status=400,
                    )

                app.status = 'HIRED'
                app.current_stage = None
                app.save(update_fields=["status", "current_stage"])
                hired_ids.append(app.id)

            send_emails = str(request.data.get("send_emails", "true")).lower() in ("1", "true", "yes")
            if send_emails and hired_ids:
                queue_hired_emails(hired_ids)

            return Response({
                "detail": "candidate hired successfully",
                "hired": len(hired_ids),
                "emails_queued": len(hired_ids) if send_emails else 0,
            })

# hired candidates
class HiredCandidates(generics.ListAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = JobApplication.objects.select_related('job_opening', 'job_opening__department').filter(status='HIRED', is_staff=False)
    serializer_class = HiredCandidatesSerializer

class HiredStats(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        applications = JobApplication.objects.select_related('job_opening').filter(
            status='HIRED'
        ).aggregate(
            hired=Count('id'),
            departments=Count('job_opening__department_id', distinct=True),
            position=Count('job_opening', distinct=True)
        )

        return Response({
            "hired_candidates":applications['hired'],
            "departments":applications['departments'],
            "positions":applications['position']
        }, status=200)
    
class handleHiredCandidateExport(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
         qs = (
             JobApplication.objects.select_related('job_opening').filter(status='HIRED')
         )

         headers = [
            "APPLICATION NO", "FIRST NAME","LAST NAME","EMAIL", "STATUS"
        ]

         rows = []

         for app in qs.iterator(chunk_size=1000):
              rows.append([
                   app.reference,
                   app.first_name,
                   app.last_name,
                   app.email,
                   app.status,
              ])

         wb = create_workbook(headers, rows, sheet_name="Hired Candidates")

         now = timezone.localtime(timezone.now())
         date_str = now.strftime("%Y-%m-%d")

         response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
         )
         response["Content-Disposition"] = (
            f'attachment; filename="hired_candidates_{date_str}.xlsx"'
        )
         wb.save(response)
         return response