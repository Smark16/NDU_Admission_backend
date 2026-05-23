from django.urls import path
from .views import *

urlpatterns = [
    path('general_overview',  GeneralOverview.as_view()),
    path('Admitted_students_by_Faculty', Admitted_students_by_Faculty.as_view()),
    path('students_data', ViewFacultyAdmissions.as_view()),
    path('export_admitted_students/', ExportAdmittedExcel.as_view()),
    path('export_faculty_excel/', ExportFacultyAdmissionsExcel.as_view()),
    path('export_first_registration_report/', ExportFirstRegistrationReportExcel.as_view()),
    path('export_applicants_report/', ExportApplicantsExcel.as_view())
]