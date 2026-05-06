from django.urls import path

# NEW MODULE: semester tuition matrix (FeePlanRule × ProgramBatch × Semester)
from .batch_semester_fee_views import BatchSemesterFeeMatrixView, BulkUploadSemesterTuitionView
from .adhoc_views import (
    FeeHeadDetailView,
    FeeHeadListView,
    StudentAdHocChargeDetailView,
    StudentAdHocChargeListCreate,
    StudentAdHocChargeWaiveView,
)
from .scheduled_fee_views import (
    ScheduledOtherFeeRuleClone,
    ScheduledOtherFeeRuleDetail,
    ScheduledOtherFeeRuleListCreate,
)
from .tuition_payment_views import (
    InitiateTuitionPayment,
    CheckTuitionPaymentStatus,
    GenerateTuitionPaymentReference,
)
from .semester_registration_views import (
    CheckRegistrationEligibility,
    GetRegistrationSettings,
    GetSemestersForProgramBatch,
    GetStudentPaymentStatus,
    GetStudentTuitionStructure,
    RegisterForCourses,
    UpdateRegistrationSettings,
)
from .views import *

app_name = 'payments'

urlpatterns = [
    path('create_fee_plan', CreateFeePlan.as_view()),
    path('list_fee_plan', ListFeePlan.as_view()),
    path('update_fee_plan/<int:pk>', UpdateFeePlan.as_view()),
    path('delete_fee_plan/<int:pk>', DeleteFeePlan.as_view()),

    # NEW MODULE: semester tuition matrix (see batch_semester_fee_views.py)
    path(
        'batch_semester_fees/bulk_upload',
        BulkUploadSemesterTuitionView.as_view(),
        name='batch_semester_fee_bulk_upload',
    ),
    path(
        'batch_semester_fees/matrix',
        BatchSemesterFeeMatrixView.as_view(),
        name='batch_semester_fee_matrix',
    ),
    path(
        'program_batch/<int:program_batch_id>/semesters',
        GetSemestersForProgramBatch.as_view(),
        name='get_semesters_for_program_batch',
    ),
    path('student/initiate_tuition_payment', InitiateTuitionPayment.as_view(), name='initiate_tuition_payment'),
    path('student/generate_tuition_reference', GenerateTuitionPaymentReference.as_view(), name='generate_tuition_reference'),
    path('student/tuition_payment_status/<str:payment_ref>', CheckTuitionPaymentStatus.as_view(), name='check_tuition_payment_status'),
    path('student/tuition_structure', GetStudentTuitionStructure.as_view(), name='get_student_tuition_structure'),
    path('student/payment_status', GetStudentPaymentStatus.as_view(), name='get_student_payment_status'),
    path(
        'student/check_registration_eligibility',
        CheckRegistrationEligibility.as_view(),
        name='check_registration_eligibility',
    ),
    path('student/register_for_courses', RegisterForCourses.as_view(), name='register_for_courses'),
    path('registration_settings', GetRegistrationSettings.as_view(), name='get_registration_settings'),
    path('registration_settings/update', UpdateRegistrationSettings.as_view(), name='update_registration_settings'),

    # --- ad-hoc per-student charges (staff) ---
    path('fee_heads', FeeHeadListView.as_view(), name='fee_heads'),
    path('fee_heads/<int:pk>', FeeHeadDetailView.as_view(), name='fee_head_detail'),
    path(
        'admin/student/<int:student_id>/charges',
        StudentAdHocChargeListCreate.as_view(),
        name='student_adhoc_charges',
    ),
    path(
        'admin/charge/<int:pk>',
        StudentAdHocChargeDetailView.as_view(),
        name='adhoc_charge_detail',
    ),
    path(
        'admin/charge/<int:pk>/waive',
        StudentAdHocChargeWaiveView.as_view(),
        name='adhoc_charge_waive',
    ),
    path(
        'other_fee_schedule',
        ScheduledOtherFeeRuleListCreate.as_view(),
        name='scheduled_other_fee_list_create',
    ),
    path(
        'other_fee_schedule/<int:pk>',
        ScheduledOtherFeeRuleDetail.as_view(),
        name='scheduled_other_fee_detail',
    ),
    path(
        'other_fee_schedule/clone',
        ScheduledOtherFeeRuleClone.as_view(),
        name='scheduled_other_fee_clone',
    ),

    # school payment
    path('initiate_payment/', InitiatePayment.as_view()),
    path('webhook/', schoolpay_webhook, name='schoolpay_webhook'),
    path('check_payment_status/<str:payment_ref>/', CheckPaymentStatus.as_view()),
    path('sync_schoolpay_transactions', SyncSchoolPayTransactions.as_view(), name='sync_schoolpay_transactions'),

    # payments
    path('list_payments', ListPayments.as_view()),
]


















