from accounts.models import Campus
from accounts.erp_drf_permissions import CanViewAdmissionQueues, user_has_any_erp_perm
from .models import *
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import *
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError as DRFValidationError
from .serializers import *
from .permissions import (
    VerifyPhysicalDocumentsPermission,
    EditApplicationRegistrationPermission,
    user_can_approve_application,
    user_can_reject_application,
    user_can_admit_applicant,
    user_can_restore_revoked_admission,
    CanAdmitApplicant,
    CanManageAdmissionChangeRequests,
)
from audit.utils import log_audit_event
from rest_framework.parsers import MultiPartParser, FormParser
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from django.conf import settings
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.db.utils import OperationalError
# from .utils.validate_photo import validate_passport_photo
from .tasks import celery_send_application_email, celery_application_notification, celery_admission_email, celery_admission_update, celery_create_student_account
from accounts.tasks import celery_send_account_email
from .utils.trigger_background_tasks import trigger_background_tasks
from payments.models import ApplicationPayment
from Drafts.models import DraftApplication
from django.db.models import Q
import time

import logging
import json

from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.template.loader import render_to_string
from datetime import date

from urllib.parse import quote
from .utils.reg_no import generate_reg_no

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
    serializer = CudApplicationSerializer(data=request.data, context={"request": request}, partial=True)
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
            application.has_olevel = str(request.data.get('has_olevel', '')).lower() in ('true', '1', 'yes')
            application.has_alevel = str(request.data.get('has_alevel', '')).lower() in ('true', '1', 'yes')

            if payment:
                application.application_fee_paid = True
                application.application_fee_amount = payment.amount
                application.application_reference = payment.external_reference

            # if passport_photo := files.get("passport_photo"):
            #      application.passport_photo = passport_photo

            # if 'passport_photo' in request.FILES:
            #     application.passport_photo = request.FILES['passport_photo']
            
            draft = None
            try:
                draft = DraftApplication.objects.get(
                    applicant=request.user,
                    batch_id=request.data.get('batch')
                )
            except DraftApplication.DoesNotExist:
                draft = None

            
            if draft and draft.passport_photo:
                try:
                    original_name = draft.passport_photo.name.split('/')[-1]
                    application.passport_photo.save(
                        original_name,
                        draft.passport_photo.file,
                        save=False
                    )
                except Exception as e:
                    logger.error(f"Failed to copy passport photo from draft: {e}")
                    return Response({"detail": "Failed to process passport photo"}, status=400)

            elif 'passport_photo' in request.FILES:
                application.passport_photo = request.FILES['passport_photo']

            else:
                return Response({"detail": "Passport photo is required"}, status=400)

            # Save the main application first (so it gets an ID)
            application.save()

            # Link payment to application
            if payment:
                payment.application = application
                payment.save(update_fields=["application"])

            # === Programs (Many-to-Many) ===
            if programs_data:
                application.programs.set(programs_data)
            
            # manage draft documents
            if not request.FILES.getlist('documents') and draft:
                try:
                    if draft.olevel_document:
                        ApplicationDocument.objects.create(
                            application=application,
                            file=draft.olevel_document,
                            name=draft.olevel_document.name.split('/')[-1],
                            document_type="OLevel"
                        )

                    if draft.alevel_document:
                        ApplicationDocument.objects.create(
                            application=application,
                            file=draft.alevel_document,
                            name=draft.alevel_document.name.split('/')[-1],
                            document_type="ALevel"
                        )

                    if draft.other_documents:
                        ApplicationDocument.objects.create(
                            application=application,
                            file=draft.other_documents,
                            name=draft.other_documents.name.split('/')[-1],
                            document_type="Others"
                        )

                except Exception as copy_error:
                    logger.warning(f"Failed to copy some documents from draft: {copy_error}")
                    # Do not fail the whole submission, just log

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

