from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from audit.models import AuditLog, UserActivity

@login_required
def audit_logs(request):
    """View audit logs (super admin only)"""
    if request.user.role != 'super_admin':
        messages.error(request, 'You do not have permission to access this page.')
        return redirect('admissions:dashboard')
    
    logs = AuditLog.objects.all()
    
    # Search functionality
    search = request.GET.get('search')
    if search:
        logs = logs.filter(
            Q(user__username__icontains=search) |
            Q(action__icontains=search) |
            Q(description__icontains=search)
        )
    
    # Pagination
    paginator = Paginator(logs, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'search': search,
    }
    
    return render(request, 'audit/audit_logs.html', context)

@login_required
def user_activities(request):
    """View user activities (super admin only)"""
    if request.user.role != 'super_admin':
        messages.error(request, 'You do not have permission to access this page.')
        return redirect('admissions:dashboard')
    
    activities = UserActivity.objects.all()
    
    # Search functionality
    search = request.GET.get('search')
    if search:
        activities = activities.filter(
            Q(user__username__icontains=search) |
            Q(activity_type__icontains=search) |
            Q(description__icontains=search)
        )
    
    # Pagination
    paginator = Paginator(activities, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'search': search,
    }
    
    return render(request, 'audit/user_activities.html', context)








