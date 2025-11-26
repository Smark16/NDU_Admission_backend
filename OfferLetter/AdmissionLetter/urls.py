from django.urls import path
from .views import *

urlpatterns = [
    path('upload_template', UploadTemplate.as_view()),
    path('list_templates', ListTemplates.as_view()),
    path('edit_template/<int:pk>', EditTemplate.as_view()),
    path('delete_template/<int:pk>', DeleteTemplate.as_view()),
    path('send_letter/<int:applicant_id>', send_offer_letter),
    path('status/<int:applicant_id>', offer_letter_status)
]