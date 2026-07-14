"""
Leave Management URLs
"""
from django.urls import path
from . import views
from .api_views import (
    HrLeaveBalancesListView,
    LeaveApprovalActionView,
    LeaveRequestAppealView,
    LeaveRequestCancelView,
    LeaveRequestCreateView,
    LeaveRequestListView,
    LeavePolicyDetailView,
    LeavePolicyListCreateView,
    LeaveTypeDetailView,
    LeaveTypeListCreateView,
    MyLeaveBalancesView,
    MyLeaveRequestsView,
    PendingApprovalsListView,
    PublicHolidayDetailView,
    PublicHolidayListCreateView,
)

app_name = 'leave'

urlpatterns = [
    path('leave_types/', LeaveTypeListCreateView.as_view(), name='api_leave_types'),
    path('leave_types/<uuid:type_id>/', LeaveTypeDetailView.as_view(), name='api_leave_type_detail'),
    path('list_requests/', LeaveRequestListView.as_view(), name='api_leave_requests'),
    path('my_requests/', MyLeaveRequestsView.as_view(), name='api_my_leave_requests'),
    path('my_balances/', MyLeaveBalancesView.as_view(), name='api_my_leave_balances'),
    path('create_request/', LeaveRequestCreateView.as_view(), name='api_leave_create'),
    path('cancel/<uuid:request_id>/', LeaveRequestCancelView.as_view(), name='api_leave_cancel'),
    path('appeal/<uuid:request_id>/', LeaveRequestAppealView.as_view(), name='api_leave_appeal'),
    path('hr_balances/', HrLeaveBalancesListView.as_view(), name='api_hr_leave_balances'),
    path('pending_approvals/', PendingApprovalsListView.as_view(), name='api_pending_approvals'),
    path('approvals/<uuid:approval_id>/action/', LeaveApprovalActionView.as_view(), name='api_approval_action'),
    path('policies/', LeavePolicyListCreateView.as_view(), name='api_leave_policies'),
    path('policies/<uuid:policy_id>/', LeavePolicyDetailView.as_view(), name='api_leave_policy_detail'),
    path('holidays/', PublicHolidayListCreateView.as_view(), name='api_public_holidays'),
    path('holidays/<uuid:holiday_id>/', PublicHolidayDetailView.as_view(), name='api_public_holiday_detail'),
    # Staff views
    path('', views.leave_dashboard, name='dashboard'),
    path('request/new/', views.leave_request_create, name='request_create'),
    path('request/<uuid:pk>/', views.leave_request_detail, name='request_detail'),
    path('request/<uuid:pk>/cancel/', views.leave_request_cancel, name='request_cancel'),
    path('request/<uuid:pk>/appeal/', views.leave_request_appeal, name='request_appeal'),
    
    # Approval views
    path('approvals/', views.pending_approvals, name='pending_approvals'),
    path('approvals/<uuid:approval_pk>/review/', views.approval_review, name='approval_review'),
    
    # HR Admin views
    path('hr/requests/', views.hr_leave_requests, name='hr_requests'),
    path('hr/balances/', views.hr_leave_balances, name='hr_balances'),
]
