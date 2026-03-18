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
from audit.utils import log_audit_event
from .utils.notification import create_notification
from django.core.mail import send_mail
from django.conf import settings
from django.db import transaction
import threading
# from .utils.validate_photo import validate_passport_photo
from .utils.email import send_admission_update
from payments.models import ApplicationPayment
from django.db.models import Q

import logging
import json

from weasyprint import HTML
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.template.loader import render_to_string
from datetime import date

# caching
from django.core.cache import cache

logger = logging.getLogger(__name__)

# ===========================applications ===========================================
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_applications(request):
    MAX_FILE_SIZE = settings.FILE_UPLOAD_MAX_MEMORY_SIZE
    
    for file_obj in request.FILES.getlist('documents', []):
        if file_obj.size > MAX_FILE_SIZE:
            return Response(
                {"detail": f"Each document must be ≤ 10 MB. '{file_obj.name}' is too large ({file_obj.size / (1024*1024):.1f} MB)."},
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

            # ext_ref = request.data.get("external_reference")

            # if not ext_ref:
            #     return Response(
            #         {"detail": "Payment reference is required"},
            #         status=400
            #     )

            # try:
            #     payment = ApplicationPayment.objects.select_for_update().get(
            #         external_reference=ext_ref,
            #         user=request.user,
            #         status="PAID",
            #         application__isnull=True 
            #     )
            # except ApplicationPayment.DoesNotExist:
            #     return Response(
            #         {"detail": "Invalid, unpaid, or already used payment reference"},
            #         status=400
            #     )


            # Extract everything
            doc_files = files.getlist("documents")
            doc_types = request.data.getlist("document_types", [])
            passport_photo = files.get("passport_photo")
            olevel_results = json.loads(request.data.get("olevel_results", "[]"))
            alevel_results = json.loads(request.data.get("alevel_results", "[]"))

            # Validate main application data
            serializer = CudApplicationSerializer(data=data, context={"request": request})
            serializer.is_valid(raise_exception=True)

            # remove M-2-M data
            programs_data = serializer.validated_data.pop('programs', None)

            application = Application(**serializer.validated_data)
            application.applicant = request.user
            application.status = "submitted"
            # application.application_fee_paid = True
            # application.application_fee_amount = payment.amount
            # application.application_reference = payment.external_reference

            if passport_photo:
                # validate_passport_photo(passport_photo)
                application.passport_photo = passport_photo

            # Validate & prepare all child objects

            # === O-Level ===
            olevel_subjects = {s.id: s for s in OLevelSubject.objects.filter(id__in=[o["subject"] for o in olevel_results])}
            olevel_bulk = []
            seen = set()
            for item in olevel_results:
                sid = item["subject"]
                if sid in seen:
                    return Response({"detail": "Duplicate O-Level subject"}, status=400)
                seen.add(sid)
                subject = olevel_subjects.get(sid)
                if not subject:
                    return Response({f"Invalid O-Level subject: {sid}"}, status=400)
                olevel_bulk.append(OLevelResult(application=application, subject=subject, grade=item["grade"].upper()))

            # === A-Level ===
            alevel_subjects = {s.id: s for s in ALevelSubject.objects.filter(id__in=[a["subject"] for a in alevel_results])}
            alevel_bulk = []
            seen = set()
            for item in alevel_results:
                sid = item["subject"]
                if sid in seen:
                    return Response({"detail": "Duplicate A-Level subject"}, status=400)
                seen.add(sid)
                subject = alevel_subjects.get(sid)
                if not subject:
                    return Response({f"Invalid A-Level subject: {sid}"}, status=400)
                alevel_bulk.append(ALevelResult(application=application, subject=subject, grade=item["grade"].upper()))

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
            # payment.application = application
            # payment.save(update_fields=["application"]) 

            # save M-2-M field
            if programs_data:
               application.programs.set(programs_data) 

            OLevelResult.objects.bulk_create(olevel_bulk, batch_size=50)
            ALevelResult.objects.bulk_create(alevel_bulk, batch_size=50)
            ApplicationDocument.objects.bulk_create(document_objs, batch_size=50)

            # === Success: Send email & notification ===
            threading.Thread(
                target=send_mail,
                kwargs={
                    "subject": "Application Submitted Successfully!",
                    "message": f"Dear {application.first_name} {application.last_name},\n\n"
                               f"Your application has been successfully submitted to Ndejje University.\n"
                               f"Application ID: {application.id}\n"
                               f"Submitted on: {application.created_at.strftime('%d %B %Y')}\n\n"
                               f"Thank you,\nNdejje University Admissions Team",
                    "from_email": settings.DEFAULT_FROM_EMAIL,
                    "recipient_list": [application.email],
                    "fail_silently": True,
                },
                daemon=True
            ).start()

            create_notification(request.user, "Application Submitted", "Your application has been successfully submitted.")

            return Response({
                "message": "Application submitted successfully!",
                "application_id": application.id,
            }, status=status.HTTP_201_CREATED)

        except ValueError as e:
            return Response({"detail": str(e)}, status=400)
        except Exception as e:
            logger.error(f"Application submission failed: {e}", exc_info=True)
            return Response({"detail": str(e)}, status=500)
        
# list applications
class ListApplications(generics.ListAPIView):
    queryset = Application.objects.filter(~Q(status__in=['draft','Admitted', 'rejected', 'accepted'])).order_by('created_at')
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
        now = timezone.now()

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

    # 3. Serialize everything
    data = {
        'application': ApplicationSerializer(application).data,
        'olevel_results': OlevelResultSerializer(olevel_results, many=True).data,
        'alevel_results': AlevelResultSerializer(alevel_results, many=True).data,
        'documents':  DocumentSerializer(documents, many=True).data,
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

        data = {
            'application': ApplicationDetailSerializer(application).data,
            'olevel_results': ListOlevelResultSerializer(olevel_results, many=True).data,
            'alevel_results': ListAlevelResultSerializer(alevel_results, many=True).data,
            'documents': DocumentSerializer(documents, many=True).data,
        }

        return Response(data)


# ==================================================Academic Levels==========================================

# create level
class CreateAcademicLevels(generics.CreateAPIView):
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
                Application.objects.filter(id=application.id).update(status="accepted")

                # ======================================================================
                # 🔥 ASYNC EMAIL USING SAME STYLE YOU REQUESTED
                # ======================================================================
                threading.Thread(
                    target=send_mail,
                    kwargs={
                        "subject": "Congratulations! You have been admitted to Ndejje University",
                        "message": (
                             f"Dear {application.first_name} {application.last_name},\n\n"
                            f"CONGRATULATIONS!\n\n"
                            f"We are delighted to inform you that your application has been **successfully reviewed and ACCEPTED**.\n\n"
                            f"You have been offered admission to study:\n"
                            f"• Program: {admission.admitted_program.name}\n"
                            f"• Campus: {admission.admitted_campus.name}\n"
                            f"• Study Mode: {application.study_mode}\n"
                            f"• Batch: {admission.admitted_batch.name} ({admission.admitted_batch.academic_year})\n\n"
                            f"Your provisional admission letter will be sent shortly.\n\n"
                            f"We look forward to welcoming you to the Ndejje University family!\n\n"
                            f"Warm regards,\n"
                            f"Admissions Office\n"
                            f"Ndejje University\n"
                            f"Email: admissions@ndejjeuniversity.ac.ug\n"
                            f"Website: www.ndejjeuniversity.ac.ug"
                        ),
                        "from_email": settings.DEFAULT_FROM_EMAIL,
                        "recipient_list": [application.email],
                        "fail_silently": False,
                    }
                ).start()

                # ======================================================================
                # 🔥 ASYNC NOTIFICATION USING SAME STYLE
                # ======================================================================
                threading.Thread(
                    target=create_notification,
                    kwargs={
                        "user": application.applicant,
                        "title": "Admission Successful",
                        "msg": "Congratulations! You have been admitted to Ndejje University",
                    }
                ).start()

                # ======================================================================

                return Response(self.serializer_class(admission).data, status=201)

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
        data = serializer.save()
        if data:
            send_admission_update(data)

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
        total_applications = Application.objects.all().count()
        pending_applications = Application.objects.filter(status='submitted').count()
        admitted_students = AdmittedStudent.objects.filter(is_registered=True).count()
        rejected_students = Application.objects.filter(status='rejected').count()
        total_batches = Batch.objects.all().count()
        active_batches = Batch.objects.filter(is_active=True).count()

        return Response({
            "totalApplication":total_applications,
            "pendingApplications":pending_applications,
            "admittedStudents":admitted_students,
            "rejectedStudents":rejected_students,
            "total_batches":total_batches,
            "activeBatches":active_batches
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
        # Get the application – make sure it belongs to the logged-in user or admin
        application = get_object_or_404(
            Application,
            id=application_id,
            # applicant=request.user  # ← uncomment if only applicant can download own letter
        )

        # Fetch related data
        olevel_results = OLevelResult.objects.filter(application=application).select_related('subject')
        alevel_results = ALevelResult.objects.filter(application=application).select_related('subject')

        # Current date for the letter
        today = date.today()

        # Render template
        html_string = render_to_string(
            'student_profile.html',
            {
                'application': application,
                'olevel_results': olevel_results,
                'alevel_results': alevel_results,
                'today': today,
            },
            request=request
        )

        # Generate PDF with WeasyPrint
        pdf_file = HTML(string=html_string, base_url=request.build_absolute_uri()).write_pdf()

        # Response as downloadable PDF
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = (
            f'attachment; filename="Admission_Letter_{application.full_name.replace(" ", "_")}_{application.application_reference or "N-A"}.pdf"'
        )
        response.write(pdf_file)

        return response



