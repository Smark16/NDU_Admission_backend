from django.urls import path
from admissions import views

app_name = 'admissions'

urlpatterns = [
    # Dashboard URLs
    path('dashboard', views.ApplicantDashboard.as_view(), name='dashboard'),
    path('admission_dashboard_stats', views.AdminDashboardStats.as_view()),
    
    # # Application URLs
    path('applications', views.ListApplications.as_view()),
    path('create_applications', views.create_applications),
    path('application_detail/<int:application_id>', views.application_detail),
    path('review_application/<int:application_id>', views.ReviewApplication.as_view()),
    path('single_app/<int:application_id>', views.SingleApplication.as_view()),
    path('change_applicatio_status/<int:pk>', views.ChangeApplicationStatus.as_view()),

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
    path('create_batch', views.CreateBatch.as_view()),
    path('edit_batch/<int:pk>', views.EditBatch.as_view()),
    path('delete_batch/<int:pk>', views.DeleteBatch.as_view()),

    # academic levels
    path('list_academic_level',  views.ListAcademicLevel.as_view()),
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
    path('list_admitted_students',  views.ListAdmittedStudents.as_view()),

    # notifications
    path('list_user_notification', views.ListNotifications.as_view())
]








