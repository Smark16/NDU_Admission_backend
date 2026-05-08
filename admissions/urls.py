from django.urls import path
from admissions import views
from admissions.analytics_views import AnalyticsDashboardView

app_name = 'admissions'

urlpatterns = [
    # Analytics
    path('analytics/dashboard', AnalyticsDashboardView.as_view(), name='analytics_dashboard'),

    # Dashboard URLs
    path('dashboard', views.ApplicantDashboard.as_view(), name='dashboard'),
    path('check_student_status', views.CheckStudentStatus.as_view()),
    path('admission_dashboard_stats', views.AdminDashboardStats.as_view()),
    path('id_cards/eligible', views.IDCardEligibleStudents.as_view()),
    path('id_cards', views.IDCardList.as_view()),
    path('id_cards/generate', views.GenerateIDCard.as_view()),
    path('id_cards/<int:card_id>/preview-data', views.IDCardPreviewData.as_view()),
    path('id_cards/<int:card_id>/revoke', views.RevokeIDCard.as_view()),
    path('id_cards/<int:card_id>/reissue', views.ReissueIDCard.as_view()),
    
    # # Application URLs
    path('applications', views.ListApplications.as_view()),
    path('create_applications', views.create_applications),
    path('create_direct_applications', views.create_direct_applications),
    path('direct_entry_applications', views.ListDirectEntryApplications.as_view()),
    path('all_applications_report', views.AllApplicationsReport.as_view()),
    path('rejected_applications', views.ListRejectedApplications.as_view()),
    path('reject_application/<int:application_id>', views.RejectStudent.as_view()),
    path('application_detail/<int:application_id>', views.application_detail),
    path('review_application/<int:application_id>', views.ReviewApplication.as_view()),
    path('single_app/<int:application_id>', views.SingleApplication.as_view()),
    path('change_applicatio_status/<int:pk>', views.ChangeApplicationStatus.as_view()),
    path('edit_application_profile/<int:application_id>', views.EditApplicationProfile.as_view()),
    path('generate-reg-no/', views.generate_reg_no_view, name='generate_reg_no'),

    # Subject Urls

    # ========================Alevel=====================
    path('list_alevel_subject', views.ListAlevelSubjects.as_view()),
    path('create_alevel_subjects', views.CreateAlevelSubjects.as_view()),
    path('edit_alevel_results/<int:pk>', views.EditAlevelSubjecgts.as_view()),
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
    path('update_admission/<int:pk>/', views.UpdateAdmittedStudent.as_view()),
    path('list_admitted_students',  views.ListAdmittedStudents.as_view()),
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

    # Admission Change Requests
    path('change_requests/my', views.StudentChangeRequestListCreate.as_view(), name='student_change_requests'),
    path('change_requests/all', views.AdminChangeRequestList.as_view(), name='admin_change_requests'),
    path('change_requests/<int:pk>/review', views.AdminChangeRequestReview.as_view(), name='review_change_request'),

    # Direct entry (admin / manual / legacy migration)
    path('direct_application_entry', views.DirectApplicationEntryView.as_view(), name='direct_application_entry'),
    path('direct_admission_entry', views.DirectAdmissionEntryView.as_view(), name='direct_admission_entry'),
]








