from django.urls import path
from audit import views

app_name = 'audit'

urlpatterns = [
    path('logs/', views.audit_logs, name='audit_logs'),
    path('activities/', views.user_activities, name='user_activities'),
]


