# ===============================Direct entry applications===========================================
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_direct_applications(request):
    MAX_FILE_SIZE = settings.FILE_UPLOAD_MAX_MEMORY_SIZE

    # === FILE SIZE VALIDATION ===
    for file_obj in request.FILES.getlist('documents', []):
        if file_obj.size > MAX_FILE_SIZE:
            return Response(
                {"detail": f"Each document must be ≤ 50 MB. '{file_obj.name}' is too large ({file_obj.size / (1024*1024):.1f} MB)."},
                status=400
            )

    if 'passport_photo' in request.FILES:
        photo = request.FILES['passport_photo']
        if photo.size > MAX_FILE_SIZE:  # You can make this smaller (e.g. 10MB) if needed
            return Response(
                {"detail": f"Passport photo must be ≤ 10 MB. '{photo.name}' is too large ({photo.size / (1024*1024):.1f} MB)."},
                status=400
            )

    with transaction.atomic():
        try:
            data = request.data.copy()
            files = request.FILES

            # === PARSE ADDITIONAL QUALIFICATIONS ===
            additional_qualifications = []
            try:
                additional_qual_str = request.data.get("additional_qualifications", "[]")
                if additional_qual_str:
                    additional_qualifications = json.loads(additional_qual_str)
            except (json.JSONDecodeError, TypeError):
                additional_qualifications = []

            # === PARSE RESULTS ONCE ===
            olevel_results = json.loads(request.data.get("olevel_results", "[]"))
            alevel_results = json.loads(request.data.get("alevel_results", "[]"))

            # === VALIDATE MAIN APPLICATION DATA ===
            serializer = CudApplicationSerializer(data=data, context={"request": request})
            serializer.is_valid(raise_exception=True)

            # Direct-entry fallback: if no school pay reference is supplied,
            # proceed as unpaid so admins can capture applicants quickly.
            fee_paid = bool(serializer.validated_data.get('application_fee_paid', False))
            school_pay_ref = (serializer.validated_data.get('school_pay_reference') or '').strip()
            if fee_paid and not school_pay_ref:
                fee_paid = False

            # Remove fields we don't want the client to control
            programs_data = serializer.validated_data.pop('programs', None)
            serializer.validated_data.pop('entered_by', None)

            # === HANDLE USER ACCOUNT (Prevent duplicate applications) ===
            email = data.get('email', '').strip().lower()
            if not email:
                return Response({"detail": "Email is required"}, status=400)

            # Check if user already has an application for this batch
            existing_application = Application.objects.filter(
                applicant__email=email,
                batch=serializer.validated_data.get('batch')
            ).first()

            if existing_application:
                return Response({
                    "detail": "An application for this email and batch already exists.",
                    "application_id": existing_application.id
                }, status=400)

            # Get or create user
            account_password = 'applicant@12345'
            is_new_account = False

            # Reuse existing account by either email or username to avoid unique collisions.
            user = User.objects.filter(
                Q(email__iexact=email) | Q(username__iexact=email)
            ).first()
            if not user:
                # Create new user
                user = User.objects.create(
                    email=email,
                    first_name=data.get('first_name', ''),
                    last_name=data.get('last_name', ''),
                    phone=data.get('phone', ''),
                    username=email,
                    is_applicant=True,
                )

                user.set_password(account_password)
                user.save()
                is_new_account = True
            else:
                return Response({
                    "detail": "An account with this email already exists.",  
                }, status=400)

            # === CREATE APPLICATION ===
            application = Application(**serializer.validated_data)
            application.applicant = user
            application.status = "submitted"
            application.entered_by = request.user
            application.application_fee_paid = True
            application.is_direct_entry = True

            if passport_photo := files.get("passport_photo"):
                application.passport_photo = passport_photo

            application.save()

            # === SAVE PROGRAMS (M2M) ===
            if programs_data:
                application.programs.set(programs_data)

            # === BUILD AND SAVE O-LEVEL RESULTS ===
            olevel_bulk = []
            has_olevel = str(request.data.get('has_olevel', '')).lower() in ('true', '1', 'yes')
            if has_olevel:
                seen = set()
                for item in olevel_results:
                    try:
                        sid = int(item["subject"])
                    except (ValueError, TypeError, KeyError):
                        return Response({"detail": f"Invalid O-Level subject ID: {item.get('subject')}"}, status=400)

                    if sid in seen:
                        return Response({"detail": "Duplicate O-Level subject"}, status=400)
                    seen.add(sid)

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

            # === BUILD AND SAVE A-LEVEL RESULTS ===
            alevel_bulk = []
            has_alevel = str(request.data.get('has_alevel', '')).lower() in ('true', '1', 'yes')
            if has_alevel:
                seen = set()
                for item in alevel_results:
                    try:
                        sid = int(item["subject"])
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

            # === SAVE DOCUMENTS ===
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

            # Bulk create everything
            if olevel_bulk:
                OLevelResult.objects.bulk_create(olevel_bulk, batch_size=50)
            if alevel_bulk:
                ALevelResult.objects.bulk_create(alevel_bulk, batch_size=50)
            if document_objs:
                ApplicationDocument.objects.bulk_create(document_objs, batch_size=50)

            # === SAVE ADDITIONAL QUALIFICATIONS ===
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

            # === SEND WELCOME EMAIL FOR NEW ACCOUNTS ===
            if is_new_account:
                celery_send_account_email.delay(user.id, account_password)

            return Response({
                "message": "Application submitted successfully!",
                "application_id": application.id,
            }, status=status.HTTP_201_CREATED)

        except DRFValidationError as e:
            return Response({"detail": e.detail}, status=400)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)
        except Exception as e:
            logger.error("Direct application creation failed: %s", str(e), exc_info=True)
            return Response({"detail": "An error occurred while processing your application."}, status=500)
        
# list applications
class ListApplications(generics.ListAPIView):
    serializer_class = ListApplicationsSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def get_queryset(self):
        qs = Application.objects.filter(
            ~Q(status__in=['draft', 'admitted', 'Admitted', 'rejected']),
            is_direct_entry=False
        ).order_by('created_at')

        # Optional query-param filters so the frontend can narrow server-side
        status_filter = self.request.query_params.get('status')
        fee_paid = self.request.query_params.get('fee_paid')
        batch_id = self.request.query_params.get('batch')
        if status_filter:
            qs = qs.filter(status=status_filter)
        if fee_paid is not None:
            qs = qs.filter(application_fee_paid=(fee_paid.lower() == 'true'))
        if batch_id:
            qs = qs.filter(batch_id=batch_id)
        return qs

class AllApplicationsReport(generics.ListAPIView):
    serializer_class = AllApplicationsReportSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def get_queryset(self):

        return Application.objects.select_related(
            'academic_level', 'batch', 'campus', 'entered_by'
        ).prefetch_related('programs', 'programs__faculty').filter(
            ~Q(status__in=['draft', 'Admitted', 'rejected']),
        ).order_by('created_at')

class ListDirectEntryApplications(generics.ListAPIView):
    queryset = (
        Application.objects.filter(is_direct_entry=True)
        .select_related("academic_level", "batch", "campus", "entered_by")
        .prefetch_related("programs", "programs__faculty")
        .filter(~Q(status__in=["draft", "Admitted", "rejected"]))
        .order_by("-created_at")
    )
    serializer_class = AllApplicationsReportSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

