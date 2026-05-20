from accounts.models import Campus
from accounts.erp_drf_permissions import CanViewAdmissionQueues, user_has_any_erp_perm
from .models import *
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from rest_framework import generics, status, filters
from rest_framework.permissions import *
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError as DRFValidationError
from .serializers import *
from .permissions import (
    VerifyPhysicalDocumentsPermission,
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
from .tasks import celery_send_application_email, celery_application_notification, celery_admission_email, celery_admission_update, celery_create_student_account, celery_send_rejection_email
from accounts.tasks import celery_send_account_email
from payments.utils.school_pay_code import register_student_with_schoolpay
from .utils.trigger_background_tasks import trigger_background_tasks
from .utils.application_programs_display import ordered_programs_for_application
from .utils.program_choices import (
    PROGRAM_CHOICE_CONFIRMED_BY_APPLICANT,
    applicant_confirmed_program_choices,
    applicant_may_edit_program_choices,
    clear_program_choices_confirmation,
    mark_program_choices_confirmed,
    program_options_for_application,
    sync_application_academic_level_from_programs,
    sync_application_program_choices,
)
from .utils.program_choice_integrity import application_has_suspect_program_choices
from payments.models import ApplicationPayment
from Drafts.models import DraftApplication
from django.db.models import Q, Prefetch
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from datetime import datetime
from rest_framework.pagination import PageNumberPagination

import logging
import json

from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.template.loader import render_to_string
from datetime import date

from urllib.parse import quote
from .utils.reg_no import generate_reg_no
from .utils.batch_offer_filters import batch_offer_window_q

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
    # serializer.validated_data.pop('programs', None)

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

            programs_input = request.data.get(
                "programs"
            )

            if programs_input:

                try:

                    if isinstance(programs_input, str):

                        program_list = json.loads(
                            programs_input
                        )

                    else:

                        program_list = programs_input

                    choice_objects = []

                    for index, program_id in enumerate(
                        program_list
                    ):

                        try:

                            pid = int(program_id)

                            if pid > 0:

                                choice_objects.append(

                                    ApplicationProgramChoice(

                                        application=application,

                                        program_id=pid,

                                        choice_order=index + 1
                                    )
                                )

                        except (
                            ValueError,
                            TypeError
                        ):

                            continue

                    if choice_objects:

                        ApplicationProgramChoice.objects.bulk_create(
                            choice_objects
                        )

                except Exception as e:

                    logger.warning(
                        f"Failed to save "
                        f"program choices: {e}"
                    )

            # Link payment to application
            if payment:
                payment.application = application
                payment.save(update_fields=["application"])

            # === Programs (Many-to-Many) ===
            # if programs_data:
            #     application.programs.set(programs_data)
            
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

    # ================= FILE VALIDATION =================
    for file_obj in request.FILES.getlist('documents', []):
        if file_obj.size > MAX_FILE_SIZE:
            return Response({"detail": f"File too large: {file_obj.name}"}, status=400)

    if 'passport_photo' in request.FILES:
        if request.FILES['passport_photo'].size > MAX_FILE_SIZE:
            return Response({"detail": "Passport photo too large"}, status=400)

    # ================= SAFE JSON PARSER =================
    def safe_json(field, default):
        try:
            val = request.data.get(field, "[]")
            return json.loads(val) if val else default
        except Exception:
            return default

    additional_qualifications = safe_json("additional_qualifications", [])
    olevel_results = safe_json("olevel_results", [])
    alevel_results = safe_json("alevel_results", [])

    # ================= EMAIL CHECK EARLY =================
    email = request.data.get("email", "").strip().lower()
    if not email:
        return Response({"detail": "Email is required"}, status=400)

    if User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).exists():
        return Response({"detail": "Account already exists"}, status=400)

    # ================= VALIDATE SERIALIZER FIRST =================
    serializer = CudApplicationSerializer(
        data=request.data,
        context={"request": request},
        partial=True
    )
    serializer.is_valid(raise_exception=True)

    validated = serializer.validated_data.copy()
    validated.pop("entered_by", None)
    validated.pop("programs", None)

    account_password = "applicant@12345"

    try:
        with transaction.atomic():

            # ================= CREATE USER (NOW SAFE) =================
            user = User.objects.create(
                email=email,
                first_name=request.data.get("first_name", ""),
                last_name=request.data.get("last_name", ""),
                phone=request.data.get("phone", ""),
                username=email,
                is_applicant=True,
            )
            user.set_password(account_password)
            user.save()

            # ================= CREATE APPLICATION =================
            application = Application(**validated)
            application.applicant = user
            application.status = "submitted"
            application.entered_by = request.user
            application.application_fee_paid = True
            application.is_direct_entry = True

            if request.FILES.get("passport_photo"):
                application.passport_photo = request.FILES["passport_photo"]

            application.save()

            # ================= PROGRAMS =================
            programs_input = request.data.get("programs")

            if programs_input:
                if isinstance(programs_input, str):
                    program_list = json.loads(programs_input)
                else:
                    program_list = programs_input

                choices = []
                for index, pid in enumerate(program_list, start=1):
                    try:
                        pid = int(pid)
                        if pid > 0:
                            choices.append(
                                ApplicationProgramChoice(
                                    application=application,
                                    program_id=pid,
                                    choice_order=index
                                )
                            )
                    except Exception:
                        continue

                if choices:
                    ApplicationProgramChoice.objects.bulk_create(choices)

            # ================= O-LEVEL =================
            OLevelResult.objects.bulk_create([
                OLevelResult(
                    application=application,
                    subject_id=int(i["subject"]),
                    grade=i["grade"].upper()
                )
                for i in olevel_results
                if "subject" in i
            ])

            # ================= A-LEVEL =================
            ALevelResult.objects.bulk_create([
                ALevelResult(
                    application=application,
                    subject_id=int(i["subject"]),
                    grade=i["grade"].upper()
                )
                for i in alevel_results
                if "subject" in i
            ])

            # ================= DOCUMENTS =================
            ApplicationDocument.objects.bulk_create([
                ApplicationDocument(
                    application=application,
                    file=f,
                    name=f.name[:50],
                    document_type="Others"
                )
                for f in request.FILES.getlist("documents")
            ])

            # ================= QUALIFICATIONS =================
            AdditionalQualifications.objects.bulk_create([
                AdditionalQualifications(
                    application=application,
                    additional_qualification_institution=q.get("institution", ""),
                    additional_qualification_type=q.get("type", ""),
                    additional_qualification_year=q.get("year", ""),
                    class_of_award=q.get("class_of_award", "")
                )
                for q in additional_qualifications
                if q.get("institution")
            ])

        # ================= OUTSIDE TRANSACTION (SAFE) =================
        transaction.on_commit(
            lambda: celery_send_account_email.delay(user.id, account_password)
        )

        return Response({
            "message": "Application submitted successfully",
            "application_id": application.id
        }, status=201)

    except Exception as e:
        logger.error("Direct application failed: %s", str(e), exc_info=True)
        return Response(
            {"detail": "Application failed. No data was saved."},
            status=500
        )
    
