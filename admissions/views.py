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

import logging
import json

logger = logging.getLogger(__name__)

# ===========================applications ===========================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_applications(request):
    with transaction.atomic():
        try:
            data = request.data.copy()
            files = request.FILES

            # Extract files
            doc_files = files.getlist("documents")
            doc_types = request.data.getlist("document_types", [])
            passport_photo = files.get("passport_photo")

            # Parse O-Level + A-Level
            olevel_results = json.loads(request.data.get("olevel_results", "[]"))
            alevel_results = json.loads(request.data.get("alevel_results", "[]"))

            # Create Application
            serializer = CudApplicationSerializer(
                data=data, context={"request": request}
            )
            serializer.is_valid(raise_exception=True)

            application = serializer.save(
                applicant=request.user,
                status="submitted"
            )

            # One save for passport (if exists)
            if passport_photo:
                application.passport_photo = passport_photo

            application.save()  # only ONE save()

            # === OPTIMIZE SUBJECT FETCH (NO DB IN LOOPS) ===
            olevel_subjects = {
                s.id: s for s in OLevelSubject.objects.filter(
                    id__in=[o["subject"] for o in olevel_results]
                )
            }

            alevel_subjects = {
                s.id: s for s in ALevelSubject.objects.filter(
                    id__in=[a["subject"] for a in alevel_results]
                )
            }

            # === BULK CREATE OLEVEL RESULTS ===
            olevel_bulk = []
            seen = set()

            for item in olevel_results:
                sid = item["subject"]
                if sid in seen:
                    return Response({"detail": "Duplicate O-Level subject"}, status=400)
                seen.add(sid)

                subject = olevel_subjects.get(sid)
                if subject:
                    olevel_bulk.append(
                        OLevelResult(
                            application=application,
                            subject=subject,
                            grade=item["grade"].upper(),
                        )
                    )

            OLevelResult.objects.bulk_create(olevel_bulk, batch_size=50)

            # === BULK CREATE ALEVEL RESULTS ===
            alevel_bulk = []
            seen = set()

            for item in alevel_results:
                sid = item["subject"]
                if sid in seen:
                    return Response({"detail": "Duplicate A-Level subject"}, status=400)
                seen.add(sid)

                subject = alevel_subjects.get(sid)
                if subject:
                    alevel_bulk.append(
                        ALevelResult(
                            application=application,
                            subject=subject,
                            grade=item["grade"].upper(),
                        )
                    )

            ALevelResult.objects.bulk_create(alevel_bulk, batch_size=50)

            # === BULK CREATE DOCUMENTS ===
            document_objs = []
            for i, file in enumerate(doc_files):
                doc_type = doc_types[i] if i < len(doc_types) else "Others"

                document_objs.append(
                    ApplicationDocument(
                        application=application,
                        file=file,
                        name=file.name.split('.')[0][:25],
                        document_type=doc_type,
                    )
                )

            ApplicationDocument.objects.bulk_create(document_objs, batch_size=50)

            # === ASYNC EMAIL SEND (DO NOT BLOCK REQUEST) ===
            threading.Thread(
                target=send_mail,
                kwargs={
                    "subject": "Application Submitted Successfully!",
                    "message": f"Dear {application.first_name} {application.last_name},\n\n"
                               f"Your application has been successfully submitted to Ndejje University.\n"
                               f"Application ID: {application.id}\n"
                               f"Submitted on: {application.created_at.strftime('%d %B %Y')}\n\n"
                               f"We will review your application and get back to you soon.\n\n"
                               f"Thank you,\nNdejje University Admissions Team",
                    "from_email": settings.DEFAULT_FROM_EMAIL,
                    "recipient_list": [application.email],
                    "fail_silently": True,
                },
                daemon=True
            ).start()

            create_notification(request.user, "Application Submitted", "Your application has been successfully submitted.")

            # Return response
            return Response(
                {
                    "message": "Application submitted successfully!",
                    "application_id": application.id,
                },
                status=status.HTTP_201_CREATED,
            )

        except Exception as e:
            logger.error(f"Application submission failed: {e}", exc_info=True)
            return Response({"detail": str(e)}, status=500)

