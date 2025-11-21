from django.urls import path
from .views import *

urlpatterns = [
    path('general_overview',  GeneralOverview.as_view()),
    path('Admitted_students_by_Faculty', Admitted_students_by_Faculty.as_view()),
    path('students_data', ViewFacultyAdmissions.as_view()),
    path('export_faculty_excel/', ExportFacultyAdmissionsExcel.as_view()),
]