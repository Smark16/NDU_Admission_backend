from django.urls import path
from .views import *

urlpatterns = [
    path('save_draft/', save_draft_applications),
    path('get_draft_info/', get_draft_application)
]