"""
URLs for Performance Appraisal module.
"""
from django.urls import path
from . import views
from .api_views import (
    AcknowledgeAppraisalView,
    AppraisalCreateView,
    AppraisalCycleActivateView,
    AppraisalCycleCreateView,
    AppraisalCycleDetailView,
    AppraisalCycleListView,
    AppraisalDetailView,
    AppraisalExportView,
    AppraisalListView,
    AppraisalReportsView,
    AppraisalStatusUpdateView,
    CampusListForAppraisalView,
    MyAppraisalsView,
    PipDetailView,
    PipListCreateView,
    SelfAssessmentSubmitView,
    SetObjectivesView,
    StrategicObjectiveAdminListCreateView,
    StrategicObjectiveDetailView,
    StrategicObjectivesListView,
    SupervisorReviewSubmitView,
    TeamAppraisalsListView,
)

app_name = 'appraisal'

urlpatterns = [
    path('api/cycles/', AppraisalCycleListView.as_view(), name='api_cycles'),
    path('api/cycles/create/', AppraisalCycleCreateView.as_view(), name='api_cycles_create'),
    path('api/cycles/<int:cycle_id>/', AppraisalCycleDetailView.as_view(), name='api_cycle_detail'),
    path('api/cycles/<int:cycle_id>/activate/', AppraisalCycleActivateView.as_view(), name='api_cycle_activate'),
    path('api/campuses/', CampusListForAppraisalView.as_view(), name='api_campuses'),
    path('api/appraisals/my/', MyAppraisalsView.as_view(), name='api_my_appraisals'),
    path('api/appraisals/team/', TeamAppraisalsListView.as_view(), name='api_team_appraisals'),
    path('api/appraisals/<int:appraisal_id>/', AppraisalDetailView.as_view(), name='api_appraisal_detail'),
    path('api/strategic-objectives/', StrategicObjectivesListView.as_view(), name='api_strategic_objectives'),
    path('api/strategic-objectives/admin/', StrategicObjectiveAdminListCreateView.as_view(), name='api_strategic_objectives_admin'),
    path('api/strategic-objectives/<int:pk>/', StrategicObjectiveDetailView.as_view(), name='api_strategic_objective_detail'),
    path('api/reports/', AppraisalReportsView.as_view(), name='api_appraisal_reports'),
    path('api/reports/export/<int:cycle_id>/', AppraisalExportView.as_view(), name='api_appraisal_export'),
    path('api/pips/', PipListCreateView.as_view(), name='api_pips'),
    path('api/pips/<int:pk>/', PipDetailView.as_view(), name='api_pip_detail'),
    path('api/appraisals/<int:appraisal_id>/set-objectives/', SetObjectivesView.as_view(), name='api_set_objectives'),
    path('api/appraisals/<int:appraisal_id>/self-assessment/', SelfAssessmentSubmitView.as_view(), name='api_self_assessment'),
    path('api/appraisals/<int:appraisal_id>/acknowledge/', AcknowledgeAppraisalView.as_view(), name='api_acknowledge'),
    path('api/appraisals/<int:appraisal_id>/supervisor-review/', SupervisorReviewSubmitView.as_view(), name='api_supervisor_review'),
    path('api/appraisals/', AppraisalListView.as_view(), name='api_appraisals'),
    path('api/appraisals/create/', AppraisalCreateView.as_view(), name='api_appraisals_create'),
    path('api/appraisals/<int:appraisal_id>/status/', AppraisalStatusUpdateView.as_view(), name='api_appraisal_status'),
    # Dashboard
    path('', views.appraisal_dashboard, name='dashboard'),
    
    # My Appraisals (Staff)
    path('my-appraisals/', views.my_appraisals_list, name='my_appraisals'),
    path('my-appraisals/<uuid:pk>/', views.my_appraisal_detail, name='my_appraisal_detail'),
    path('my-appraisals/<uuid:pk>/view-objectives/', views.view_objectives, name='view_objectives'),
    path('my-appraisals/<uuid:pk>/self-assessment/', views.self_assessment_form, name='self_assessment'),
    path('my-appraisals/<uuid:pk>/acknowledge/', views.acknowledge_appraisal, name='acknowledge'),
    
    # Team Appraisals (Supervisor/Manager)
    path('team-appraisals/', views.team_appraisals_list, name='team_appraisals'),
    path('team-appraisals/<uuid:pk>/', views.team_appraisal_detail, name='team_appraisal_detail'),
    path('team-appraisals/<uuid:pk>/set-objectives/', views.set_objectives_form, name='set_objectives'),
    path('team-appraisals/<uuid:pk>/review/', views.supervisor_review_form, name='supervisor_review'),
    
    # HR Admin - Appraisal Management
    path('manage/', views.appraisal_manage_list, name='manage_list'),
    path('manage/<uuid:pk>/', views.appraisal_manage_detail, name='manage_detail'),
    path('manage/<uuid:pk>/approve/', views.hr_approve_appraisal, name='hr_approve'),
    path('manage/<uuid:pk>/publish/', views.hr_publish_appraisal, name='hr_publish'),
    
    # Cycles Management (HR Admin)
    path('cycles/', views.cycle_list, name='cycle_list'),
    path('cycles/create/', views.cycle_create, name='cycle_create'),
    path('cycles/<uuid:pk>/', views.cycle_detail, name='cycle_detail'),
    path('cycles/<uuid:pk>/edit/', views.cycle_edit, name='cycle_edit'),
    path('cycles/<uuid:pk>/activate/', views.cycle_activate, name='cycle_activate'),
    
    # Strategic Objectives (HR Admin)
    path('strategic-objectives/', views.strategic_objectives_list, name='strategic_objectives'),
    path('strategic-objectives/create/', views.strategic_objective_create, name='strategic_objective_create'),
    path('strategic-objectives/<uuid:pk>/edit/', views.strategic_objective_edit, name='strategic_objective_edit'),
    
    # Reports & Analytics
    path('reports/', views.appraisal_reports, name='reports'),
    path('reports/export/<uuid:cycle_id>/', views.export_appraisals, name='export_appraisals'),
    
    # PIP Management
    path('pip/', views.pip_list, name='pip_list'),
    path('pip/<uuid:pk>/', views.pip_detail, name='pip_detail'),
    path('pip/<uuid:appraisal_id>/create/', views.pip_create, name='pip_create'),
]
