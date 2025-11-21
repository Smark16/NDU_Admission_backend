from django.urls import path
from .views import *
# Program Management URLs

urlpatterns = [
    path('list_programs', ListPrograms.as_view()),
    path('create_programs', CreatePrograms.as_view()),
    path('update_program/<int:pk>', UpdateProgram.as_view()),
    path('delete_program/<int:pk>', DeleteProgram.as_view()),
    path('bulk_upload', HandleBulkUpload.as_view()),
    path('change_status/<int:pk>', ChangeProgramStatus.as_view()),
    path("download_program_sheet", ExportProgramTemplateView.as_view())
]