class RejectStudent(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, application_id):
        if not user_can_reject_application(request.user):
            return Response(
                {"detail": "You do not have permission to reject applications."},
                status=status.HTTP_403_FORBIDDEN,
            )
        _rejection_reason = request.data.get("rejection_reason", "No reason provided")
        try:
            with transaction.atomic():
                application = Application.objects.select_related("applicant").get(pk=application_id)
                application.status = "rejected"
                application.save()
                try:
                    celery_application_notification.delay(
                        application.applicant_id,
                        "Application Rejected",
                        "We regret to inform you that your application has been rejected.",
                    )
                except Exception as exc:
                    logger.warning("Reject notification task failed: %s", exc)
                return Response({"detail": "Application rejected successfully"}, status=200)
        except Application.DoesNotExist:
            return Response({"detail": "Application not found"}, status=404)
        except Exception as e:
            return Response({"detail": str(e)}, status=400)

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
    permission_classes = [IsAuthenticated]

    def patch(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                app_id = self.kwargs['pk']
                newStatus = request.data.get('status')
                ns = str(newStatus or '').strip().lower()
                user = request.user
                if not user.is_superuser:
                    if ns == 'accepted':
                        if not user_can_approve_application(user):
                            return Response(
                                {
                                    'detail': (
                                        'You do not have permission to approve applications '
                                        '(admissions.approve_application or ERP approve_admissions).'
                                    ),
                                },
                                status=status.HTTP_403_FORBIDDEN,
                            )
                    elif ns == 'rejected':
                        if not user_can_reject_application(user):
                            return Response(
                                {
                                    'detail': (
                                        'You do not have permission to reject applications '
                                        '(admissions.reject_application or ERP approve_admissions).'
                                    ),
                                },
                                status=status.HTTP_403_FORBIDDEN,
                            )
                    else:
                        if not user.has_perm('admissions.change_application'):
                            return Response(
                                {'detail': 'You do not have permission to change application status.'},
                                status=status.HTTP_403_FORBIDDEN,
                            )

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

class EditApplicationProfile(APIView):
    permission_classes = [IsAuthenticated, EditApplicationRegistrationPermission]

    def patch(self, request, application_id):
        application = get_object_or_404(Application, pk=application_id)
        allowed_fields = {
            "first_name",
            "last_name",
            "middle_name",
            "date_of_birth",
            "gender",
            "nationality",
            "phone",
            "email",
            "address",
            "disabled",
            "next_of_kin_name",
            "next_of_kin_contact",
            "next_of_kin_relationship",
            "nin",
            "passport_number",
        }
        payload = {k: v for k, v in request.data.items() if k in allowed_fields}
        required_non_blank_fields = {
            "first_name",
            "last_name",
            "date_of_birth",
            "gender",
            "nationality",
            "phone",
            "email",
            "next_of_kin_name",
            "next_of_kin_contact",
            "next_of_kin_relationship",
        }
        # Avoid failing partial updates when frontend sends empty strings
        # for required fields it did not actually intend to clear.
        payload = {
            key: value
            for key, value in payload.items()
            if not (key in required_non_blank_fields and str(value).strip() == "")
        }
        if not payload:
            return Response({"detail": "No valid profile fields provided."}, status=status.HTTP_400_BAD_REQUEST)

        serializer = CudApplicationSerializer(application, data=payload, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(
            {
                "detail": "Profile updated successfully.",
                "application": ApplicationDetailSerializer(application).data,
            },
            status=status.HTTP_200_OK,
        )


class ChangeApplicationProgramme(APIView):
    permission_classes = [IsAuthenticated, EditApplicationRegistrationPermission]

    def patch(self, request, application_id):
        application = get_object_or_404(
            Application.objects.prefetch_related("programs").select_related("campus"),
            pk=application_id,
        )
        raw_program_ids = request.data.get("program_ids", [])
        if not isinstance(raw_program_ids, list) or not raw_program_ids:
            return Response({"detail": "program_ids must be a non-empty list."}, status=400)

        try:
            program_ids = [int(pid) for pid in raw_program_ids]
        except (TypeError, ValueError):
            return Response({"detail": "program_ids must contain valid integers."}, status=400)

        program_qs = Program.objects.filter(id__in=program_ids)
        if program_qs.count() != len(set(program_ids)):
            return Response({"detail": "One or more selected programmes are invalid."}, status=400)

        campus_id = request.data.get("campus_id")
        campus_changed = False
        if campus_id not in (None, "", "null"):
            try:
                application.campus = Campus.objects.get(pk=int(campus_id))
                campus_changed = True
            except (TypeError, ValueError, Campus.DoesNotExist):
                return Response({"detail": "Invalid campus_id."}, status=400)

        application.programs.set(program_qs)
        if campus_changed:
            application.save(update_fields=["campus", "updated_at"])
        else:
            application.save(update_fields=["updated_at"])

        return Response(
            {
                "detail": "Programme choices updated successfully.",
                "programs": [{"id": p.id, "name": p.name} for p in application.programs.all()],
                "campus": application.campus.name if application.campus else None,
            },
            status=200,
        )

# list rejected students
class ListRejectedApplications(generics.ListAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = ListApplicationsSerializer
    queryset = Application.objects.filter(status='rejected')

# ================================subjects================================================

# create O subjects
class CreateOlevelSubjects(generics.CreateAPIView):
    queryset = OLevelSubject.objects.all()
    serializer_class = OlevelSubjectSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

class ListOlevelSubjects(generics.ListAPIView):
    queryset = OLevelSubject.objects.all()
    serializer_class = OlevelSubjectSerializer
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        cache_key = 'all_olevel_subjects_list'
        try:
            cached_data = cache.get(cache_key)
            if cached_data is not None:
                return Response(cached_data)
        except Exception:
            cached_data = None

        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        data = serializer.data

        try:
            cache.set(cache_key, data, timeout=60 * 60 * 24)
        except Exception:
            pass

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
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        cache_key = 'all_alevel_subjects_list'
        try:
            cached_data = cache.get(cache_key)
            if cached_data is not None:
                return Response(cached_data)
        except Exception:
            cached_data = None

        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        data = serializer.data

        try:
            cache.set(cache_key, data, timeout=60 * 60 * 24)
        except Exception:
            pass

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
class EditBatch(generics.UpdateAPIView):
    queryset = Batch.objects.all()
    serializer_class = BatchSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def put(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.serializer_class(instance, data=request.data, partial=True)
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
    permission_classes = [IsAuthenticated]
    queryset = Batch.objects.all()
    serializer_class = BatchSerializer

    def get(self, request):
        now = timezone.now().date()

        # Try cache (skip gracefully if Redis is unavailable)
        cached = None
        try:
            version = cache.get('active_batch_version', 0)
            cache_key = f'active_batch_{version}'
            cached = cache.get(cache_key)
        except Exception:
            cache_key = 'active_batch_0'

        if cached is not None:
            return Response(cached, status=status.HTTP_200_OK)

        try:
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

            try:
                cache.set(cache_key, data, timeout=60 * 60 * 24)
            except Exception:
                pass

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


class CheckStudentStatus(APIView):
    """Check if the logged-in user is an admitted student (student portal gate)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        try:
            admitted_student = (
                AdmittedStudent.objects.select_related(
                    "admitted_program",
                    "admitted_campus",
                    "admitted_batch",
                    "application",
                )
                .filter(
                    Q(application__applicant=user) | Q(student_user=user) | Q(reg_no=user.username),
                    is_admitted=True,
                )
                .first()
            )
            if admitted_student:
                return Response(
                    {
                        "is_admitted_student": True,
                        "student_id": admitted_student.student_id,
                        "reg_no": admitted_student.reg_no,
                        "program": admitted_student.admitted_program.name
                        if admitted_student.admitted_program
                        else None,
                        "program_id": admitted_student.admitted_program_id,
                        "campus": admitted_student.admitted_campus.name
                        if admitted_student.admitted_campus
                        else None,
                        "campus_id": admitted_student.admitted_campus_id,
                        "study_mode": admitted_student.study_mode,
                        "passport_photo": request.build_absolute_uri(admitted_student.application.passport_photo.url)
                            if admitted_student.application and admitted_student.application.passport_photo
                            else None,
                    },
                    status=status.HTTP_200_OK,
                )
            return Response({"is_admitted_student": False}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {"is_admitted_student": False, "error": str(e)},
                status=status.HTTP_200_OK,
            )

# =========================================================Applicant Dashboard===============================
class ApplicantDashboard(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        # Get the most recent application
        application = Application.objects.filter(applicant=user).order_by('-created_at').first()

        if not application:
            # Fall back to a saved draft so the applicant can see and continue it
            from Drafts.models import DraftApplication
            draft = DraftApplication.objects.filter(applicant=user).order_by('-updated_at').first()

            if draft:
                name_parts = [p for p in [draft.first_name, draft.last_name] if p]
                program_names = (
                    list(draft.programs.values_list('name', flat=True))
                    if hasattr(draft, 'programs') and draft.programs.exists()
                    else []
                )
                return Response({
                    "application_status": "draft",
                    "draft_id": draft.id,
                    "last_saved": draft.updated_at,
                    "applicant_name": " ".join(name_parts) if name_parts else None,
                    "campus": draft.campus.name if draft.campus_id and hasattr(draft, 'campus') and draft.campus else None,
                    "programs": program_names,
                    "has_admission": False,
                    "id": None,
                    "batch": None,
                    "applied_date": draft.updated_at,
                    "admission_letter_pdf": None,
                    "student_id": None,
                }, status=status.HTTP_200_OK)

            return Response(
                {"detail": "You have not submitted any application yet."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Base data from application
        selected_programs = list(application.programs.values_list("name", flat=True))
        base_data = {
            "id":application.id,
            "batch": application.batch.name if application.batch else None,
            "campus": application.campus.name if application.campus else None,
            "programs": selected_programs,
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
            "programs": [admission.admitted_program.name] if admission.admitted_program else base_data.get("programs", []),
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
    
# list level (active only — e.g. applicants)
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

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            with transaction.atomic():
                instance.delete()
        except ProtectedError:
            return Response(
                {
                    "detail": (
                        "Cannot delete this academic level because other records still depend on it "
                        "(for example programmes with student enrollments or fee rules). Remove or "
                        "reassign those first."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)

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
        try:
            with transaction.atomic():
                instance.delete()
        except ProtectedError:
            return Response(
                {
                    "detail": (
                        "Cannot delete this faculty because one or more of its programmes "
                        "still have protected links (for example student programme enrollments "
                        "or other records). Remove or reassign those records first, or delete "
                        "the programmes individually after clearing dependencies."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({"detail": "faculty deleted successfully"})

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

class ListProgramBatchOptionsForAdmission(APIView):
    """
    Active ProgramBatch rows for a programme — minimal fields for admit-officer UI.
    """
    permission_classes = [IsAuthenticated, CanAdmitApplicant]

    def get(self, request, program_id):
        from Programs.models import ProgramBatch

        qs = (
            ProgramBatch.objects.filter(program_id=program_id, is_active=True)
            .order_by('-start_date', 'name')
            .only('id', 'name', 'start_date', 'academic_year', 'is_active')
        )
        return Response(
            [
                {
                    'id': b.id,
                    'name': b.name,
                    'start_date': b.start_date.isoformat() if b.start_date else None,
                    'academic_year': b.academic_year or '',
                    'is_active': b.is_active,
                }
                for b in qs
            ],
            status=status.HTTP_200_OK,
        )


# create admission
class AdmitStudent(generics.CreateAPIView):
    queryset = AdmittedStudent.objects.all()
    serializer_class = AdmittedStudentSerializer
    permission_classes = [IsAuthenticated, CanAdmitApplicant]

    def create(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                application_id = request.data.get("application")
                application_obj = get_object_or_404(Application, pk=application_id)
                existing_admission = (
                    AdmittedStudent.objects.select_for_update()
                    .filter(application=application_obj)
                    .first()
                )

                if existing_admission:
                    if existing_admission.is_admitted:
                        return Response(
                            {"detail": "This application is already in admitted list."},
                            status=400,
                        )

                    serializer = self.get_serializer(existing_admission, data=request.data, partial=True)
                    serializer.is_valid(raise_exception=True)
                    admission = serializer.save(
                        admission_date=timezone.now(),
                        is_admitted=True,
                        admitted_by=request.user,
                    )
                else:
                    serializer = self.get_serializer(data=request.data)
                    serializer.is_valid(raise_exception=True)
                    admission = serializer.save(
                        admitted_by=request.user,
                        admission_date=timezone.now(),
                        is_admitted=True,
                    )

                # Fetch application
                try:
                    application = Application.objects.select_related(
                        "applicant",
                        "batch",
                        "campus"
                    ).get(pk=admission.application_id)
                    
                except Application.DoesNotExist:
                    logger.warning(f"Application {admission.application_id} not found")
                    return

                # CRITICAL: Update status immediately
                Application.objects.filter(id=application.id).update(status="Admitted")

                # Student Account Creation and auto Enrollment
                transaction.on_commit(
                    lambda: trigger_background_tasks(admission.id, application.id)
                )
            
                return Response(self.serializer_class(admission).data, status=201)

        except Exception as e:
            logger.exception(f"Admission failed: {e}", exc_info=True)
            return Response({"detail": str(e)}, status=400)

# revoke student 
class RevokeAdmittedStudent(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not (
            request.user.has_perm("admissions.revoke_admission")
            or request.user.has_perm("admissions.change_admittedstudent")
        ):
            return Response({"detail": "You do not have permission to revoke admissions."}, status=403)

        admission = get_object_or_404(AdmittedStudent, pk=pk)
        application = get_object_or_404(Application, pk=admission.application_id)

        reason = str(request.data.get("reason", "")).strip()
        if not reason:
            return Response({"detail": "Revocation reason is required."}, status=400)

        with transaction.atomic():
            # Delete actual files from storage
            if application.admission_letter_pdf:
                application.admission_letter_pdf.delete(save=False)

            if application.admission_letter_docx:
                application.admission_letter_docx.delete(save=False)

            application.is_revoked = True
            application.revoked_at = timezone.now()
            application.revoked_by = request.user
            application.revocation_reason = reason
            application.status = "revoked"
            # Clear database fields
            application.admission_letter_pdf = None
            application.admission_letter_docx = None

            application.save(
                update_fields=[
                    "is_revoked",
                    "revoked_at",
                    "revoked_by",
                    "revocation_reason",
                    "admission_letter_pdf",
                    "admission_letter_docx",
                    "status"
                ]
            )
           
        User.objects.filter(username=admission.reg_no).delete()
        admission.delete()

        return Response({"detail":"Candidate has been removed from Admitted Students"}, status=200)

# restore student 
class RestoreAdmittedStudent(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not user_can_restore_revoked_admission(request.user):
            return Response({"detail": "You do not have permission to restore admissions."}, status=403)

        admission = get_object_or_404(AdmittedStudent, pk=pk)

        with transaction.atomic():
            admission.is_revoked = False
            admission.is_admitted = True
            admission.revoked_at = None
            admission.revoked_by = None
            admission.revocation_reason = ""
            admission.save(
                update_fields=[
                    "is_revoked",
                    "is_admitted",
                    # "revoked_at",
                    # "revoked_by",
                    # "revocation_reason",
                    "updated_at",
                ]
            )
            Application.objects.filter(id=admission.application_id).update(status="Admitted")

        refreshed = (
            AdmittedStudent.objects.select_related(
                "application__applicant",
                "admitted_program__faculty",
                "admitted_batch",
                "admitted_campus",
                # "revoked_by",
            )
            .get(pk=admission.pk)
        )
        return Response(AdmittedStudentListSerializer(refreshed).data, status=200)
 
# list Admitted students
class ListAdmittedStudents(generics.ListAPIView):
    queryset = AdmittedStudent.objects.select_related(
        'admitted_program__faculty',
        'admitted_batch',
        'admitted_campus',
        'application__applicant',
        'programme_enrollment'
    ).all()

    serializer_class = AdmittedStudentListSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        dv = (p.get("documents_verified") or "").lower()
        if dv in ("1", "true", "yes"):
            qs = qs.filter(physical_documents_verified=True)
        elif dv in ("0", "false", "no"):
            qs = qs.filter(physical_documents_verified=False)

        ay = p.get("academic_year")
        if ay:
            qs = qs.filter(admitted_batch__academic_year=ay)
        batch_id = p.get("batch")
        if batch_id:
            qs = qs.filter(admitted_batch_id=batch_id)
        campus_id = p.get("campus")
        if campus_id:
            qs = qs.filter(admitted_campus_id=campus_id)
        program_id = p.get("program")
        if program_id:
            qs = qs.filter(admitted_program_id=program_id)
        faculty_id = p.get("faculty")
        if faculty_id:
            qs = qs.filter(admitted_program__faculty_id=faculty_id)
        reg = (p.get("is_registered") or "").lower()
        if reg in ("1", "true", "yes"):
            qs = qs.filter(is_registered=True)
        elif reg in ("0", "false", "no"):
            qs = qs.filter(is_registered=False)
        return qs

class MarkPhysicalDocumentsVerified(APIView):
    """Record that original hard-copy documents were checked (does not register the student)."""

    permission_classes = [IsAuthenticated, VerifyPhysicalDocumentsPermission]

    def post(self, request, pk):
        notes = (request.data.get("notes") or "").strip()
        student = get_object_or_404(
            AdmittedStudent.objects.select_related("application"),
            pk=pk,
        )
        student.physical_documents_verified = True
        student.physical_documents_verified_at = timezone.now()
        student.physical_documents_verified_by = request.user
        if notes:
            student.physical_documents_notes = notes[:4000]
        student.save(
            update_fields=[
                "physical_documents_verified",
                "physical_documents_verified_at",
                "physical_documents_verified_by",
                "physical_documents_notes",
                "updated_at",
            ]
        )
        desc = (
            f"Physical documents verified for admitted student id={student.pk} "
            f"student_id={student.student_id} reg_no={student.reg_no}. "
            f"Notes: {notes[:500]}"
            if notes
            else f"Physical documents verified id={student.pk}"
        )
        log_audit_event(request.user, "phys_verify", student, desc, request)
        student = AdmittedStudent.objects.select_related(
            "physical_documents_verified_by",
            "admitted_program__faculty",
            "admitted_batch",
            "admitted_campus",
            "application__applicant",
        ).get(pk=student.pk)
        return Response(AdmittedStudentListSerializer(student).data, status=200)


class ClearPhysicalDocumentsVerification(APIView):
    permission_classes = [IsAuthenticated, VerifyPhysicalDocumentsPermission]

    def post(self, request, pk):
        confirm = request.data.get("confirm")
        if confirm is not True and str(confirm).lower() not in ("true", "1", "yes"):
            return Response(
                {"detail": "Send JSON body {\"confirm\": true} to clear verification."},
                status=400,
            )
        student = get_object_or_404(AdmittedStudent, pk=pk)
        if not student.physical_documents_verified:
            return Response({"detail": "This student is not marked as physically verified."}, status=400)
        student.physical_documents_verified = False
        student.physical_documents_verified_at = None
        student.physical_documents_verified_by = None
        student.physical_documents_notes = ""
        student.save(
            update_fields=[
                "physical_documents_verified",
                "physical_documents_verified_at",
                "physical_documents_verified_by",
                "physical_documents_notes",
                "updated_at",
            ]
        )
        log_audit_event(
            request.user,
            "phys_clear",
            student,
            f"Physical document verification cleared for admitted student id={student.pk} "
            f"student_id={student.student_id}",
            request,
        )
        student = AdmittedStudent.objects.select_related(
            "physical_documents_verified_by",
            "admitted_program__faculty",
            "admitted_batch",
            "admitted_campus",
            "application__applicant",
        ).get(pk=student.pk)
        return Response(AdmittedStudentListSerializer(student).data, status=200)

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
            logger.warning("Celery error: %s", f"{e.__class__.__name__}: {e}")

# candidate admission
class CandidateAdmission(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = AdmittedStudent.objects.select_related(
        'admitted_program',
        'admitted_batch',
        'admitted_campus',
        'admitted_by',
        # 'physical_documents_verified_by',
    ).prefetch_related('admitted_program__campuses')
    serializer_class = AdmissionDetailSerializer
    lookup_field = "id"
    lookup_url_kwarg = "admission_id"


# delete admitted student
class DeleteAdmittedStudent(generics.DestroyAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    queryset = AdmittedStudent.objects.all()
    serializer_class = AdmittedStudentSerializer

    def destroy(self, request, *args, **kwargs):
        admission = self.get_object()
        application_id = admission.application_id
        with transaction.atomic():
            admission.delete()
            # Keep application available in queue for fresh admission.
            Application.objects.filter(id=application_id).update(status="accepted")
        return Response({"detail": "Admission deleted successfully."}, status=200)

# Admin dashboard stats
class AdminDashboardStats(APIView):
    permission_classes = [CanViewAdmissionQueues]

    def get(self, request):
        total_applications = Application.objects.all().count()
        online_applications = Application.objects.filter(is_direct_entry=False).count()
        direct_applications = Application.objects.filter(is_direct_entry=True).count()
        pending_applications = Application.objects.filter(status='submitted').count()
        admitted_students = AdmittedStudent.objects.filter(
            is_admitted=True,
        ).count()
        rejected_students = Application.objects.filter(status='rejected').count()
        total_batches = Batch.objects.all().count()
        active_batches = Batch.objects.filter(is_active=True).count()

        return Response({
            "totalApplication":total_applications,
            "onlineApplications":online_applications,
            "directApplications":direct_applications,
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
        import base64 as b64_mod
        import os as _os

        # Get the application – make sure it belongs to the logged-in user or admin
        application = get_object_or_404(
            Application,
            id=application_id,
        )

        # Fetch related data
        olevel_results = OLevelResult.objects.filter(application=application).select_related('subject', 'application')
        alevel_results = ALevelResult.objects.filter(application=application).select_related('subject', 'application')
        qualifications = AdditionalQualifications.objects.filter(application=application).select_related('application')

        # ── Base64-encode the university logo ─────────────────────────────────
        # Resolve relative to this file so it works regardless of CWD
        _here = _os.path.dirname(_os.path.abspath(__file__))            # admissions/
        _backend_root = _os.path.dirname(_here)                          # project root
        _frontend_pub = _os.path.join(
            _os.path.dirname(_backend_root),
            'NDU_Admission_Frontend', 'public',
        )
        logo_b64 = ""
        for _ext in ('Ndejje_University_Logo.png', 'Ndejje_University_Logo.jpg'):
            _logo_path = _os.path.join(_frontend_pub, _ext)
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
                pass  # photo unavailable — template shows placeholder

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

        Application.objects.filter(
            pk=application_id,
            status__in=['pending', 'submitted', 'in_progress', 'draft']  
        ).update(
            reviewed_by=request.user,
            reviewed_at=timezone.now(),
            status='under_review'
        )

        return response


# ══════════════════════════════════════════════════════════════════════════════
# ADMISSION CHANGE REQUESTS
# ══════════════════════════════════════════════════════════════════════════════

class StudentChangeRequestListCreate(APIView):
    """Student: list own requests + submit a new one."""
    permission_classes = [IsAuthenticated]

    def _get_admission(self, user):
        try:
            return AdmittedStudent.objects.select_related(
                'admitted_program', 'admitted_campus'
            ).filter(
                Q(application__applicant=user) | Q(student_user=user) | Q(reg_no=user.username),
                is_admitted=True,
            ).first()
        except Exception:
            return None

    def get(self, request):
        admission = self._get_admission(request.user)
        if not admission:
            return Response({'detail': 'No active admission found.'}, status=404)
        qs = AdmissionChangeRequest.objects.filter(
            admitted_student=admission
        ).select_related('new_program', 'new_campus', 'reviewed_by')

        return Response(AdmissionChangeRequestSerializer(qs, many=True).data)
    def post(self, request):
        admission = self._get_admission(request.user)
        if not admission:
            return Response({'detail': 'No active admission found.'}, status=404)

        # Block if there's already a pending request of the same type
        change_type = request.data.get('change_type')
        if AdmissionChangeRequest.objects.filter(
            admitted_student=admission, change_type=change_type, status='pending'
        ).exists():
            return Response(
                {'detail': 'You already have a pending request of this type. Please wait for it to be reviewed.'},
                status=400
            )

        serializer = AdmissionChangeRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        obj = serializer.save(
            admitted_student=admission,
            requested_by=request.user,
            current_program=admission.admitted_program,
            current_campus=admission.admitted_campus,
            current_study_mode=admission.study_mode,
        )
        return Response(AdmissionChangeRequestSerializer(obj).data, status=201)


class StudentChangeRequestOptions(APIView):
    """Student: fetch available program/campus options for change requests."""
    permission_classes = [IsAuthenticated]

    def _get_admission(self, user):
        try:
            return AdmittedStudent.objects.select_related(
                'admitted_program', 'admitted_campus'
            ).filter(
                Q(application__applicant=user) | Q(student_user=user) | Q(reg_no=user.username),
                is_admitted=True,
            ).first()
        except Exception:
            return None

    def get(self, request):
        admission = self._get_admission(request.user)
        if not admission:
            return Response({'detail': 'No active admission found.'}, status=404)

        base_program_qs = Program.objects.all().order_by("name")
        try:
            # Prefer same academic level options for safer programme transitions.
            if admission.admitted_program and admission.admitted_program.academic_level_id:
                base_program_qs = base_program_qs.filter(
                    academic_level_id=admission.admitted_program.academic_level_id
                )
        except Exception:
            pass

        programs = [
            {"id": p.id, "name": p.name, "code": p.code}
            for p in base_program_qs
        ]
        campuses = [{"id": c.id, "name": c.name} for c in Campus.objects.all().order_by("name")]
        return Response({"programs": programs, "campuses": campuses}, status=200)


class AdminChangeRequestList(APIView):
    """Admin: list all requests with optional status filter."""
    permission_classes = [IsAuthenticated, CanViewAdmissionQueues]

    def get(self, request):
        qs = AdmissionChangeRequest.objects.select_related(
            'admitted_student__application__applicant',
            'admitted_student__admitted_program',
            'admitted_student__admitted_campus',
            'current_program', 'current_campus',
            'new_program', 'new_campus',
            'reviewed_by',
        ).order_by('-created_at')

        status_filter = request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)

        change_type = request.query_params.get('change_type')
        if change_type:
            qs = qs.filter(change_type=change_type)

        return Response(AdmissionChangeRequestSerializer(qs, many=True).data)


class AdminChangeRequestReview(APIView):
    """Admin: approve or reject a specific request."""
    permission_classes = [IsAuthenticated, CanManageAdmissionChangeRequests]

    def post(self, request, pk):
        req_obj = get_object_or_404(AdmissionChangeRequest, pk=pk)

        if req_obj.status != 'pending':
            return Response({'detail': 'This request has already been reviewed.'}, status=400)

        action = request.data.get('action')  # 'approve' or 'reject'
        review_notes = request.data.get('review_notes', '')

        if action not in ('approve', 'reject'):
            return Response({'detail': 'action must be "approve" or "reject".'}, status=400)

        with transaction.atomic():
            req_obj.status = 'approved' if action == 'approve' else 'rejected'
            req_obj.reviewed_by = request.user
            req_obj.reviewed_at = timezone.now()  
            req_obj.review_notes = review_notes
            if action == 'approve':
                admission = req_obj.admitted_student
                if req_obj.change_type == 'program' and req_obj.new_program:
                    admission.admitted_program = req_obj.new_program
                elif req_obj.change_type == 'campus' and req_obj.new_campus:
                    admission.admitted_campus = req_obj.new_campus
                elif req_obj.change_type == 'study_mode' and req_obj.new_study_mode:
                    admission.study_mode = req_obj.new_study_mode
                admission.save()

            req_obj.save()

        return Response(AdmissionChangeRequestSerializer(req_obj).data)

# Generate reg no
@api_view(['POST'])
def generate_reg_no_view(request):
    try:
        campus_id = request.data.get("campus")
        program_id = request.data.get("program")
        study_mode = request.data.get("study_mode")

        if not campus_id or not program_id or not study_mode:
            return Response(
                {"error": "campus, program and study_mode are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        campus = Campus.objects.get(id=campus_id)
        program = Program.objects.get(id=program_id)

        reg_no = generate_reg_no(
            campus=campus,
            program=program,
            study_mode=study_mode
        )

        return Response({"reg_no": reg_no}, status=status.HTTP_200_OK)

    except Campus.DoesNotExist:
        return Response({"error": "Invalid campus"}, status=404)

    except Program.DoesNotExist:
        return Response({"error": "Invalid program"}, status=404)

    except Exception as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
# ══════════════════════════════════════════════════════════════════════════════
# DIRECT APPLICATION ENTRY  (admin-side manual / legacy entry)
def _generate_student_id():
    """Return a unique 10-digit student ID string."""
    import random
    for _ in range(20):
        prefix = str(random.randint(1, 2))
        rest = ''.join([str(random.randint(0, 9)) for _ in range(9)])
        sid = prefix + rest
        if not AdmittedStudent.objects.filter(student_id=sid).exists():
            return sid
    raise ValueError('Could not generate a unique student_id after 20 attempts.')

def _run_post_admission_setup(request, admission, application):
    # ── Student portal account ────────────────────────────────────────────────
    try:
        from .student_accounts import ensure_student_portal_account

        ensure_student_portal_account(admission)
    except Exception as e:
        logger.warning('DirectEntry: student account creation failed: %s', f'{e.__class__.__name__}: {e}')

    # ── Academic programme enrollment ─────────────────────────────────────────
    try:
        from payments.models import RegistrationSettings
        from Programs.models import StudentProgrammeEnrollment, ProgramBatch

        reg_settings = RegistrationSettings.get_settings()
        pb_qs = ProgramBatch.objects.filter(program=admission.admitted_program).order_by(
            '-is_active', '-start_date', 'name'
        )
        program_batch = (
            admission.intended_program_batch
            or (
                pb_qs.filter(is_active=True, name__icontains='year 1').first()
                or pb_qs.filter(is_active=True).first()
                or pb_qs.first()
            )
        )
        if not program_batch:
            program_batch, _ = ProgramBatch.objects.get_or_create(
                program=admission.admitted_program,
                name='Year 1',
                defaults=dict(
                    start_date=timezone.now().date(),
                    is_active=True,
                    academic_year=getattr(admission.admitted_batch, 'academic_year', '') or '',
                ),
            )
        spe, created = StudentProgrammeEnrollment.objects.get_or_create(
            student=admission,
            defaults=dict(
                program=admission.admitted_program,
                program_batch=program_batch,
                current_year_of_study=1,
                current_term_number=1,
                status='enrolled' if reg_settings.auto_enroll_on_admission else 'pending',
                enrolled_by=request.user if reg_settings.auto_enroll_on_admission else None,
                enrolled_at=timezone.now() if reg_settings.auto_enroll_on_admission else None,
                notes=(
                    'Auto-enrolled on direct admission.'
                    if reg_settings.auto_enroll_on_admission
                    else 'Pending commitment fee confirmation.'
                ),
            ),
        )
        if (not created) and reg_settings.auto_enroll_on_admission and spe.status != 'enrolled':
            spe.status = 'enrolled'
            spe.enrolled_by = request.user
            spe.enrolled_at = timezone.now()
            spe.save(update_fields=['status', 'enrolled_by', 'enrolled_at'])
    except Exception as e:
        logger.warning('DirectEntry: SPE creation failed: %s', f'{e.__class__.__name__}: {e}')


class DirectApplicationEntryView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not (
            request.user.is_superuser
            or user_has_any_erp_perm(request.user, "manage_direct_applications")
            or request.user.has_perm("admissions.add_application")
        ):
            return Response(
                {"detail": "You do not have permission for direct application entry."},
                status=status.HTTP_403_FORBIDDEN,
            )

        d = request.data

        # ── Validate required fields ──────────────────────────────────────────
        required_fields = [
            'first_name', 'last_name', 'date_of_birth', 'gender', 'nationality',
            'phone', 'email', 'next_of_kin_name', 'next_of_kin_contact',
            'next_of_kin_relationship', 'batch', 'campus', 'program', 'academic_level',
        ]
        errors = {f: 'This field is required.' for f in required_fields if not d.get(f)}
        if errors:
            return Response(errors, status=400)

        try:
            with transaction.atomic():
                email = d['email'].strip().lower()
                batch = Batch.objects.get(id=d['batch'])
                campus = Campus.objects.get(id=d['campus'])
                from Programs.models import Program as ProgramModel
                program = ProgramModel.objects.get(id=d['program'])
                academic_level = AcademicLevel.objects.get(id=d['academic_level'])

                # ── Applicant user ────────────────────────────────────────────
                from accounts.models import User as UserModel
                applicant_user = UserModel.objects.filter(email=email, is_applicant=True).first()
                if not applicant_user:
                    base_username = email
                    username = base_username
                    if UserModel.objects.filter(username=username).exists():
                        suffix = generate_reference().replace('APP-', '')
                        username = f'{base_username}_{suffix}'
                    applicant_user = UserModel.objects.create_user(
                        username=username,
                        first_name=d['first_name'],
                        last_name=d['last_name'],
                        email=email,
                        password='NDU@1234',
                        is_applicant=True,
                        must_change_password=True,
                    )

                # ── Application ───────────────────────────────────────────────
                app = Application.objects.create(
                    applicant=applicant_user,
                    batch=batch,
                    campus=campus,
                    academic_level=academic_level,
                    source=Application.SOURCE_DIRECT,
                    legacy_application_number=d.get('legacy_application_number') or '',
                    first_name=d['first_name'],
                    last_name=d['last_name'],
                    middle_name=d.get('middle_name', ''),
                    date_of_birth=d['date_of_birth'],
                    gender=d['gender'],
                    nationality=d['nationality'],
                    phone=d['phone'],
                    email=email,
                    address=d.get('address', ''),
                    nin=d.get('nin', ''),
                    passport_number=d.get('passport_number', ''),
                    next_of_kin_name=d['next_of_kin_name'],
                    next_of_kin_contact=d['next_of_kin_contact'],
                    next_of_kin_relationship=d['next_of_kin_relationship'],
                    # Education — use provided values or safe defaults
                    olevel_year=int(d.get('olevel_year') or 0),
                    olevel_index_number=d.get('olevel_index_number') or 'N/A',
                    olevel_school=d.get('olevel_school') or 'N/A',
                    alevel_year=int(d.get('alevel_year') or 0),
                    alevel_index_number=d.get('alevel_index_number') or 'N/A',
                    alevel_school=d.get('alevel_school') or 'N/A',
                    alevel_combination=d.get('alevel_combination') or 'N/A',
                    status='submitted',
                    application_reference=generate_reference(),
                )
                app.programs.set([program])

                # Async notification (best-effort)
                try:
                    celery_application_notification.delay(
                        request.user.id,
                        'Direct Application Created',
                        f'Application {app.application_reference} was created manually for '
                        f'{app.first_name} {app.last_name}.',
                    )
                except Exception:
                    pass

                return Response({
                    'application_id': app.id,
                    'application_reference': app.application_reference,
                    'applicant_user_id': applicant_user.id,
                    'message': f'Application {app.application_reference} created successfully.',
                }, status=201)

        except (Batch.DoesNotExist, Campus.DoesNotExist, AcademicLevel.DoesNotExist) as e:
            return Response({'detail': f'Invalid reference: {e}'}, status=400)
        except Exception as e:
            logger.exception('DirectApplicationEntryView error')
            return Response({'detail': str(e)}, status=500)


class DirectAdmissionEntryView(APIView):
    """
    Admin-side: create a fully admitted student record directly, bypassing
    the applicant portal.  Creates User (applicant) + Application +
    AdmittedStudent + student portal account + SPE in one transaction.

    POST /api/admissions/direct_admission_entry
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not user_can_admit_applicant(request.user):
            return Response(
                {'detail': 'You do not have permission to use direct admission entry.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        d = request.data

        # ── Validate required fields ──────────────────────────────────────────
        required_fields = [
            'first_name', 'last_name', 'date_of_birth', 'gender', 'nationality',
            'phone', 'email', 'next_of_kin_name', 'next_of_kin_contact',
            'next_of_kin_relationship', 'batch', 'campus', 'program',
            'academic_level', 'study_mode',
        ]
        errors = {f: 'This field is required.' for f in required_fields if not d.get(f)}
        if errors:
            return Response(errors, status=400)

        try:
            with transaction.atomic():
                email = d['email'].strip().lower()
                batch = Batch.objects.get(id=d['batch'])
                campus = Campus.objects.get(id=d['campus'])
                from Programs.models import Program as ProgramModel
                program = ProgramModel.objects.get(id=d['program'])
                academic_level = AcademicLevel.objects.get(id=d['academic_level'])
                study_mode = d['study_mode'].strip().upper()

                # ── Applicant user ────────────────────────────────────────────
                from accounts.models import User as UserModel
                applicant_user = UserModel.objects.filter(email=email, is_applicant=True).first()
                if not applicant_user:
                    base_username = email
                    username = base_username
                    if UserModel.objects.filter(username=username).exists():
                        suffix = generate_reference().replace('APP-', '')
                        username = f'{base_username}_{suffix}'
                    applicant_user = UserModel.objects.create_user(
                        username=username,
                        first_name=d['first_name'],
                        last_name=d['last_name'],
                        email=email,
                        password='NDU@1234',
                        is_applicant=True,
                        must_change_password=True,
                    )

                # ── Application ───────────────────────────────────────────────
                app = Application.objects.create(
                    applicant=applicant_user,
                    batch=batch,
                    campus=campus,
                    academic_level=academic_level,
                    source=Application.SOURCE_DIRECT,
                    legacy_application_number=d.get('legacy_application_number') or '',
                    first_name=d['first_name'],
                    last_name=d['last_name'],
                    middle_name=d.get('middle_name', ''),
                    date_of_birth=d['date_of_birth'],
                    gender=d['gender'],
                    nationality=d['nationality'],
                    phone=d['phone'],
                    email=email,
                    address=d.get('address', ''),
                    nin=d.get('nin', ''),
                    passport_number=d.get('passport_number', ''),
                    next_of_kin_name=d['next_of_kin_name'],
                    next_of_kin_contact=d['next_of_kin_contact'],
                    next_of_kin_relationship=d['next_of_kin_relationship'],
                    olevel_year=int(d.get('olevel_year') or 0),
                    olevel_index_number=d.get('olevel_index_number') or 'N/A',
                    olevel_school=d.get('olevel_school') or 'N/A',
                    alevel_year=int(d.get('alevel_year') or 0),
                    alevel_index_number=d.get('alevel_index_number') or 'N/A',
                    alevel_school=d.get('alevel_school') or 'N/A',
                    alevel_combination=d.get('alevel_combination') or 'N/A',
                    status='accepted',
                    application_reference=generate_reference(),
                )
                app.programs.set([program])

                # ── Generate IDs server-side ──────────────────────────────────
                # Allow override from request (e.g. legacy migration with known IDs)
                provided_reg_no = d.get('reg_no', '').strip()
                provided_student_id = d.get('student_id', '').strip()

                if provided_reg_no:
                    if AdmittedStudent.objects.filter(reg_no=provided_reg_no).exists():
                        raise ValueError(f'reg_no "{provided_reg_no}" is already in use.')
                    reg_no = provided_reg_no
                else:
                    reg_no = generate_reg_no(campus, program, study_mode)
    
                if provided_student_id:
                    if AdmittedStudent.objects.filter(student_id=provided_student_id).exists():
                        raise ValueError(f'student_id "{provided_student_id}" is already in use.')
                    student_id = provided_student_id
                else:
                    student_id = _generate_student_id()

                # ── AdmittedStudent ───────────────────────────────────────────
                admission = AdmittedStudent.objects.create(
                    application=app,
                    student_id=student_id,
                    reg_no=reg_no,
                    admitted_program=program,
                    admitted_batch=batch,
                    admitted_campus=campus,
                    study_mode=study_mode,
                    admission_date=timezone.now(),
                    is_admitted=True,
                    admission_notes=d.get('admission_notes', ''),
                )

                # ── Shared post-admission setup (account + SPE) ───────────────
                _run_post_admission_setup(request, admission, app)

                # Async email / notification (best-effort)
                try:
                    celery_admission_email.delay(app.id, admission.id)
                    celery_application_notification.delay(
                        request.user.id,
                        'Direct Admission Completed',
                        f'Student {d["first_name"]} {d["last_name"]} admitted directly as {reg_no}.',
                    )
                except Exception:
                    pass

                return Response({
                    'admission_id': admission.id,
                    'student_id': admission.student_id,
                    'reg_no': admission.reg_no,
                    'application_id': app.id,
                    'application_reference': app.application_reference,
                    'message': (
                        f'Student admitted successfully. '
                        f'Reg No: {admission.reg_no} | Student ID: {admission.student_id}'
                    ),
                }, status=201)

        except (Batch.DoesNotExist, Campus.DoesNotExist, AcademicLevel.DoesNotExist) as e:
            return Response({'detail': f'Invalid reference: {e}'}, status=400)
        except ValueError as e:
            return Response({'detail': str(e)}, status=400)
        except Exception as e:
            logger.exception('DirectAdmissionEntryView error')
            return Response({'detail': str(e)}, status=500)
