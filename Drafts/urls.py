from django.urls import path
from .views import *

urlpatterns = [
    path('save_draft/', save_draft_applications),
    path('get_draft_info/', get_draft_application),
    path('upload_draft_document/', upload_draft_document),
    path('delete_draft_other_document/', delete_draft_other_document),
]