from django.urls import path
from audit import views

app_name = 'audit'

urlpatterns = [
    # auth logs
    path('auth_logs/', views.ListAuditLogs.as_view()),
    path('delete_auth_log/<int:pk>', views.DeleteAuditLogs.as_view()),
    path('delete_all_auth_logs', views.DeleteAllAuthLogs.as_view()),

    # crud logs
    path('crud_logs', views.ListLogsView.as_view()),
    path('remove_crud_log/<int:pk>', views.DeleteCrudlogs.as_view()),
    path('delete_all_crud_logs', views.DeleteAllCrudLogs.as_view())
]


















