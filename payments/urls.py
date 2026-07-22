from django.urls import path

# NEW MODULE: semester tuition matrix (FeePlanRule × ProgramBatch × Semester)
from .batch_semester_fee_views import BatchSemesterFeeMatrixView, BulkUploadSemesterTuitionView
from .adhoc_views import (
    FeeHeadDetailView,
    FeeHeadListView,
    StudentAdHocChargeDetailView,
    StudentAdHocChargeListCreate,
    StudentAdHocChargeWaiveView,
    StudentBulkChargesCreateView,
    StudentExemptionChargesCreateView,
)
from .admin_ledger_views import (
    AdminTuitionLedgerFiltersView,
    AdminTuitionLedgerStudentDetailView,
    AdminTuitionLedgerStudentsExportView,
    AdminTuitionLedgerStudentsView,
    AdminTuitionLedgerTransactionsView,
    SendCommitmentFeeReminderView,
)

from .application_fee_exception_views import (
    ApplicationFeeExceptionsView,
    ClearPendingApplicationFeePaymentView,
    ReconcileApplicationFeePaymentView,
    SyncUnpaidApplicationFeeView,
    VerifyApplicationFeePaymentView,
)
from .registration_lookup_views import (
    AdminRegistrationLookupDetailView,
    AdminRegistrationLookupSearchView,
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
    verify_registration_card_public,
)
from .student_tuition_payment_views import (
    InitiateTuitionPaymentView,
    TuitionPaymentStatusView,
)
from .other_fee_schedule_views import (
    OtherFeeScheduleCloneView,
    OtherFeeScheduleRuleDetailView,
    OtherFeeScheduleView,
)
from .scholarship_views import (
    ScholarshipAwardApplyView,
    ScholarshipAwardDetailView,
    ScholarshipAwardRevokeView,
    ScholarshipCreditReverseView,
    ScholarshipProgrammeAwardsView,
    ScholarshipProgrammeDetailView,
    ScholarshipProgrammeListCreateView,
)
from payments.tuition_payment_views import (
    TuitionLedgerListView,
    ManualHistoricalReconciliationView,
    StudentTransactions,
    ExportTutionExcel
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
        'admin/tuition_ledger/students/export',
        AdminTuitionLedgerStudentsExportView.as_view(),
        name='admin_tuition_ledger_students_export',
    ),
    path(
        'admin/tuition_ledger/students/<int:student_id>',
        AdminTuitionLedgerStudentDetailView.as_view(),
        name='admin_tuition_ledger_student_detail',
    ),
    path('admin/tuition_ledger/transactions', AdminTuitionLedgerTransactionsView.as_view(), name='admin_tuition_ledger_transactions'),
    path(
        'admin/tuition_ledger/send_commitment_reminders',
        SendCommitmentFeeReminderView.as_view(),
        name='admin_send_commitment_reminders',
    ),
    path(
        'admin/registration_lookup',
        AdminRegistrationLookupSearchView.as_view(),
        name='admin_registration_lookup_search',
    ),
    path(
        'admin/registration_lookup/<int:student_id>',
        AdminRegistrationLookupDetailView.as_view(),
        name='admin_registration_lookup_detail',
    ),
    path('student/tuition_structure', GetStudentTuitionStructure.as_view(), name='get_student_tuition_structure'),
    path('student/payment_status', GetStudentPaymentStatus.as_view(), name='get_student_payment_status'),
    path(
        'student/initiate_tuition_payment',
        InitiateTuitionPaymentView.as_view(),
        name='initiate_tuition_payment',
    ),
    path(
        'student/tuition_payment_status/<str:payment_ref>',
        TuitionPaymentStatusView.as_view(),
        name='tuition_payment_status',
    ),
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
    path(
        'verify_registration/<str:student_id>',
        verify_registration_card_public,
        name='verify_registration_card',
    ),
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
        'admin/student/<int:student_id>/bulk_charges',
        StudentBulkChargesCreateView.as_view(),
        name='student_bulk_charges',
    ),
    path(
        'admin/student/<int:student_id>/exemption_charges',
        StudentExemptionChargesCreateView.as_view(),
        name='student_exemption_charges',
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

    # application-fee reconciliation (staff)
    path(
        'application-fee-exceptions/',
        ApplicationFeeExceptionsView.as_view(),
        name='application-fee-exceptions',
    ),
    path(
        'application-fee-exceptions/<int:payment_id>/verify/',
        VerifyApplicationFeePaymentView.as_view(),
        name='application-fee-verify',
    ),
    path(
        'application-fee-exceptions/<int:payment_id>/reconcile/',
        ReconcileApplicationFeePaymentView.as_view(),
        name='application-fee-reconcile',
    ),
    path(
        'application-fee-exceptions/<int:payment_id>/clear-pending/',
        ClearPendingApplicationFeePaymentView.as_view(),
        name='application-fee-clear-pending',
    ),
    path(
        'application-fee-exceptions/applications/<int:application_id>/sync/',
        SyncUnpaidApplicationFeeView.as_view(),
        name='application-fee-sync-application',
    ),

    # Scholarships
    path(
        'scholarships/',
        ScholarshipProgrammeListCreateView.as_view(),
        name='scholarship-list',
    ),
    path(
        'scholarships/<int:pk>/',
        ScholarshipProgrammeDetailView.as_view(),
        name='scholarship-detail',
    ),
    path(
        'scholarships/<int:pk>/awards/',
        ScholarshipProgrammeAwardsView.as_view(),
        name='scholarship-awards',
    ),
    path(
        'scholarship-awards/<int:pk>/',
        ScholarshipAwardDetailView.as_view(),
        name='scholarship-award-detail',
    ),
    path(
        'scholarship-awards/<int:pk>/apply/',
        ScholarshipAwardApplyView.as_view(),
        name='scholarship-award-apply',
    ),
    path(
        'scholarship-awards/<int:pk>/revoke/',
        ScholarshipAwardRevokeView.as_view(),
        name='scholarship-award-revoke',
    ),
    path(
        'scholarship-credits/<int:pk>/reverse/',
        ScholarshipCreditReverseView.as_view(),
        name='scholarship-credit-reverse',
    ),

    # payments
    path('list_payments', ListPayments.as_view()),

    # transaction sync
    path("transactions/", TuitionLedgerListView.as_view(), name="transactions-list"),
    path("manual-reconcile/", ManualHistoricalReconciliationView.as_view(), name="manual-reconcile"),
    path("student-transactions/", StudentTransactions.as_view(), name="student-transactions"),
    path('export_tution/', ExportTutionExcel.as_view())
]
