from django.urls import path
from .views import *
from .erp_views import CreateJobOpeningErpView, OnboardHiredCandidateView

urlpatterns = [
   path('list_openings/', ListJobOpenings.as_view()),
   path('create_opening_erp/', CreateJobOpeningErpView.as_view()),
   path('onboard_hired/<int:application_id>/', OnboardHiredCandidateView.as_view()),
   path('open_jobs/', ListOpenJobs.as_view()),
   path('open_jobs/<int:job_id>/', RetrieveOpenJob.as_view()),
   path('create_openings/', CreateJobOpenings.as_view()),
   path('update_openings/<int:pk>/', UpdateJobOpenings.as_view()),
   path('delete_openings/<int:pk>/', DeleteJobOpenings.as_view()),
   path('openings/<int:job_id>/', SingleJobOpening.as_view()),
   path('opening_stats/', OpeningStats.as_view()),

   # applications
   path('list_job_positions/', ListJobPositions.as_view()),
   path('list_applications/', ListJobApplications.as_view()),
   path('create_job_application/', create_job_application),
   path('shortlist/<int:pk>/', Shortlist.as_view()),
   path('bulk_shortlist/', BulkShortList.as_view()),
   path('job-applications/<int:application_id>/pdf/', DownloadJobApplicationPDF.as_view()),
   path('bulk_download_pdfs/', BulkJobApplicationPDFDownloadView.as_view()),
   path('track_application/', track_application),
   path('list_hired_candidates/', HiredCandidates.as_view()),
   path('hired_stats/', HiredStats.as_view()),
   path('single_app/<int:app_id>/', SingleApplication.as_view()),
   path('export_hired_candidates/', handleHiredCandidateExport.as_view()),

   # interviews
   path('interview_lists/', InterviewPipelineView.as_view()),
   path('move_to_next_stage/', MoveCandidatesToStage.as_view()),
   path('change_interview_status/<int:interview_id>/', ChangeInterviewStatus.as_view()),
   path('hired/', MarkAsHired.as_view())
]
