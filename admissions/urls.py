from django.urls import path
from admissions import views
from admissions import id_card_views
from admissions import id_card_template_views
from admissions.analytics_views import AnalyticsDashboardView
from admissions.email_template_views import (
    EmailTemplateDetailView,
    EmailTemplateListView,
    EmailTemplatePreviewView,
    EmailTemplateResetDefaultView,
)
from admissions.announcement_views import SendAnnouncementView, TestAnnouncementView

app_name = 'admissions'

urlpatterns = [
    # Analytics
    path('analytics/dashboard', AnalyticsDashboardView.as_view(), name='analytics_dashboard'),

    # Dashboard URLs
    path('dashboard', views.ApplicantDashboard.as_view(), name='dashboard'),
    path('check_student_status', views.CheckStudentStatus.as_view()),
    path('admission_dashboard_stats', views.AdminDashboardStats.as_view()),
    
    # # Application URLs
    path('applications', views.ListApplications.as_view()),
    path('create_applications', views.create_applications),
    path('create_direct_applications', views.create_direct_applications),
    path('direct_entry_applications', views.ListDirectEntryApplications.as_view()),
    path('all_applications_report/', views.AllApplicationsReport.as_view()),
    path('all_applications_detail_report/', views.AllApplicationDetailedReport.as_view()),
    path('application_choice_stats/', views.ApplicationChoiceStatsView.as_view()),
    path('test_announcement', TestAnnouncementView.as_view()),
    path('send_announcement', SendAnnouncementView.as_view()),
    path('rejected_applications', views.ListRejectedApplications.as_view()),
    path('reject_application/<int:application_id>', views.RejectStudent.as_view()),
    path('application_detail/<int:application_id>', views.application_detail),
    path('review_application/<int:application_id>', views.ReviewApplication.as_view()),
    path('single_app/<int:application_id>', views.SingleApplication.as_view()),
    path('change_applicatio_status/<int:pk>', views.ChangeApplicationStatus.as_view()),
    path('edit_application_profile/<int:application_id>', views.EditApplicationProfile.as_view()),
    path('change_programme/<int:application_id>', views.ChangeApplicationProgramme.as_view()),
    path(
        'applicant_program_choices/<int:application_id>',
        views.ApplicantProgramChoicesView.as_view(),
    ),
    path('applicant_change_programme/<int:application_id>', views.ApplicantChangeApplicationProgramme.as_view()),
    path('generate-reg-no/', views.generate_reg_no_view, name='generate_reg_no'),
    path('list_selected_programs/<int:application_id>', views.ListSelectedPrograms.as_view(), name='list_selected_programs'),

    #results
    path('update_olevel_results/<int:application_id>/', views.UpdateOlevelResults.as_view()),
    path('update_alevel_results/<int:application_id>/', views.UpdateAlevelResults.as_view()),
    path('update_additional_qualifications/<int:application_id>/', views.UpdateAdditionalQualififcations.as_view()),
    path('document/<int:doc_id>/update/', views.UpdateDocumentAPIView.as_view(), name='update-document'),
    path('upload_document/<int:application_id>/', views.UploadDocumentAPIView.as_view()),
    path('document/<int:doc_id>/', views.DeleteDocumentAPIView.as_view()),
    path('personal-info/<int:application_id>/', views.UpdatePersonalInfoAPIView.as_view()),
    path('update_education_setup/<int:application_id>/', views.update_education_setup),
    path('admin_update_education_setup/<int:application_id>/', views.admin_update_education_setup),
    # Subject Urls

    # ========================Alevel=====================
    path('list_alevel_subject', views.ListAlevelSubjects.as_view()),
    path('create_alevel_subjects', views.CreateAlevelSubjects.as_view()),
    path('edit_alevel_results/<int:pk>', views.EditAlevelSubjects.as_view()),
    path('delete_alevel_subject/<int:pk>', views.DeleteAlevelSubjects.as_view()),

    # ====================olevel===============================
    path('list_olevel_subject', views.ListOlevelSubjects.as_view()),
    path('create_olevel_subjects', views.CreateOlevelSubjects.as_view()),
    path('edit_olevel_subjects/<int:pk>', views.EditOlevelSubjecgts.as_view()),
    path('delete_olevel_subjects/<int:pk>', views.DeleteOlevelSubjects.as_view()),
    
    # # Batch Management URLs
    path('batches/', views.ListBatch.as_view()),
    path('active_batch', views.GetActiveApplicationBatch.as_view()),
    path('active_admission_batch', views.GetActiveAdmissionBatch.as_view()),
    path('create_batch', views.CreateBatch.as_view()),
    path('edit_batch/<int:pk>', views.EditBatch.as_view()),
    path('delete_batch/<int:pk>', views.DeleteBatch.as_view()),
    path('intake_options', views.IntakeOptions.as_view()),

    # academic levels
    path('list_academic_level',  views.ListAcademicLevel.as_view()),
    path('list_admin_academic_level',  views.ListAdminAcademicLevels.as_view()),    
    path('create_levels', views.CreateAcademicLevels.as_view()),
    path('update_academic_levels/<int:pk>', views.UpdateAcademicLevel.as_view()),
    path('delete_level/<int:pk>', views.DeleteAcademicLevel.as_view()),

    # # Faculty Management URLs
    path('faculties', views.ListFaculties.as_view()),
    path('create_faculties', views.CreateFaculty.as_view()),
    path('edit_faculties/<int:pk>', views.UpdateFaculty.as_view()),
    path('delete_faculty/<int:pk>', views.DeleteFaculty.as_view()),
    path('change_status/<int:pk>', views.ChangeFacultyStatus.as_view()),
    
    # Admission Management URLs
    path('create_admissions', views.AdmitStudent.as_view()),
    path(
        'program_batches_options/<int:program_id>/',
        views.ListProgramBatchOptionsForAdmission.as_view(),
    ),
    path('update_admission/<int:pk>/', views.UpdateAdmittedStudent.as_view()),
    path('list_admitted_students/',  views.ListAdmittedStudents.as_view()),
    path('admitted_students/<int:pk>/revoke/', views.RevokeAdmittedStudent.as_view()),
    path('admitted_students/<int:pk>/restore/', views.RestoreAdmittedStudent.as_view()),
    path(
        'admitted_students/<int:pk>/verify_physical_documents/',
        views.MarkPhysicalDocumentsVerified.as_view(),
    ),
    path(
        'admitted_students/<int:pk>/clear_physical_documents/',
        views.ClearPhysicalDocumentsVerification.as_view(),
    ),
    path('delete_admission/<int:pk>/', views.DeleteAdmittedStudent.as_view()),
    path('candidate_admission/<int:admission_id>/', views.CandidateAdmission.as_view()),
    path('student-profile/pdf/<int:application_id>/', views.DownloadAdmissionPDF.as_view(), name='download_admission_pdf'),

    # notifications
    path('list_user_notification', views.ListNotifications.as_view()),
    path('email_templates', EmailTemplateListView.as_view(), name='email_template_list'),
    path('email_templates/<str:key>', EmailTemplateDetailView.as_view(), name='email_template_detail'),
    path('email_templates/<str:key>/preview', EmailTemplatePreviewView.as_view(), name='email_template_preview'),
    path('email_templates/<str:key>/reset', EmailTemplateResetDefaultView.as_view(), name='email_template_reset'),

    # Admission Change Requests
    path('change_requests/my', views.StudentChangeRequestListCreate.as_view(), name='student_change_requests'),
    path('change_requests/options', views.StudentChangeRequestOptions.as_view(), name='student_change_request_options'),
    path('change_requests/all', views.AdminChangeRequestList.as_view(), name='admin_change_requests'),
    path('change_requests/<int:pk>/review', views.AdminChangeRequestReview.as_view(), name='review_change_request'),

    # Direct entry (admin / manual / legacy migration)
    path('direct_application_entry', views.DirectApplicationEntryView.as_view(), name='direct_application_entry'),
    path('direct_admission_entry', views.DirectAdmissionEntryView.as_view(), name='direct_admission_entry'),

    # Student ID cards (admin)
    path('id_cards/eligible', id_card_views.IdCardEligibleListView.as_view(), name='id_cards_eligible'),
    path('id_cards/filter-options', id_card_views.IdCardFilterOptionsView.as_view(), name='id_cards_filter_options'),
    path(
        'id_cards/admitted/<int:admitted_student_id>/passport_photo',
        id_card_views.IdCardAdmittedPassportPhotoView.as_view(),
        name='id_cards_admitted_passport_photo',
    ),
    path('id_cards/generate', id_card_views.IdCardGenerateView.as_view(), name='id_cards_generate'),
    path('id_cards/<int:card_id>/preview-data', id_card_views.IdCardPreviewDataView.as_view(), name='id_cards_preview'),
    path('id_cards/<int:card_id>/revoke', id_card_views.IdCardRevokeView.as_view(), name='id_cards_revoke'),
    path('id_cards/<int:card_id>/reissue', id_card_views.IdCardReissueView.as_view(), name='id_cards_reissue'),
    path('id_cards', id_card_views.IdCardListView.as_view(), name='id_cards_list'),
    # ID card PDF templates (map fields like offer letter)
    path('id_card_templates', id_card_template_views.IdCardPdfTemplateListCreateView.as_view(), name='id_card_templates_list'),
    path('id_card_templates/<int:pk>', id_card_template_views.IdCardPdfTemplateDetailView.as_view(), name='id_card_templates_detail'),
    path(
        'id_card_templates/<int:pk>/pdf_preview',
        id_card_template_views.IdCardPdfTemplatePreviewView.as_view(),
        name='id_card_templates_pdf_preview',
    ),
    path(
        'id_card_templates/<int:pk>/save_field_positions',
        id_card_template_views.IdCardPdfTemplateSavePositionsView.as_view(),
        name='id_card_templates_save_positions',
    ),
]








