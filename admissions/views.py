from accounts.models import Campus
from .models import *
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import *
from rest_framework.response import Response
from .serializers import *
from rest_framework.parsers import MultiPartParser, FormParser
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from django.conf import settings
from django.db import transaction
# from .utils.validate_photo import validate_passport_photo
from .tasks import celery_rejection_email, celery_send_application_email, celery_application_notification, celery_admission_email, celery_admission_update, celery_bulk_announcement
from accounts.tasks import celery_send_account_email
from payments.models import ApplicationPayment
from Drafts.models import DraftApplication
from django.db.models import Q, Sum

import logging
import json
import os

try:
    from weasyprint import HTML
except OSError:
    HTML = None
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.template.loader import render_to_string
from datetime import date
from urllib.parse import quote

# caching
from django.core.cache import cache

logger = logging.getLogger(__name__)

# ===========================applications ===========================================
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_applications(request):
    MAX_FILE_SIZE = settings.FILE_UPLOAD_MAX_MEMORY_SIZE

    # === File size validation ===
    for file_obj in request.FILES.getlist('documents', []):
        if file_obj.size > MAX_FILE_SIZE:
            return Response(
                {"detail": f"Each document must be ≤ 50 MB. '{file_obj.name}' is too large ({file_obj.size / (1024*1024):.1f} MB)."},
                status=400
            )

    if 'passport_photo' in request.FILES:
        photo = request.FILES['passport_photo']
        if photo.size > MAX_FILE_SIZE:   # Note: You may want a smaller limit for photos (e.g. 10MB)
            return Response(
                {"detail": f"Passport photo must be ≤ 10 MB. '{photo.name}' is too large ({photo.size / (1024*1024):.1f} MB)."},
                status=400
            )

    # === Validate serializer ===
    serializer = CudApplicationSerializer(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    programs_data = serializer.validated_data.pop('programs', None)

    # === Parse & Validate O-Level and A-Level ONCE ===
    olevel_validated = []
    if request.data.get('has_olevel'):
        try:
            results = json.loads(request.data.get("olevel_results", "[]"))
            _seen = set()
            for item in results:
                sid = int(item["subject"])
                if sid in _seen:
                    return Response({"detail": "Duplicate O-Level subject"}, status=400)
                _seen.add(sid)
                subject = OLevelSubject.objects.get(id=sid)
                olevel_validated.append({"subject": subject, "grade": item["grade"].upper()})
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            return Response({"detail": "Invalid O-Level results format"}, status=400)
        except OLevelSubject.DoesNotExist:
            return Response({"detail": "Invalid O-Level subject ID"}, status=400)

    alevel_validated = []
    if request.data.get('has_alevel'):
        try:
            results = json.loads(request.data.get("alevel_results", "[]"))
            _seen = set()
            for item in results:
                sid = int(item["subject"])
                if sid in _seen:
                    return Response({"detail": "Duplicate A-Level subject"}, status=400)
                _seen.add(sid)
                subject = ALevelSubject.objects.get(id=sid)
                alevel_validated.append({"subject": subject, "grade": item["grade"].upper()})
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            return Response({"detail": "Invalid A-Level results format"}, status=400)
        except ALevelSubject.DoesNotExist:
            return Response({"detail": "Invalid A-Level subject ID"}, status=400)

    # === Additional qualifications ===
    additional_qualifications = []
    try:
        additional_qual_str = request.data.get("additional_qualifications", "[]")
        if additional_qual_str:
            additional_qualifications = json.loads(additional_qual_str)
    except (json.JSONDecodeError, TypeError):
        additional_qualifications = []

    with transaction.atomic():
        try:
            files = request.FILES
            ext_ref = request.data.get("external_reference")
            payment = None

            # === Idempotency check for payment ===
            if ext_ref:
                try:
                    payment = ApplicationPayment.objects.select_for_update().get(
                        external_reference=ext_ref,
                        user=request.user,
                        status="PAID",
                    )
                except ApplicationPayment.DoesNotExist:
                    return Response({"detail": "Invalid or unpaid payment reference"}, status=400)

                if payment.application_id is not None:
                    logger.info(
                        "Idempotent submit replay accepted for user=%s ext_ref=%s app_id=%s",
                        request.user.id, ext_ref, payment.application_id
                    )
                    return Response({
                        "detail": "Application already submitted successfully.",
                        "application_id": payment.application_id,
                        "idempotent_replay": True
                    }, status=status.HTTP_200_OK)

            # === Create Application object ===
            application = Application(**serializer.validated_data)
            application.applicant = request.user
            application.status = "submitted"

            if payment:
                application.application_fee_paid = True
                application.application_fee_amount = payment.amount
                application.application_reference = payment.external_reference

            if passport_photo := files.get("passport_photo"):
                application.passport_photo = passport_photo

            # Save the main application first (so it gets an ID)
            application.save()

            # Link payment to application
            if payment:
                payment.application = application
                payment.save(update_fields=["application"])

            # === Programs (Many-to-Many) ===
            if programs_data:
                application.programs.set(programs_data)

            # === Bulk create O-Level results ===
            if olevel_validated:
                OLevelResult.objects.bulk_create([
                    OLevelResult(
                        application=application,
                        subject=d["subject"],
                        grade=d["grade"]
                    ) for d in olevel_validated
                ], batch_size=50)

            # === Bulk create A-Level results ===
            if alevel_validated:
                ALevelResult.objects.bulk_create([
                    ALevelResult(
                        application=application,
                        subject=d["subject"],
                        grade=d["grade"]
                    ) for d in alevel_validated
                ], batch_size=50)

            # === Documents ===
            doc_files = files.getlist("documents")
            doc_types = request.data.getlist("document_types", [])
            document_objs = []
            for i, file in enumerate(doc_files):
                doc_type = doc_types[i] if i < len(doc_types) else "Others"
                document_objs.append(ApplicationDocument(
                    application=application,
                    file=file,
                    name=file.name.split('.')[0][:50],
                    document_type=doc_type,
                ))

            if document_objs:
                ApplicationDocument.objects.bulk_create(document_objs, batch_size=50)

            # === Additional Qualifications ===
            if additional_qualifications:
                qual_bulk = []
                for qual in additional_qualifications:
                    if qual.get('institution'):
                        qual_bulk.append(AdditionalQualifications(
                            application=application,
                            additional_qualification_institution=qual.get('institution', ''),
                            additional_qualification_type=qual.get('type', ''),
                            additional_qualification_year=qual.get('year', ''),
                            class_of_award=qual.get('class_of_award', '')
                        ))
                if qual_bulk:
                    AdditionalQualifications.objects.bulk_create(qual_bulk, batch_size=20)

            # === Queue background tasks after successful commit ===
            def _queue_submission_tasks():
                try:
                    celery_send_application_email.delay(application.id)
                    celery_application_notification.delay(
                        request.user.id,
                        "Application Submitted",
                        "Your application was successfully submitted"
                    )
                except Exception as task_error:
                    logger.exception(
                        "Application %s saved but post-submit tasks failed: %s",
                        application.id,
                        task_error
                    )

            transaction.on_commit(_queue_submission_tasks)

            return Response({
                "detail": "Application submitted successfully!",
                "application_id": application.id,
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error("Application creation failed: %s", str(e), exc_info=True)
            return Response({"detail": "An error occurred while processing your application."}, status=500)

# Direct Application Entry
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_direct_applications(request):
    MAX_FILE_SIZE = settings.FILE_UPLOAD_MAX_MEMORY_SIZE
    
    for file_obj in request.FILES.getlist('documents', []):
        if file_obj.size > MAX_FILE_SIZE:
            return Response(
                {"detail": f"Each document must be ≤ 50 MB. '{file_obj.name}' is too large ({file_obj.size / (1024*1024):.1f} MB)."},
                    status=400
                ) 
                      
    if 'passport_photo' in request.FILES:
            photo = request.FILES['passport_photo']
            if photo.size > MAX_FILE_SIZE:
                return Response(
                    {"detail": f"Passport photo must be ≤ 10 MB. '{photo.name}' is too large ({photo.size / (1024*1024):.1f} MB)."},
                        status=400
                )          
            
    with transaction.atomic():
        try:
            data = request.data.copy()
            files = request.FILES

            # additional qualifications
            additional_qualifications = []
            try:
                additional_qual_str = request.data.get("additional_qualifications", "[]")
                if additional_qual_str:
                    additional_qualifications = json.loads(additional_qual_str)
            except (json.JSONDecodeError, TypeError):
                additional_qualifications = []

            # Extract everything
            doc_files = files.getlist("documents")
            doc_types = request.data.getlist("document_types", [])
            passport_photo = files.get("passport_photo")
            olevel_results = json.loads(request.data.get("olevel_results", "[]"))
            alevel_results = json.loads(request.data.get("alevel_results", "[]"))

            # Validate main application data
            serializer = CudApplicationSerializer(data=data, context={"request": request})
            serializer.is_valid(raise_exception=True)

            # Validate school_pay_reference rule
            fee_paid = serializer.validated_data.get('application_fee_paid', False)
            school_pay_ref = (serializer.validated_data.get('school_pay_reference') or '').strip()
            if fee_paid and not school_pay_ref:
                return Response(
                    {"detail": "school_pay_reference is required when application_fee_paid is true."},
                    status=400
                )

            # remove M-2-M data and prevent client from injecting entered_by
            programs_data = serializer.validated_data.pop('programs', None)
            serializer.validated_data.pop('entered_by', None)

            # create applicant user (reuse existing account if email already registered)
            account_password = 'applicant@12345'
            is_new_account = False
            try:
                email = data.get('email', '').strip()
                existing = User.objects.filter(email=email).first()
                if existing:
                    applicant = user = existing
                else:
                    # ensure unique username if email is already taken as username
                    base_username = email
                    username = base_username
                    counter = 1
                    while User.objects.filter(username=username).exists():
                        username = f"{base_username}_{counter}"
                        counter += 1
                    applicant = user = User.objects.create(
                        email=email,
                        first_name=data.get('first_name', ''),
                        last_name=data.get('last_name', ''),
                        phone=data.get('phone', ''),
                        username=username,
                        is_applicant=True,
                        password=account_password,
                    )
                    is_new_account = True
            except Exception as e:
                return Response({"detail": f"Failed to create user: {str(e)}"}, status=400)

            application = Application(**serializer.validated_data)
            application.applicant = applicant
            application.status = "submitted"
            application.entered_by = request.user
            application.application_fee_paid = True
            application.is_direct_entry = True
        
            if passport_photo:
                # validate_passport_photo(passport_photo)
                application.passport_photo = passport_photo

            # Validate & prepare all child objects

            # === O-LEVEL ===
            if request.data.get('has_olevel'):
                olevel_results = json.loads(request.data.get("olevel_results", "[]"))
                olevel_bulk = []
                seen = set()

                for item in olevel_results:
                    try:
                        sid = int(item["subject"])          # ← Convert to integer
                    except (ValueError, TypeError, KeyError):
                        return Response({"detail": f"Invalid O-Level subject ID: {item.get('subject')}"}, status=400)

                    if sid in seen:
                        return Response({"detail": "Duplicate O-Level subject"}, status=400)
                    seen.add(sid)

                    # Get subject by ID
                    try:
                        subject = OLevelSubject.objects.get(id=sid)
                    except OLevelSubject.DoesNotExist:
                        return Response({"detail": f"Invalid O-Level subject ID: {sid}"}, status=400)

                    olevel_bulk.append(
                        OLevelResult(
                            application=application, 
                            subject=subject, 
                            grade=item["grade"].upper()
                        )
                    )

            # === A-LEVEL ===
            if request.data.get('has_alevel'):
                alevel_results = json.loads(request.data.get("alevel_results", "[]"))
                alevel_bulk = []
                seen = set()

                for item in alevel_results:
                    try:
                        sid = int(item["subject"])          # ← Convert to integer
                    except (ValueError, TypeError, KeyError):
                        return Response({"detail": f"Invalid A-Level subject ID: {item.get('subject')}"}, status=400)

                    if sid in seen:
                        return Response({"detail": "Duplicate A-Level subject"}, status=400)
                    seen.add(sid)

                    try:
                        subject = ALevelSubject.objects.get(id=sid)
                    except ALevelSubject.DoesNotExist:
                        return Response({"detail": f"Invalid A-Level subject ID: {sid}"}, status=400)

                    alevel_bulk.append(
                        ALevelResult(
                            application=application, 
                            subject=subject, 
                            grade=item["grade"].upper()
                        )
                    )

            # === Documents ===
            document_objs = []
            for i, file in enumerate(doc_files):
                doc_type = doc_types[i] if i < len(doc_types) else "Others"
                document_objs.append(ApplicationDocument(
                    application=application,
                    file=file,
                    name=file.name.split('.')[0][:50],
                    document_type=doc_type,
                ))

            # NOW SAVE EVERYTHING
            application.save() 

            # save M-2-M field
            if programs_data:
               application.programs.set(programs_data) 

            OLevelResult.objects.bulk_create(olevel_bulk, batch_size=50)
            ALevelResult.objects.bulk_create(alevel_bulk, batch_size=50)
            ApplicationDocument.objects.bulk_create(document_objs, batch_size=50)

            # === NEW: Save Multiple Additional Qualifications ===
            if additional_qualifications:
                qual_bulk = []
                for qual in additional_qualifications:
                    if qual.get('institution'):  # Only save if institution is provided
                        qual_bulk.append(AdditionalQualifications(
                            application=application,
                            additional_qualification_institution=qual.get('institution', ''),
                            additional_qualification_type=qual.get('type', ''),
                            additional_qualification_year=qual.get('year', ''),
                            class_of_award=qual.get('class_of_award', '')
                        ))
                if qual_bulk:
                    AdditionalQualifications.objects.bulk_create(qual_bulk, batch_size=20)

            # Send welcome email only for newly created accounts
            if is_new_account:
                celery_send_account_email.delay(applicant.id, account_password)

            return Response({
                "message": "Application submitted successfully!",
                "application_id": application.id,
            }, status=status.HTTP_201_CREATED)

        except ValueError as e:
            return Response({"detail": str(e)}, status=400)
        except Exception as e:
            return Response({"detail": str(e)}, status=500)
        
# list applications
class ListApplications(generics.ListAPIView):
    queryset = Application.objects.filter(~Q(status__in=['draft','Admitted', 'rejected', 'accepted'])).order_by('created_at')
    serializer_class = ListApplicationsSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

# All applications report (no status filter — returns everything)
class AllApplicationsReport(generics.ListAPIView):
    serializer_class = AllApplicationsReportSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def get_queryset(self):
        return Application.objects.select_related(
            'academic_level', 'batch', 'campus', 'entered_by'
        ).prefetch_related('programs', 'programs__faculty').order_by('-created_at')

# Direct entry applicants
class ListDirectEntryApplications(generics.ListAPIView):
    queryset = Application.objects.filter(is_direct_entry=True).order_by('-created_at')
    serializer_class = ListApplicationsSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

# rejected Students
class ListRejectedStudents(generics.ListAPIView):
    queryset = Application.objects.filter(status__in=['rejected']).order_by('-created_at')
    serializer_class = ListApplicationsSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

# delete application
class DeleteApplication(generics.RetrieveDestroyAPIView):
    queryset = Application.objects.all()
    serializer_class = CudApplicationSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    
    def delete(self, request,*args, **kwargs):
        instance = self.get_object()
        instance.delete()

        return Response({"detail":"Application delete successfully"})

# get single application
class SingleApplication(generics.RetrieveAPIView):
    queryset = Application.objects.all()
    serializer_class = SingleApplicationSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def get(self, request, application_id):
        try:
            application = Application.objects.prefetch_related('programs', 'programs__campuses').select_related(
                'applicant', 'batch', 'campus', 'academic_level', 'reviewed_by').get(pk=application_id)

            serializer = SingleApplicationSerializer(application)
            return Response(serializer.data, status=200)
        except Application.DoesNotExist:
            return Response({"detail":"Application not found"})
        
# change application status
class ChangeApplicationStatus(APIView):
    queryset = Application.objects.all()
    serializer_class = ApplicationSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def patch(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                app_id = self.kwargs['pk']
                newStatus = request.data.get('status')

                try:
                    application = Application.objects.prefetch_related('programs').select_related(
                      'applicant', 'batch', 'campus', 'academic_level', 'reviewed_by').get(pk=app_id)
                    application.status = newStatus
                    application.save()

                    return Response({"detail":"status changed successfully"})
                except Application.DoesNotExist:
                    return Response({"detail":"student Application does not exist"})
                    
        except Exception as e:
            return Response({"detail":str(e)})

    
# ================================subjects================================================

# create O subjects
class CreateOlevelSubjects(generics.CreateAPIView):
    queryset = OLevelSubject.objects.all()
    serializer_class = OlevelSubjectSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

class ListOlevelSubjects(generics.ListAPIView):
    queryset = OLevelSubject.objects.all()
    serializer_class = OlevelSubjectSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def get(self, request, *args, **kwargs):
        cache_key = 'all_olevel_subjects_list'

        # Try cache first
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return Response(cached_data)

        # Get fresh data
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        data = serializer.data

        # Cache for 24 hours (86,400 seconds)
        cache.set(cache_key, data, timeout=60 * 60 * 24)

        return Response(data)

class EditOlevelSubjecgts(generics.UpdateAPIView):
    queryset = OLevelSubject.objects.all()
    serializer_class = OlevelSubjectSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def put(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.serializer_class(instance, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data, status=200)
    
class DeleteOlevelSubjects(generics.RetrieveDestroyAPIView):
    queryset = OLevelSubject.objects.all()
    serializer_class = OlevelSubjectSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()

        return Response({"detail":"subject deleted successfully"})

# =============================================A level subjects===============================================================
class CreateAlevelSubjects(generics.CreateAPIView):
    queryset = ALevelSubject.objects.all()
    serializer_class = AlevelSubjectSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]


class ListAlevelSubjects(generics.ListAPIView):
    queryset = ALevelSubject.objects.all()
    serializer_class = AlevelSubjectSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def get(self, request, *args, **kwargs):
        cache_key = 'all_alevel_subjects_list'

        # Try cache first
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return Response(cached_data)

        # Get fresh data
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        data = serializer.data

        # Cache for 24 hours (86,400 seconds)
        cache.set(cache_key, data, timeout=60 * 60 * 24)

        return Response(data)

class EditAlevelSubjecgts(generics.UpdateAPIView):
    queryset = ALevelSubject.objects.all()
    serializer_class = AlevelSubjectSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def put(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.serializer_class(instance, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data, status=200)
    
class DeleteAlevelSubjects(generics.RetrieveDestroyAPIView):
    queryset = ALevelSubject.objects.all()
    serializer_class = AlevelSubjectSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()

        return Response({"detail":"subject deleted successfully"})
        
# ========================================================Batch=================================================

#create batch
class CreateBatch(generics.CreateAPIView):
    queryset = Batch.objects.all()
    serializer_class = BatchSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
        
# list batch
class ListBatch(generics.ListAPIView):
    queryset = Batch.objects.prefetch_related('programs', 'programs__campuses').select_related('created_by').order_by('-created_at')
    serializer_class = BatchSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

# edit batch
class EditBatch(generics.ListAPIView):
    queryset = Batch.objects.all()
    serializer_class = BatchSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def put(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.serializer_class(instance, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data, status=200)
    
# delete batch
class DeleteBatch(generics.RetrieveDestroyAPIView):
    queryset = Batch.objects.all()
    serializer_class = BatchSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()

        return Response({"detail":"batch deleted successfully"})
    
# get active batch
class GetActiveApplicationBatch(generics.ListAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = Batch.objects.all()
    serializer_class = BatchSerializer

    def get(self, request):
        now = timezone.now().date()

        # Get current version (fallback to 0 if missing)
        version = cache.get('active_batch_version', 0)

        cache_key = f'active_batch_{version}'

        # Try cache first
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached, status=status.HTTP_200_OK)

        try:
            # Optimized query
            batch = (
                Batch.objects
                .select_related('created_by')
                .prefetch_related('programs', 'programs__campuses')
                .get(
                    application_start_date__lte=now,
                    application_end_date__gte=now,
                    is_active=True
                )
            )

            serializer = self.get_serializer(batch)
            data = serializer.data

            # Cache for 24 hours
            cache.set(cache_key, data, timeout=60 * 60 * 24)

            return Response(data, status=status.HTTP_200_OK)

        except Batch.DoesNotExist:
            return Response({
                "detail": "No active application batch found",
                "is_active": False
            }, status=status.HTTP_404_NOT_FOUND)

        except Exception as e:
            return Response({
                "detail": str(e),
                "is_active": False
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# active admission batch
class GetActiveAdmissionBatch(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = Batch.objects.all()
    serializer_class = BatchSerializer

    def get(self, request):
        now = timezone.now().date()

        try:
            # Optimized query
            batch = (
                Batch.objects
                .select_related('created_by')
                .prefetch_related('programs', 'programs__campuses')
                .filter(is_active=True)
                .filter(
                    Q(application_start_date__lte=now, application_end_date__gte=now) |
                    Q(admission_start_date__lte=now, admission_end_date__gte=now)
                ).first() 
            )

            if not batch:
                return Response({
                    "detail": "No active admission batch found",
                    "is_active": False
                }, status=status.HTTP_404_NOT_FOUND)

            serializer = self.get_serializer(batch)
            data = serializer.data

            return Response(data, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                "detail": str(e),
                "is_active": False
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

#get intake options
class IntakeOptions(APIView):
    def get(self, request):
        intakes = Batch.objects.values_list('name', 'academic_year').order_by('-created_at')

        data = [
            f"{name} ({year})"
            for name, year in intakes
        ]

        return Response(data)
  
# =========================================================Applicant Dashboard===============================
class ApplicantDashboard(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        # Get the most recent application
        application = Application.objects.filter(applicant=user).order_by('-created_at').first()

        if not application:
            return Response(
                {"detail": "You have not submitted any application yet."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Base data from application
        base_data = {
            "id":application.id,
            "batch": application.batch.name if application.batch else None,
            "campus": application.campus.name,
            "applied_date": application.created_at,
            "application_status": application.status,
            "admission_letter_pdf": application.admission_letter_pdf.url if application.admission_letter_pdf else None
        }

        # Try to get admission record
        admission = AdmittedStudent.objects.filter(application=application).order_by('-created_at').first()

        if not admission:
            return Response({
                **base_data,
                "program": "In Progress",
                "student_id": "No student number",
                "has_admission": False,
            })

        # If admission exists
        return Response({
            **base_data,
            "program": admission.admitted_program.name,
            "campus": admission.admitted_campus.name,  
            "student_id": admission.student_id,
            "has_admission": True,
            "is_admitted": admission.is_admitted,  
        })
    
# =========================================Application details=====================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def application_detail(request, application_id):
    # 1. Get application safely
    application = get_object_or_404(Application, pk=application_id, applicant=request.user)

    # 2. Get related data
    olevel_results = OLevelResult.objects.filter(application=application).select_related('subject')
    alevel_results = ALevelResult.objects.filter(application=application).select_related('subject')
    documents = ApplicationDocument.objects.filter(application=application)

    qualifications = AdditionalQualifications.objects.filter(application=application).select_related('application')

    # 3. Serialize everything
    data = {
        'application': ApplicationSerializer(application).data,
        'olevel_results': OlevelResultSerializer(olevel_results, many=True).data,
        'alevel_results': AlevelResultSerializer(alevel_results, many=True).data,
        'documents':  DocumentSerializer(documents, many=True).data,
        "qualifications":AdditionalQualifficationsSerializer(qualifications, many=True).data
    }

    return Response(data, status=status.HTTP_200_OK)

# review application
class ReviewApplication(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, application_id):

        Application.objects.filter(
            pk=application_id,
            status__in=['pending', 'submitted', 'in_progress']  
        ).update(
            status='under_review',
            reviewed_by=request.user,
            reviewed_at=timezone.now()
        )

        # Fetch optimized object AFTER update
        application = Application.objects.select_related(
            'applicant', 'batch', 'campus', 'academic_level', 'reviewed_by'
        ).prefetch_related('programs').get(pk=application_id)

        # Related queries
        olevel_results = OLevelResult.objects.filter(application=application).select_related('subject')
        alevel_results = ALevelResult.objects.filter(application=application).select_related('subject')
        documents = ApplicationDocument.objects.filter(application=application).select_related('application')
        qualifications = AdditionalQualifications.objects.filter(application=application).select_related('application')

        data = {
            'application': ApplicationDetailSerializer(application).data,
            'olevel_results': ListOlevelResultSerializer(olevel_results, many=True).data,
            'alevel_results': ListAlevelResultSerializer(alevel_results, many=True).data,
            'documents': DocumentSerializer(documents, many=True).data,
            "qualifications":AdditionalQualifficationsSerializer(qualifications, many=True).data
        }

        return Response(data)

# change programme
class ChangeProgramme(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, application_id):
        from accounts.models import Campus as CampusModel
        application = get_object_or_404(Application, pk=application_id)
        program_ids = request.data.get('program_ids', [])
        campus_id = request.data.get('campus_id')
        note = request.data.get('note', '').strip()

        if not program_ids:
            return Response({'detail': 'At least one programme is required.'}, status=400)

        programs = Program.objects.filter(id__in=program_ids)
        if programs.count() != len(program_ids):
            return Response({'detail': 'One or more programme IDs are invalid.'}, status=400)

        if campus_id:
            campus = get_object_or_404(CampusModel, pk=campus_id)
            application.campus = campus

        application.programs.set(programs)
        application.save()

        return Response({
            'detail': f'Programme and campus updated successfully.{" Note: " + note if note else ""}',
            'programs': [{'id': p.id, 'name': p.name} for p in programs],
            'campus': application.campus.name,
        })

# edit application personal details
class EditApplicationProfile(APIView):
    permission_classes = [IsAuthenticated]

    EDITABLE_FIELDS = [
        'first_name', 'last_name', 'middle_name', 'date_of_birth', 'gender',
        'nationality', 'phone', 'email', 'address', 'disabled',
        'next_of_kin_name', 'next_of_kin_contact', 'next_of_kin_relationship',
        'nin', 'passport_number',
    ]

    def patch(self, request, application_id):
        application = get_object_or_404(Application, pk=application_id)

        if application.status == 'Admitted':
            return Response({'detail': 'Cannot edit profile of an already admitted student.'}, status=400)

        updates = {k: v for k, v in request.data.items() if k in self.EDITABLE_FIELDS}
        if not updates:
            return Response({'detail': 'No valid fields provided.'}, status=400)

        for field, value in updates.items():
            setattr(application, field, value)
        application.save(update_fields=list(updates.keys()))

        return Response({'detail': 'Profile updated successfully.'})

# ==================================================Academic Levels==========================================

# create level
class CreateAcademicLevels(generics.CreateAPIView):
    queryset = AcademicLevel.objects.all()
    serializer_class = AcademicLevelSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

# ListAdminAcademiclevels
class ListAdminAcademicLevels(generics.ListAPIView):
    queryset = AcademicLevel.objects.all()
    serializer_class = AcademicLevelSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    
# list level
class ListAcademicLevel(generics.ListAPIView):
    queryset = AcademicLevel.objects.filter(is_active=True)
    serializer_class = AcademicLevelSerializer
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        cache_key = 'active_academic_levels_list'

        # Try cache first
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return Response(cached_data)

        # Get fresh data
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        data = serializer.data

        # Cache for 24 hours (86,400 seconds)
        cache.set(cache_key, data, timeout=60 * 60 * 24)

        return Response(data)

# edit level
class UpdateAcademicLevel(generics.UpdateAPIView):
    queryset = AcademicLevel.objects.all()
    serializer_class = AcademicLevelSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def put(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.serializer_class(instance, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data, status=200)
    
# delete level
class DeleteAcademicLevel(generics.RetrieveDestroyAPIView):
    queryset = AcademicLevel.objects.all()
    serializer_class = AcademicLevelSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()

        return Response({"detail":"academic Level deleted successfully"})

# ============================================faculties============================
class ListFaculties(generics.ListCreateAPIView):
    queryset = Faculty.objects.prefetch_related('campuses')
    serializer_class = FacultySerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

class CreateFaculty(generics.CreateAPIView):
    queryset = Faculty.objects.all()
    serializer_class = FacultySerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

class UpdateFaculty(generics.UpdateAPIView):
    queryset = Faculty.objects.all()
    serializer_class = FacultySerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.serializer_class(instance, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data, status=200)
    
class DeleteFaculty(generics.RetrieveDestroyAPIView):
    queryset = Faculty.objects.all()
    serializer_class = FacultySerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()

        return Response({"detail":"faculty deleted successfully"})

# change status
class ChangeFacultyStatus(APIView):
    queryset = Faculty.objects.all()
    serializer_class = FacultySerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def patch(self, request, *args, **kwargs):
        faculty_id = self.kwargs['pk']
        newStatus = request.data.get('is_active')
        try:
            faculty = Faculty.objects.prefetch_related('campuses').get(pk=faculty_id)
            faculty.is_active = newStatus
            faculty.save()

            serializer = self.serializer_class(faculty)
            return Response(serializer.data, status=200)
        except Exception as e:
            return Response({"detail":str(e)}, status=400)
        
# ===========================================================Admissions=======================================================

# create admission
class AdmitStudent(generics.CreateAPIView):
    queryset = AdmittedStudent.objects.all()
    serializer_class = AdmittedStudentSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def create(self, request, *args, **kwargs):
        try:
            with transaction.atomic():

                # Validate and save admission
                serializer = self.get_serializer(data=request.data)
                serializer.is_valid(raise_exception=True)
                admission = serializer.save()

                # Fetch related application
                try:
                    application = Application.objects.select_related(
                        "applicant", "batch", "campus"
                    ).get(pk=admission.application_id)
                except Application.DoesNotExist:
                    return Response({"detail": "Student application doesn't exist"}, status=400)

                # Update status
                Application.objects.filter(id=application.id).update(status="accepted", admitted_by=request.user)

                celery_admission_email.delay(application.id, admission.id)
                celery_application_notification.delay(request.user.id,"Admission Successful","Congratulations! You have been admitted to Ndejje University")
               
                # ======================================================================

                return Response(self.serializer_class(admission).data, status=201)

        except Exception as e:
            return Response({"detail": str(e)}, status=400)

class RejectStudent(APIView):
    queryset = Application.objects.all()
    serializer_class = ApplicationSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def update(self, request, application_id):
        rejection_reason = request.data.get('rejection_reason', 'No reason provided')
        try:
            with transaction.atomic():
                application = Application.objects.select_related('applicant').get(pk=application_id)
                application.status = 'rejected'
                application.save()

                celery_rejection_email.delay(application.id, rejection_reason)
                celery_application_notification.delay(request.user.id,"Application Rejected","We regret to inform you that your application has been rejected")

                return Response({"detail": "Application rejected successfully"}, status=200)

        except Application.DoesNotExist:
            return Response({"detail": "Application not found"}, status=404)
        except Exception as e:
            return Response({"detail": str(e)}, status=400)
 
# list Admitted students
class ListAdmittedStudents(generics.ListAPIView):
    queryset = AdmittedStudent.objects.select_related(
        'admitted_program__faculty',
        'admitted_batch',
        'admitted_campus',
        'admitted_by',
        'application__applicant'
    ).all()

    serializer_class = AdmittedStudentListSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

# update admitted students
class UpdateAdmittedStudent(generics.UpdateAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = AdmittedStudent.objects.all()
    serializer_class = AdmittedStudentSerializer

    @transaction.atomic
    def perform_update(self, serializer):
        admission_data = serializer.save()
        try:
            celery_admission_update.delay(admission_data.id)
        except Exception as e:
            print("Celery error:", e)

# candidate admission
class CandidateAdmission(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = AdmittedStudent.objects.select_related(
        'admitted_program',
        'admitted_batch',
        'admitted_campus',
        'admitted_by',
    ).prefetch_related('admitted_program__campuses')
    serializer_class = AdmissionDetailSerializer
    lookup_field = "id"
    lookup_url_kwarg = "admission_id"


# delete admitted student
class DeleteAdmittedStudent(generics.DestroyAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = AdmittedStudent.objects.all()
    serializer_class = AdmittedStudentSerializer

# Admin dashboard stats
class AdminDashboardStats(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        total_applications = Application.objects.count()
        online_applications = Application.objects.filter(is_direct_entry=False).count()
        direct_applications = Application.objects.filter(is_direct_entry=True).count()
        pending_applications = Application.objects.filter(status='submitted').count()
        admitted_students = AdmittedStudent.objects.filter(is_registered=True).count()
        rejected_students = Application.objects.filter(status='rejected').count()
        total_batches = Batch.objects.count()
        active_batches = Batch.objects.filter(is_active=True).count()

        # Income from online SchoolPay payments only — direct entry excluded
        online_fee_income = ApplicationPayment.objects.filter(
            status="PAID",
            application__isnull=False,
            application__is_direct_entry=False,
        ).aggregate(total=Sum("amount"))["total"] or 0

        return Response({
            "totalApplication": total_applications,
            "onlineApplications": online_applications,
            "directApplications": direct_applications,
            "pendingApplications": pending_applications,
            "admittedStudents": admitted_students,
            "rejectedStudents": rejected_students,
            "total_batches": total_batches,
            "activeBatches": active_batches,
            "onlineFeeIncome": float(online_fee_income),
        }, status=200)

# ===================================================notifications======================================
# list user notifications
class ListNotifications(generics.ListAPIView):
    queryset = PortalNotification.objects.select_related('recipient')
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = NotificationSerializer

    def get(self, request):
        user_notifications = PortalNotification.objects.select_related('recipient').filter(recipient=request.user)
        serializer = self.serializer_class(user_notifications, many=True)

        return Response(serializer.data, status=200)

#========================================pdf download=================================================
class DownloadAdmissionPDF(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, application_id):
        import base64 as b64_mod
        import os as _os

        # Get the application – make sure it belongs to the logged-in user or admin
        application = get_object_or_404(
            Application,
            id=application_id,
            # applicant=request.user  # ← uncomment if only applicant can download own letter
        )

        # Fetch related data
        olevel_results = OLevelResult.objects.filter(application=application).select_related('subject', 'application')
        alevel_results = ALevelResult.objects.filter(application=application).select_related('subject', 'application')
        qualifications = AdditionalQualifications.objects.filter(application=application).select_related('application')

        # ── Base64-encode the university logo ─────────────────────────────────
        # Resolve relative to this file so it works regardless of CWD
        _here = _os.path.dirname(_os.path.abspath(__file__))           
        logo_b64 = ""
        for _ext in ('ndejje_logo.jpg', 'ndejje_logo.png'):
            _logo_path = _os.path.join(settings.BASE_DIR, "static", "ndejje_logo.jpg")
            if _os.path.exists(_logo_path):
                with open(_logo_path, 'rb') as _f:
                    _mime = 'jpeg' if _ext.endswith('.jpg') else 'png'
                    logo_b64 = f"data:image/{_mime};base64,{b64_mod.b64encode(_f.read()).decode()}"
                break

        # ── Base64-encode the applicant's passport photo ──────────────────────
        photo_b64 = ""
        if application.passport_photo:
            try:
                _photo_path = application.passport_photo.path
                if _os.path.exists(_photo_path):
                    with open(_photo_path, 'rb') as _f:
                        _raw = _f.read()
                    _photo_ext = _os.path.splitext(_photo_path)[1].lower().lstrip('.')
                    _photo_mime = {'jpg': 'jpeg', 'jpeg': 'jpeg', 'png': 'png'}.get(_photo_ext, 'jpeg')
                    photo_b64 = f"data:image/{_photo_mime};base64,{b64_mod.b64encode(_raw).decode()}"
            except Exception:
                pass 
        # Current date for the letter
        today = date.today()

        # Render template
        html_string = render_to_string(
            'student_profile.html',
            {
                'application': application,
                'olevel_results': olevel_results,
                'alevel_results': alevel_results,
                'additional_qualifications': qualifications,
                'today': today,
                'logo_b64': logo_b64,
                'photo_b64': photo_b64,
            },
            request=request
        )

        # Generate PDF with xhtml2pdf (pure Python, works on Windows)
        import io
        from xhtml2pdf import pisa

        pdf_buffer = io.BytesIO()
        result = pisa.CreatePDF(html_string, dest=pdf_buffer)

        if result.err:
            return Response(
                {"detail": "PDF generation failed. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        pdf_buffer.seek(0)
        safe_name = application.full_name.replace(" ", "_")
        ref = application.application_reference or "N-A"

        # Response as downloadable PDF
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = (
            f'attachment; filename="Applicant_Profile_{safe_name}_{ref}.pdf"'
        )
        response.write(pdf_buffer.read())

        return response


# ── Bulk Announcement ──────────────────────────────────────────────────────────
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def send_bulk_announcement(request):
    subject = (request.data.get('subject') or '').strip()
    body = (request.data.get('body') or '').strip()
    message_type = request.data.get('message_type', 'email')  # email | sms | both
    status_filter = request.data.get('status', 'all')
    batch_filter = request.data.get('batch', 'all')
    level_filter = request.data.get('academic_level', 'all')

    if not subject or not body:
        return Response({"detail": "Subject and body are required."}, status=400)

    if message_type in ('sms', 'both'):
        return Response({"detail": "SMS is not yet configured. Please use Email only for now."}, status=400)

    explicit_ids = request.data.get('application_ids', None)
    if explicit_ids:
        ids = [int(i) for i in explicit_ids if str(i).isdigit()]
    else:
        qs = Application.objects.all()
        if status_filter != 'all':
            qs = qs.filter(status=status_filter)
        if batch_filter != 'all':
            qs = qs.filter(batch__name=batch_filter)
        if level_filter != 'all':
            qs = qs.filter(academic_level__name=level_filter)
        ids = list(qs.values_list('id', flat=True))

    if not ids:
        return Response({"detail": "No applicants match the selected filters."}, status=400)

    celery_bulk_announcement.delay(ids, subject, body)
    return Response({"detail": f"Announcement queued for {len(ids)} applicant(s).", "count": len(ids)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def test_announcement(request):
    subject = (request.data.get('subject') or '').strip()
    body = (request.data.get('body') or '').strip()
    test_email = (request.data.get('test_email') or '').strip()

    if not subject or not body:
        return Response({"detail": "Subject and body are required."}, status=400)
    if not test_email or '@' not in test_email:
        return Response({"detail": "A valid test email address is required."}, status=400)

    from ndu_portal.send_grid import send_configurable_email
    personalised = body.replace("{first_name}", "Test").replace("{last_name}", "User")
    sent = send_configurable_email(test_email, f"[TEST] {subject}", personalised)

    if sent:
        return Response({"detail": f"Test email sent to {test_email}."})
    return Response({"detail": "Failed to send test email. Check your SendGrid configuration."}, status=500)