# @api_view(['POST'])
# @permission_classes([IsAuthenticated])
# def create_applications(request):
#     with transaction.atomic():
#         try:
#             data = request.data.copy()
#             files = request.FILES

#             # Extract files
#             doc_files = files.getlist('documents')          
#             doc_types = request.data.getlist('document_types', [])  
#             passport_photo = files.get('passport_photo')

#             # Parse JSON strings from frontend
#             olevel_results = request.data.get('olevel_results', '[]')
#             if isinstance(olevel_results, str):
#                 olevel_results = json.loads(olevel_results)

#             alevel_results = request.data.get('alevel_results', '[]')
#             if isinstance(alevel_results, str):
#                 alevel_results = json.loads(alevel_results)

#             # Create main application
#             serializer = CudApplicationSerializer(data=data, context={'request': request})
#             if not serializer.is_valid():
#                 return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

#             application = serializer.save(
#                 applicant=request.user,
#                 status='submitted'
#             )

#             # Save passport photo (optional)
#             if passport_photo:
#                 application.passport_photo = passport_photo
#                 application.save(update_fields=['passport_photo'])

#             # Save O-Level Results
#             seen_olevel_subjects = set()
#             for item in olevel_results:
#                 subject_id = item.get('subject')
#                 grade = item.get('grade')

#                 if not subject_id or not grade:
#                     continue

#                 if subject_id in seen_olevel_subjects:
#                     return Response({"detail":f"Duplicate O-Level subject: {subject.name}. You can only add each subject once."}, status=400)
#                 else:
#                     seen_olevel_subjects.add(subject_id)

#                 try:
#                     subject = OLevelSubject.objects.get(id=subject_id)
#                     OLevelResult.objects.create(
#                         application=application,
#                         subject=subject,
#                         grade=grade.upper()
#                     )
#                 except OLevelSubject.DoesNotExist:
#                     logger.warning(f"O-Level Subject ID {subject_id} not found")
#                     continue

#             # Save A-Level Results
#             seen_alevel_subjects = set()
#             for item in alevel_results:
#                 subject_id = item.get('subject')
#                 grade = item.get('grade')

#                 if not subject_id or not grade:
#                     continue

#                 if subject_id in seen_alevel_subjects:
#                     return Response({"detail":f"Duplicate A-Level subject: {subject.name}. You can only add each subject once."}, status=400)
#                 else:
#                     seen_alevel_subjects.add(subject_id)

#                 try:
#                     subject = ALevelSubject.objects.get(id=subject_id)
#                     ALevelResult.objects.create(
#                         application=application,
#                         subject=subject,
#                         grade=grade.upper()
#                     )
#                 except ALevelSubject.DoesNotExist:
#                     logger.warning(f"A-Level Subject ID {subject_id} not found")
#                     continue

#             # Save Documents (optional + file_url saved!)
#             for i, file in enumerate(doc_files):
#                 doc_type = doc_types[i] if i < len(doc_types) else "Others"
#                 doc = ApplicationDocument(
#                     application=application,
#                     file=file,
#                     name=file.name.split('.')[0][:25],
#                     document_type=doc_type
#                 )
#                 doc.save()  

#                 # Generate and save full URL
#                 doc.file_url = request.build_absolute_uri(doc.file.url)
#                 doc.save(update_fields=['file_url'])

#             # Send confirmation email
#             try:
#                 send_mail(
#                     subject="Application Submitted Successfully!",
#                     message=(
#                         f"Dear {application.first_name} {application.last_name},\n\n"
#                         f"Your application has been successfully submitted to Ndejje University.\n"
#                         f"Application ID: {application.id}\n"
#                         f"Submitted on: {application.created_at.strftime('%d %B %Y')}\n\n"
#                         f"We will review your application and get back to you soon.\n\n"
#                         f"Thank you,\nNdejje University Admissions Team"
#                     ),
#                     from_email=settings.DEFAULT_FROM_EMAIL,
#                     recipient_list=[application.email],
#                     fail_silently=False,
#                 )