# list applications
class ListApplications(generics.ListAPIView):
    serializer_class = ListApplicationsSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

    def get_queryset(self):
        qs = Application.objects.filter(
            ~Q(status__in=['draft', 'admitted', 'Admitted', 'rejected']),
            is_direct_entry=False
        ).select_related(
            "academic_level", "batch", "campus"
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

class StandardPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


def build_applications_report_queryset(request, *, apply_choice_filter: bool = True):
    queryset = (
        Application.objects.select_related(
            "academic_level",
            "batch",
            "campus",
            "applicant",
            "entered_by",
        )
        .prefetch_related(
            Prefetch(
                "program_choices",
                queryset=ApplicationProgramChoice.objects.select_related(
                    "program__faculty"
                ).order_by("choice_order"),
                to_attr="prefetched_program_choices",
            )
        )
        .filter(~Q(status__in=["draft", "Admitted", "admitted", "rejected"]))
        .order_by("created_at")
    )

    status = request.query_params.get("status")
    gender = request.query_params.get("gender")
    academic_level = request.query_params.get("academic_level")
    batch = request.query_params.get("batch")
    campus = request.query_params.get("campus")
    program = request.query_params.get("program")
    faculty = request.query_params.get("faculty")
    date_from = request.query_params.get("date_from")
    date_to = request.query_params.get("date_to")
    choice_confirmation = request.query_params.get("choice_confirmation") if apply_choice_filter else None
    search = (request.query_params.get("search") or "").strip()

    if search:
        queryset = queryset.filter(
            Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(email__icontains=search)
            | Q(application_reference__icontains=search)
            | Q(program_choices__program__name__icontains=search)
            | Q(program_choices__program__faculty__name__icontains=search)
        )

    if status and status != "all":
        queryset = queryset.filter(status=status)
    if gender and gender != "all":
        queryset = queryset.filter(gender=gender)
    if academic_level and academic_level != "all":
        queryset = queryset.filter(academic_level__name=academic_level)
    if batch and batch != "all":
        queryset = queryset.filter(batch__name=batch)
    if campus and campus != "all":
        queryset = queryset.filter(campus__name=campus)
    if program and program != "all":
        queryset = queryset.filter(program_choices__program__name__icontains=program)
    if faculty and faculty != "all":
        queryset = queryset.filter(program_choices__program__faculty__name__icontains=faculty)
    if date_from:
        queryset = queryset.filter(created_at__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(created_at__date__lte=date_to)

    if choice_confirmation and choice_confirmation != "all":
        cc = choice_confirmation.strip().lower()
        if cc == "awaiting":
            queryset = queryset.filter(
                status__in=["submitted", "under_review"],
                program_choices_confirmed_at__isnull=True,
            )
        elif cc == "confirmed":
            queryset = queryset.filter(
                program_choices_confirmed_at__isnull=False,
                program_choices_confirmed_by=PROGRAM_CHOICE_CONFIRMED_BY_APPLICANT,
            )
        elif cc == "flagged":
            from .utils.program_choice_integrity import application_ids_with_suspect_program_choices

            queryset = queryset.filter(
                id__in=application_ids_with_suspect_program_choices()
            )

    return queryset.distinct()


class ApplicationChoiceStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        base = build_applications_report_queryset(request, apply_choice_filter=False)
        from .utils.program_choice_integrity import application_ids_with_suspect_program_choices

        flagged_ids = application_ids_with_suspect_program_choices()
        return Response(
            {
                "awaiting": base.filter(
                    status__in=["submitted", "under_review"],
                    program_choices_confirmed_at__isnull=True,
                ).count(),
                "confirmed": base.filter(
                    program_choices_confirmed_at__isnull=False,
                    program_choices_confirmed_by=PROGRAM_CHOICE_CONFIRMED_BY_APPLICANT,
                ).count(),
                "flagged": base.filter(id__in=flagged_ids).count(),
            }
        )

class AllApplicationsReport(generics.ListAPIView):
    serializer_class = AllApplicationsReportSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    pagination_class = StandardPagination

    ordering_fields = ['created_at', 'id', 'status', 'first_name']
    filter_backends = [OrderingFilter]
    ordering = ['created_at']

    def get_queryset(self):
        return build_applications_report_queryset(self.request, apply_choice_filter=True)
    
class ListDirectEntryApplications(generics.ListAPIView):
    serializer_class = AllApplicationsReportSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    # pagination_class = StandardPagination

    def get_queryset(self):
        return Application.objects.filter(is_direct_entry=True).select_related(
            'academic_level', 
            'batch', 
            'campus', 
            'applicant',
            'entered_by'
        ).prefetch_related(
            Prefetch(
                'program_choices',
                queryset=ApplicationProgramChoice.objects.select_related('program__faculty')
                          .order_by('choice_order'),
                to_attr='prefetched_program_choices'
            )
        ).filter(
            ~Q(status__in=['draft', 'Admitted', 'admitted', 'rejected'])
        ).order_by('-created_at')

class RejectStudent(APIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

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
                    celery_send_rejection_email.delay(
                        application.id,
                        _rejection_reason
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
            application = Application.objects.select_related(
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
                ns = str(newStatus or '').strip().lower()
                try:
                    application = Application.objects.select_related(
                      'applicant', 'batch', 'campus', 'academic_level', 'reviewed_by').get(pk=app_id)
                    application.status = ns
                    application.save()

                    return Response({"detail":"status changed successfully"})
                except Application.DoesNotExist:
                    return Response({"detail":"student Application does not exist"})        
        except Exception as e:
            return Response({"detail":str(e)}) 

class EditApplicationProfile(APIView):
    queryset = Application.objects.all()
    permission_classes = [IsAuthenticated, DjangoModelPermissions]

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

# change application programme choices and campus
class ChangeApplicationProgramme(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, application_id):

        application = get_object_or_404(
            Application.objects.prefetch_related(
                "program_choices__program"
            ).select_related(
                "campus"
            ),
            pk=application_id,
        )

        raw_program_ids = request.data.get("program_ids", [])

        if not isinstance(raw_program_ids, list) or not raw_program_ids:
            return Response(
                {"detail": "program_ids must be a non-empty list."},
                status=400
            )

        try:
            program_ids = [int(pid) for pid in raw_program_ids]

        except (TypeError, ValueError):
            return Response(
                {"detail": "program_ids must contain valid integers."},
                status=400
            )

        # Prevent duplicates
        if len(program_ids) != len(set(program_ids)):
            return Response(
                {"detail": "Duplicate programmes are not allowed."},
                status=400
            )

        # Max 3 choices
        if len(program_ids) > 3:
            return Response(
                {"detail": "Maximum of 3 programme choices allowed."},
                status=400
            )

        programs = Program.objects.filter(
            id__in=program_ids
        )

        if programs.count() != len(program_ids):
            return Response(
                {"detail": "One or more selected programmes are invalid."},
                status=400
            )

        # Optional campus update
        campus_id = request.data.get("campus_id")

        campus_changed = False
        if campus_id not in (None, "", "null"):
            try:
                application.campus = Campus.objects.get(pk=int(campus_id))
                campus_changed = True
            except (TypeError, ValueError, Campus.DoesNotExist):
                return Response({"detail": "Invalid campus_id."}, status=400)

        level_changed = False
        new_level_name = None
        try:
            sync_application_program_choices(application, program_ids)
            level_changed, new_level_name = sync_application_academic_level_from_programs(
                application, program_ids
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)

        # Staff may override applicant confirmation; applicant must confirm again after admin edit.
        had_applicant_confirmation = applicant_confirmed_program_choices(application)
        clear_program_choices_confirmation(application, save=False)
        update_fields = ["program_choices_confirmed_at", "program_choices_confirmed_by", "updated_at"]
        if campus_changed:
            update_fields.insert(0, "campus")
        if level_changed:
            update_fields.insert(0, "academic_level")
        application.save(update_fields=update_fields)

        confirmed_at = application.program_choices_confirmed_at
        program_parts = [
            p.name for p in ordered_programs_for_application(application)
        ]
        desc_parts = ["Programmes: " + ", ".join(program_parts)] if program_parts else []
        if application.campus:
            desc_parts.append(f"Campus: {application.campus.name}")
        if level_changed and new_level_name:
            desc_parts.append(f"Academic level: {new_level_name}")
        raw_note = request.data.get("note")
        if raw_note:
            txt = str(raw_note).strip()
            if txt:
                desc_parts.append(f"Note: {txt[:500]}")
        log_audit_event(
            request.user,
            "program_choice_admin_change",
            application,
            description="; ".join(desc_parts) if desc_parts else "Programme choices updated.",
            request=request,
        )
        detail = "Programme choices updated successfully."
        if level_changed and new_level_name:
            detail += f" Academic level set to {new_level_name}."
        if had_applicant_confirmation:
            detail += (
                " Applicant confirmation was cleared; they should review and confirm again in the portal."
            )
        return Response(
            {
                "detail": detail,
                "programs": [
                    {"id": p.id, "name": p.name}
                    for p in ordered_programs_for_application(application)
                ],
                "campus": application.campus.name if application.campus else None,
                "academic_level": (
                    application.academic_level.name
                    if application.academic_level_id
                    else None
                ),
                "program_choices_confirmed_at": (
                    confirmed_at.isoformat() if confirmed_at else None
                ),
            },
            status=200,
        )


class ApplicantProgramChoicesView(APIView):
    permission_classes = [IsAuthenticated]

    def _get_owned_application(self, request, application_id):
        return get_object_or_404(
            Application.objects.select_related(
                "batch", "campus", "academic_level", "applicant"
            ).prefetch_related("program_choices__program"),
            pk=application_id,
            applicant=request.user,
        )

    def _payload(self, application):
        current = [
            {"id": p.id, "name": p.name}
            for p in ordered_programs_for_application(application)
        ]
        may_edit = applicant_may_edit_program_choices(application)
        suspect = application_has_suspect_program_choices(application)
        return {
            "application_id": application.id,
            "status": application.status,
            "program_choices_confirmed_at": application.program_choices_confirmed_at,
            "program_choices_confirmed_by": application.program_choices_confirmed_by or "",
            "program_choices_verification_sent_at": application.program_choices_verification_sent_at,
            "program_choices_suspect": suspect,
            "can_update_programs": may_edit,
            "can_confirm": may_edit and len(current) > 0,
            "is_confirmed": applicant_confirmed_program_choices(application),
            "current_programs": current,
            "available_programs": program_options_for_application(application) if may_edit else [],
            "campus_id": application.campus_id,
            "academic_level_id": application.academic_level_id,
        }

    def get(self, request, application_id):
        application = self._get_owned_application(request, application_id)
        return Response(self._payload(application), status=200)

    def patch(self, request, application_id):
        application = self._get_owned_application(request, application_id)
        if not applicant_may_edit_program_choices(application):
            return Response(
                {"detail": "Programme choices cannot be changed for this application status."},
                status=400,
            )

        raw_program_ids = request.data.get("program_ids", [])
        if not isinstance(raw_program_ids, list) or not raw_program_ids:
            return Response({"detail": "program_ids must be a non-empty list."}, status=400)

        try:
            program_ids = [int(pid) for pid in raw_program_ids]
        except (TypeError, ValueError):
            return Response({"detail": "program_ids must contain valid integers."}, status=400)

        if len(program_ids) > 3:
            return Response({"detail": "You may select at most three programmes."}, status=400)

        try:
            sync_application_program_choices(application, program_ids)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)

        clear_program_choices_confirmation(application, save=True)
        return Response(
            {
                "detail": "Programme choices saved. Please confirm when they are correct.",
                **self._payload(application),
            },
            status=200,
        )

    def post(self, request, application_id):
        """Confirm current choices (optional program_ids to save then confirm)."""
        application = self._get_owned_application(request, application_id)
        if not applicant_may_edit_program_choices(application):
            return Response(
                {"detail": "Programme choices cannot be confirmed for this application status."},
                status=400,
            )

        raw_program_ids = request.data.get("program_ids")
        if raw_program_ids is not None:
            if not isinstance(raw_program_ids, list) or not raw_program_ids:
                return Response({"detail": "program_ids must be a non-empty list."}, status=400)
            try:
                program_ids = [int(pid) for pid in raw_program_ids]
            except (TypeError, ValueError):
                return Response({"detail": "program_ids must contain valid integers."}, status=400)
            if len(program_ids) > 3:
                return Response({"detail": "You may select at most three programmes."}, status=400)
            try:
                sync_application_program_choices(application, program_ids)
            except ValueError as exc:
                return Response({"detail": str(exc)}, status=400)

        if not ordered_programs_for_application(application):
            return Response(
                {"detail": "Select at least one programme before confirming."},
                status=400,
            )

        mark_program_choices_confirmed(application, save=True)
        return Response(
            {
                "detail": "Thank you. Your programme choices have been confirmed.",
                **self._payload(application),
            },
            status=200,
        )


# APPLICANT CHANGE PROGRAM
class ApplicantChangeApplicationProgramme(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, application_id):

        application = get_object_or_404(
            Application.objects.prefetch_related(
                "program_choices__program"
            ).select_related(
                "applicant", "batch", "campus", "academic_level", "entered_by", "reviewed_by", 
                "revoked_by", "offer_letter_generated_by", "admission"
            ),
            pk=application_id,
        )

        raw_program_ids = request.data.get("program_ids", [])

        if not isinstance(raw_program_ids, list) or not raw_program_ids:
            return Response(
                {"detail": "program_ids must be a non-empty list."},
                status=400
            )

        try:
            program_ids = [int(pid) for pid in raw_program_ids]

        except (TypeError, ValueError):
            return Response(
                {"detail": "program_ids must contain valid integers."},
                status=400
            )

        # Prevent duplicates
        if len(program_ids) != len(set(program_ids)):
            return Response(
                {"detail": "Duplicate programmes are not allowed."},
                status=400
            )

        # Max 3 choices
        if len(program_ids) > 3:
            return Response(
                {"detail": "Maximum of 3 programme choices allowed."},
                status=400
            )

        programs = Program.objects.filter(
            id__in=program_ids
        )

        if programs.count() != len(program_ids):
            return Response(
                {"detail": "One or more selected programmes are invalid."},
                status=400
            )

        # Optional campus update
        campus_id = request.data.get("campus_id")

        if campus_id not in (None, "", "null"):
            try:
                application.campus = Campus.objects.get(
                    pk=int(campus_id)
                )

            except (
                TypeError,
                ValueError,
                Campus.DoesNotExist
            ):
                return Response(
                    {"detail": "Invalid campus_id."},
                    status=400
                )

        with transaction.atomic():

            # Remove old choices
            ApplicationProgramChoice.objects.filter(
                application=application
            ).delete()

            # Create new ordered choices
            choices = []

            for index, pid in enumerate(program_ids, start=1):

                choices.append(
                    ApplicationProgramChoice(
                        application=application,
                        program_id=pid,
                        choice_order=index,
                    )
                )

            ApplicationProgramChoice.objects.bulk_create(
                choices
            )

            application.save(
                update_fields=[
                    "campus",
                    "updated_at"
                ]
            )

        return Response(
            {
                "detail": "Programme choices updated successfully.",

                "programs": [
                    {
                        "id": choice.program.id,
                        "name": choice.program.name,
                        "choice_order": choice.choice_order,
                    }
                    for choice in application.program_choices.select_related(
                        "program"
                    ).order_by(
                        "choice_order"
                    )
                ],

                "campus": (
                    application.campus.name
                    if application.campus
                    else None
                ),
            },
            status=200,
        )


# list applicant selelcted programs
class ListSelectedPrograms(generics.ListAPIView):
    queryset = ApplicationProgramChoice.objects.all()
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = ApplicationProgramChoiceSerializer

    def get_queryset(self):
        application_id = self.kwargs['application_id']
        return ApplicationProgramChoice.objects.filter(application_id=application_id).select_related('application', 'program')


# list rejected students
class ListRejectedApplications(generics.ListAPIView):
    permission_classes = [IsAuthenticated, CanViewAdmissionQueues]
    serializer_class = ListApplicationsSerializer

    def get_queryset(self):
        return (
            Application.objects.filter(status__iexact="rejected")
            .select_related("academic_level", "batch", "campus")
            .order_by("-updated_at", "-created_at")
        )

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

class EditAlevelSubjects(generics.UpdateAPIView):
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
    
#=================================================Olevel Results==========================================
#update Olevel results
class UpdateOlevelResults(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, application_id):
        application = get_object_or_404(Application, id=application_id)
        
        results = request.data.get('results', [])
        
        # Delete old results
        OLevelResult.objects.filter(application=application).delete()
        
        created = []
        for item in results:
            subject = get_object_or_404(OLevelSubject, id=item['subject_id'])
            created.append(OLevelResult.objects.create(
                application=application,
                subject=subject,
                grade=item['grade']
            ))
        
        serializer = OlevelResultSerializer(created, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

#=======================================================Alevel===========================================
class UpdateAlevelResults(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, application_id):
        application = get_object_or_404(Application, id=application_id)
        
        results = request.data.get('results', [])
        
        # Delete old results
        ALevelResult.objects.filter(application=application).delete()
        
        created = []
        for item in results:
            subject = get_object_or_404(ALevelSubject, id=item['subject_id'])
            created.append(ALevelResult.objects.create(
                application=application,
                subject=subject,
                grade=item['grade']
            ))
        
        serializer = AlevelResultSerializer(created, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

#========================================Update Additional qualifications=======================================
class UpdateAdditionalQualififcations(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, application_id):
        application = get_object_or_404(Application, id=application_id)
        
        results = request.data.get('qualifications', [])
        
        # Delete old results
        AdditionalQualifications.objects.filter(application=application).delete()

        created = []
        for item in results:
            created.append(AdditionalQualifications.objects.create(
                application=application,
                additional_qualification_institution=item['additional_qualification_institution'],
                additional_qualification_type=item['additional_qualification_type'],
                additional_qualification_year=item['additional_qualification_year'],
                class_of_award=item['class_of_award']
            ))
        
        serializer = AdditionalQualifficationsSerializer(created, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

#==================================================Update Documents=======================================
class UpdateDocumentAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, doc_id):
        document = get_object_or_404(ApplicationDocument, id=doc_id)

        # Security check
        if document.application.applicant != request.user:
            return Response({"detail": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)

        file = request.FILES.get('file')
        if file:
            document.file = file

        if 'document_type' in request.data:
            document.document_type = request.data['document_type']
        if 'name' in request.data:
            document.name = request.data['name']

        document.save()
        return Response({"detail": "Document updated successfully"}, status=status.HTTP_200_OK)

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
                .filter(batch_offer_window_q())
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
                .filter(batch_offer_window_q())
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
            # from Drafts.models import DraftApplication
            # draft = DraftApplication.objects.filter(applicant=user).order_by('-updated_at').first()

            # if draft:
            #     name_parts = [p for p in [draft.first_name, draft.last_name] if p]
            #     program_names = (
            #         list(draft.programs.values_list('name', flat=True))
            #         if hasattr(draft, 'programs') and draft.programs.exists()
            #         else []
            #     )
            #     return Response({
            #         "application_status": "draft",
            #         "draft_id": draft.id,
            #         "last_saved": draft.updated_at,
            #         "applicant_name": " ".join(name_parts) if name_parts else None,
            #         "campus": draft.campus.name if draft.campus_id and hasattr(draft, 'campus') and draft.campus else None,
            #         "programs": program_names,
            #         "has_admission": False,
            #         "id": None,
            #         "batch": None,
            #         "applied_date": draft.updated_at,
            #         "admission_letter_pdf": None,
            #         "student_id": None,
            #     }, status=status.HTTP_200_OK)

            return Response(
                {"detail": "You have not submitted any application yet."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Base data from application
        selected_programs = [p.name for p in ordered_programs_for_application(application)]
        base_data = {
            "id":application.id,
            "batch": application.batch.name if application.batch else None,
            "campus": application.campus.name if application.campus else None,
            # "programs": selected_programs,
            "applied_date": application.created_at,
            "application_status": application.status,
            "admission_letter_pdf": application.admission_letter_pdf.url if application.admission_letter_pdf else None,
            "program_choices_confirmed_at": application.program_choices_confirmed_at,
            "program_choices_verification_sent_at": application.program_choices_verification_sent_at,
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
    program_choices = ApplicationProgramChoice.objects.filter(application=application).select_related('application')

    qualifications = AdditionalQualifications.objects.filter(application=application).select_related('application')

    # 3. Serialize everything
    data = {
        'application': ApplicationSerializer(application).data,
        'program_choices': ApplicationProgramChoiceSerializer(program_choices, many=True).data,
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
        application = (
            Application.objects.select_related(
                "applicant", "batch", "campus", "academic_level", "reviewed_by"
            )
            .prefetch_related(
                Prefetch(
                    "program_choices",
                    queryset=ApplicationProgramChoice.objects.select_related(
                        "program", "program__faculty"
                    ).order_by("choice_order"),
                )
            )
            .get(pk=application_id)
        )

        # Related queries
        olevel_results = OLevelResult.objects.filter(application=application).select_related('subject')
        alevel_results = ALevelResult.objects.filter(application=application).select_related('subject')
        documents = ApplicationDocument.objects.filter(application=application).select_related('application')
        qualifications = AdditionalQualifications.objects.filter(application=application).select_related('application')
        program_choices = list(application.program_choices.all())

        data = {
            'application': ApplicationDetailSerializer(application).data,
            'olevel_results': ListOlevelResultSerializer(olevel_results, many=True).data,
            'alevel_results': ListAlevelResultSerializer(alevel_results, many=True).data,
            'documents': DocumentSerializer(documents, many=True).data,
            "qualifications":AdditionalQualifficationsSerializer(qualifications, many=True).data,
            "program_choices": ApplicationProgramChoiceSerializer(program_choices, many=True).data
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

    Response shape: ``{ "batches": [...], "default_program_batch_id": <int|null> }``.
    The default is the first cohort in the same ordering used for automatic placement.
    """
    permission_classes = [IsAuthenticated, CanAdmitApplicant]

    def get(self, request, program_id):
        from Programs.program_batch_resolution import (
            admission_program_batch_options_qs,
            program_batch_offer_api_fields,
        )

        admission_batch = None
        application_id = request.query_params.get("application_id")
        admission_batch_id = request.query_params.get("admission_batch_id")
        if application_id:
            application = Application.objects.select_related("batch").filter(
                pk=application_id
            ).first()
            if application is None:
                return Response(
                    {"detail": "Application not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            admission_batch = application.batch
        elif admission_batch_id:
            admission_batch = Batch.objects.filter(pk=admission_batch_id).first()
            if admission_batch is None:
                return Response(
                    {"detail": "Admission batch (intake) not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

        today = timezone.now().date()
        qs = admission_program_batch_options_qs(
            program_id, today=today, admission_batch=admission_batch
        ).only(
            'id',
            'name',
            'start_date',
            'academic_year',
            'is_active',
            'offer_start_date',
            'offer_end_date',
        )
        first = qs.first()
        default_id = first.pk if first else None
        batches = [
            {
                'id': b.id,
                'name': b.name,
                'start_date': b.start_date.isoformat() if b.start_date else None,
                'academic_year': b.academic_year or '',
                'is_active': b.is_active,
                **program_batch_offer_api_fields(
                    b, today=today, admission_batch=admission_batch
                ),
            }
            for b in qs
        ]
        return Response(
            {'batches': batches, 'default_program_batch_id': default_id},
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

                try:
                    if not admission.is_registered_with_schoolpay:

                        result = register_student_with_schoolpay(admission)

                        logger.info(
                            "SchoolPay registration for admitted student %s: %s",
                            admission.id,
                            result.get("success")
                        )

                        if not result["success"]:
                            logger.error(
                                "SchoolPay registration failed for student %s: %s",
                                admission.id,
                                result.get("error") or result.get("data")
                            )

                except Exception:
                    logger.exception(
                        "SchoolPay registration failed during admission"
                    )

                # Student Account Creation and auto Enrollment
                transaction.on_commit(
                    lambda: trigger_background_tasks(admission.id, application.id),
                )
            
                return Response(self.serializer_class(admission).data, status=201)

        except Exception as e:
            logger.exception("Admission failed")
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
        # 'programme_enrollment'
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
        program_batch_id = p.get("program_batch")
        if program_batch_id:
            qs = qs.filter(
                Q(intended_program_batch_id=program_batch_id)
                | Q(programme_enrollment__program_batch_id=program_batch_id)
            ).distinct()
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
        'intended_program_batch',
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
        rejected_students = Application.objects.filter(status__iexact="rejected").count()
        total_batches = Batch.objects.all().count()
        active_batches = Batch.objects.filter(is_active=True).filter(batch_offer_window_q()).count()

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

        from admissions.utils.reg_no import resolve_intake_month_from_batch

        campus = Campus.objects.get(id=campus_id)
        program = Program.objects.get(id=program_id)

        intake_month = (request.data.get("intake_month") or "").strip().upper()
        if not intake_month:
            application_id = request.data.get("application_id")
            admission_batch_id = request.data.get("admission_batch_id")
            if application_id:
                app = Application.objects.select_related("batch").filter(pk=application_id).first()
                if app:
                    intake_month = resolve_intake_month_from_batch(app.batch)
            elif admission_batch_id:
                intake_batch = Batch.objects.filter(pk=admission_batch_id).first()
                if intake_batch:
                    intake_month = resolve_intake_month_from_batch(intake_batch)
        if not intake_month:
            intake_month = "APR"

        reg_no = generate_reg_no(
            campus=campus,
            program=program,
            study_mode=study_mode,
            intake_month=intake_month,
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
            'next_of_kin_relationship', 'batch', 'campus', 'academic_level',
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
                sync_application_program_choices(app, [program.id])

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
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not user_can_admit_applicant(request.user):
            return Response(
                {'detail': 'You do not have permission to use direct admission entry.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        d = request.data

        # ====================== 1. VALIDATION ======================
        required_fields = [
            'first_name', 'last_name', 'date_of_birth', 'gender', 'nationality',
            'phone', 'email'
        ]

        errors = {field: 'This field is required.' for field in required_fields if not d.get(field)}
        
        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)

        # ====================== 2. FETCH RELATED OBJECTS ======================
        try:
            campus = Campus.objects.get(id=d['campus'])
            program = Program.objects.get(id=d['program'])
            academic_level = AcademicLevel.objects.get(id=d['academic_level'])
            batch = Batch.objects.get(id=d.get('batch')) 
        except (Campus.DoesNotExist, Program.DoesNotExist, AcademicLevel.DoesNotExist, Batch.DoesNotExist) as e:
            return Response({'detail': f'Invalid reference: {str(e)}'}, status=400)

        email = d['email'].strip().lower()

        # ====================== 3. MAIN TRANSACTION ======================
        try:
            with transaction.atomic():
                # --- 3.1 Create or Get Applicant User ---
                applicant_user = User.objects.filter(email=email, is_applicant=True).first()

                if not applicant_user:
                    base_username = email.split('@')[0]
                    username = base_username
                    counter = 1
                    while User.objects.filter(username=username).exists():
                        username = f"{base_username}_{counter}"
                        counter += 1

                    applicant_user = User.objects.create_user(
                        username=username,
                        first_name=d['first_name'].strip(),
                        last_name=d['last_name'].strip(),
                        email=email,
                        password='NDU@1234',          
                        is_applicant=True
                    )

                # 2. Safe Date Parsing
                date_str = d.get('date_of_birth') or d.get('dateOfBirth')
                if not date_str:
                    return Response({'date_of_birth': 'Date of birth is required'}, status=400)

                try:
                    dob_date = datetime.strptime(str(date_str).strip(), "%Y-%m-%d").date()
                except ValueError:
                    return Response({'date_of_birth': 'Invalid date format. Use YYYY-MM-DD'}, status=400)

                # --- 3.2 Create Application ---
                application = Application.objects.create(
                    applicant=applicant_user,
                    batch=batch if 'batch' in d else None,
                    campus=campus,
                    academic_level=academic_level,
                    source=Application.SOURCE_DIRECT,
                    status='Admitted',                   
                    application_reference=generate_reference(),
                    first_name=d['first_name'].strip(),
                    last_name=d['last_name'].strip(),
                    middle_name=d.get('middle_name', '').strip(),
                    date_of_birth=dob_date,
                    gender=d['gender'],
                    nationality=d['nationality'],
                    phone=d['phone'].strip(),
                    email=email,
                    address=d.get('address', '').strip(),
                    nin=d.get('nin', '').strip(),
                    passport_number=d.get('passport_number', '').strip(),
                    next_of_kin_name=d.get('next_of_kin_name', '').strip(),
                    next_of_kin_contact=d.get('next_of_kin_contact', '').strip(),
                    next_of_kin_relationship=d.get('next_of_kin_relationship', '').strip(),
                )

                # --- 3.3 Create AdmittedStudent ---
                provided_reg_no = d.get('reg_no', '').strip()
                provided_study_mode = d.get('study_mode', '').strip()

                # Uniqueness checks
                if AdmittedStudent.objects.filter(reg_no=provided_reg_no).exists():
                    raise ValueError(f"Reg No '{provided_reg_no}' is already in use.")

                raw_ipb = d.get("intended_program_batch", None)
                if raw_ipb in (None, ""):
                    intended_val = None
                else:
                    try:
                        intended_val = int(raw_ipb)
                    except (TypeError, ValueError):
                        raise ValueError("intended_program_batch must be an integer or empty.")

                admission_payload = {
                    "application": application.pk,
                    "reg_no": provided_reg_no,
                    "admitted_program": program.pk,
                    "admitted_batch": batch.pk,
                    "admitted_campus": campus.pk,
                    "study_mode": provided_study_mode.upper(),
                    "is_admitted": True,
                    "admission_date": timezone.now(),
                    "admitted_by": request.user.pk,
                    "intended_program_batch": intended_val,
                    "admission_notes": (d.get("admission_notes") or "").strip(),
                }
                adm_serializer = AdmittedStudentSerializer(data=admission_payload)
                try:
                    adm_serializer.is_valid(raise_exception=True)
                except DRFValidationError as exc:
                    return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)
                admitted_student = adm_serializer.save()

                try:
                    if not admitted_student.is_registered_with_schoolpay:

                        result = register_student_with_schoolpay(admitted_student)

                        logger.info(
                            "SchoolPay registration for admitted student %s: %s",
                            admitted_student.id,
                            result.get("success")
                        )

                        if not result["success"]:
                            logger.error(
                                "SchoolPay registration failed for student %s: %s",
                                admitted_student.id,
                                result.get("error") or result.get("data")
                            )

                except Exception:
                    logger.exception(
                        "SchoolPay registration failed during admission"
                    )


                # Queue background tasks AFTER successful commit
                transaction.on_commit(
                    lambda: trigger_background_tasks(admitted_student.id, application.id)
                )

                return Response({
                    'message': 'Direct admission completed successfully.',
                    'application_id': application.id,
                    'admitted_student_id': admitted_student.id,
                    'reg_no': admitted_student.reg_no,
                    'student_id': admitted_student.student_id,
                    'schoolpay_code': admitted_student.schoolpay_code,
                }, status=status.HTTP_201_CREATED)

        except ValueError as ve:
            return Response({'detail': str(ve)}, status=400)
        except Exception as e:
            logger.exception("Direct Admission Error")
            return Response({
                'detail': 'An unexpected error occurred while processing direct admission.'
            }, status=500)
