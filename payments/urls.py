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
from .admin_ledger_views import (
    AdminTuitionLedgerFiltersView,
    AdminTuitionLedgerStudentDetailView,
    AdminTuitionLedgerStudentsView,
    AdminTuitionLedgerTransactionsView,
)

from .semester_registration_views import (
    CheckRegistrationEligibility,
    DownloadStudentOfferLetterPdf,
    GetRegistrationSettings,
    GetSemestersForProgramBatch,
    GetStudentPaymentStatus,
    GetStudentTuitionStructure,
    RegisterForCourses,
    UpdateRegistrationSettings,
)
from .other_fee_schedule_views import (
    OtherFeeScheduleCloneView,
    OtherFeeScheduleRuleDetailView,
    OtherFeeScheduleView,
)
from payments.tuition_payment_views import (
    TuitionLedgerListView,
    ManualHistoricalReconciliationView
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
    path('admin/tuition_ledger/filters', AdminTuitionLedgerFiltersView.as_view(), name='admin_tuition_ledger_filters'),
    path('admin/tuition_ledger/students', AdminTuitionLedgerStudentsView.as_view(), name='admin_tuition_ledger_students'),
    path(
        'admin/tuition_ledger/students/<int:student_id>',
        AdminTuitionLedgerStudentDetailView.as_view(),
        name='admin_tuition_ledger_student_detail',
    ),
    path('admin/tuition_ledger/transactions', AdminTuitionLedgerTransactionsView.as_view(), name='admin_tuition_ledger_transactions'),
    path('student/tuition_structure', GetStudentTuitionStructure.as_view(), name='get_student_tuition_structure'),
    path('student/payment_status', GetStudentPaymentStatus.as_view(), name='get_student_payment_status'),
    path(
        'student/offer_letter_pdf',
        DownloadStudentOfferLetterPdf.as_view(),
        name='student_offer_letter_pdf',
    ),
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

    path('other_fee_schedule/clone', OtherFeeScheduleCloneView.as_view()),
    path('other_fee_schedule/<int:pk>', OtherFeeScheduleRuleDetailView.as_view()),
    path('other_fee_schedule', OtherFeeScheduleView.as_view()),

    # school payment
    path('initiate_payment/', InitiatePayment.as_view()),
    path('webhook/', schoolpay_webhook, name='schoolpay_webhook'),
    path('check_payment_status/<str:payment_ref>/', CheckPaymentStatus.as_view()),
    path('register_with_schoolpay/<int:student_id>/', generate_paycode, name='register_with_schoolpay'),
    path('cancel_pending_payment/', CancelPayment.as_view(), name='cancel_payment'),

    # payments
    path('list_payments', ListPayments.as_view()),

    # transaction sync
    path("transactions/", TuitionLedgerListView.as_view(), name="transactions-list"),
    path("manual-reconcile/", ManualHistoricalReconciliationView.as_view(), name="manual-reconcile"),
]