#                 create_notification(request.user, "Application Submitted", "Your application has been successfully submitted.")
#             except Exception as e:
#                 logger.error(f"Failed to send email: {e}")
#                 return Response({"detail":"Failed to send email please check connection"}, status=400)

#             return Response({
#                 "message": "Application submitted successfully!",
#                 "application_id": application.id,
#                 "submitted_at": application.created_at.isoformat()
#             }, status=status.HTTP_201_CREATED)

#         except Exception as e:
#             logger.error(f"Application submission failed: {str(e)}", exc_info=True)
#             return Response(
#                 {"detail": str(e)},
#                 status=status.HTTP_500_INTERNAL_SERVER_ERROR
#             )

# list applications
class ListApplications(generics.ListAPIView):
    queryset = Application.objects.all()
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
    queryset = Batch.objects.prefetch_related('programs').select_related('created_by').order_by('-created_at')
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
    queryset = Batch.objects.all()
    serializer_class = BatchSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def get(self, request):
        try:
            now = timezone.now()
            batch = Batch.objects.get(application_start_date__lte=now,  application_end_date__gte=now, is_active=True)
            serializer = self.serializer_class(batch)
            return Response(serializer.data, status=200)
        except Exception as e:
            return Response({
                "detail":str(e),
                "is_active":False
            }, status=400)

    
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
# class AdmitStudent(generics.CreateAPIView):
#     queryset = AdmittedStudent.objects.all()
#     serializer_class = AdmittedStudentSerializer
#     permission_classes = [IsAuthenticated, DjangoModelPermissions]

#     def create(self, request, *args, **kwargs):
#         try:
#             with transaction.atomic():
#                 serializer = self.get_serializer(data=request.data)
#                 serializer.is_valid(raise_exception=True)
#                 admission = serializer.save()
                
#                 try:  
#                     application = Application.objects.select_related('applicant', 'batch', 'campus').prefetch_related('programs').get(pk=admission.application_id)
#                     application.status = 'accepted'
#                     application.save()

#                      # Send confirmation email
#                 except Application.DoesNotExist:
#                     return Response({"detail":"Student application doesnt exist"}, status=400)
                
#                 try:
#                     send_mail(
#                         subject="Congratulations! You have been admitted to Ndejje University",

#                         message=(
#                             f"Dear {application.first_name} {application.last_name},\n\n"
#                             f"CONGRATULATIONS!\n\n"
#                             f"We are delighted to inform you that your application has been **successfully reviewed and ACCEPTED**.\n\n"
#                             f"You have been offered admission to study:\n"
#                             f"• Program: {admission.admitted_program.name}\n"
#                             f"• Campus: {admission.admitted_campus.name}\n"
#                             f"• Study Mode: {application.study_mode}\n"
#                             f"• Batch: {admission.admitted_batch.name} ({admission.admitted_batch.academic_year})\n\n"
#                             f"Your provisional admission letter will be sent shortly.\n\n"
#                             f"We look forward to welcoming you to the Ndejje University family!\n\n"
#                             f"Warm regards,\n"
#                             f"Admissions Office\n"
#                             f"Ndejje University\n"
#                             f"Email: admissions@ndejjeuniversity.ac.ug\n"
#                             f"Website: www.ndejjeuniversity.ac.ug"
#                         ),

#                         from_email=settings.DEFAULT_FROM_EMAIL,
#                         recipient_list=[application.email],
#                         fail_silently=False,
#                     )

#                     create_notification(application.applicant, "Admission successfull", "Congratulations! You have been admitted to Ndejje University")
#                 except Exception as e:
#                     logger.error(f"Failed to send email: {e}")
#                     return Response({"detail":"Failed to send email please check connection"}, status=400)

                
#                 serializer = self.serializer_class(admission)
#                 return Response(serializer.data, status=201)
#         except Exception as e:
#             return Response({"detail":str(e)}, status=400)
 
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







