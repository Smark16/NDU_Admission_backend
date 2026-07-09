"""
Leave Management Views
Implements monthly accrual system with dynamic hierarchical approval workflow
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q, Sum, Count
from datetime import timedelta, date
from decimal import Decimal

from .models import (
    LeaveType,
    LeavePolicy,
    LeaveBalance,
    LeaveRequest,
    LeaveApproval,
    LeaveAccrual,
    PublicHoliday,
)
from .forms import (
    LeaveRequestForm,
    LeaveApprovalForm,
    LeaveAppealForm,
    LeaveBalanceAdjustmentForm,
)
from .workflow_utils import (
    generate_approval_workflow,
    get_staff_supervisor,
    process_leave_approval,
    update_balance_pending,
)
from hr.staff.models import StaffProfile


def is_hr_admin(user):
    """Check if user is HR admin"""
    return user.is_authenticated and (user.is_superuser or user.user_type == 'HR_ADMIN')


# ============================================================================
# STAFF VIEWS - Leave Request & Balance
# ============================================================================

@login_required
def leave_dashboard(request):
    """Staff leave dashboard showing balances and requests"""
    try:
        staff = request.user.staff_profile
    except AttributeError:
        messages.error(request, "Staff profile not found. Please contact HR to link your account to a staff profile.")
        return redirect('staff:my_profile')
    
    current_year = timezone.now().year
    
    # Get leave balances for current year
    balances = LeaveBalance.objects.filter(
        staff=staff,
        year=current_year
    ).select_related('leave_type')
    
    # Get recent leave requests
    recent_requests = LeaveRequest.objects.filter(
        staff=staff
    ).select_related('leave_type').order_by('-request_date')[:10]
    
    # Get upcoming leaves
    upcoming_leaves = LeaveRequest.objects.filter(
        staff=staff,
        status='APPROVED',
        start_date__gte=timezone.now().date()
    ).order_by('start_date')[:5]
    
    # Statistics
    total_requests = LeaveRequest.objects.filter(staff=staff, status='APPROVED').count()
    pending_requests = LeaveRequest.objects.filter(staff=staff, status='PENDING').count()
    
    context = {
        'staff': staff,
        'balances': balances,
        'recent_requests': recent_requests,
        'upcoming_leaves': upcoming_leaves,
        'total_requests': total_requests,
        'pending_requests': pending_requests,
        'current_year': current_year,
    }
    return render(request, 'leave/dashboard.html', context)


@login_required
def leave_request_create(request):
    """Create new leave request"""
    try:
        staff = request.user.staff_profile
    except AttributeError:
        messages.error(request, "Staff profile not found. Please contact HR to link your account to a staff profile.")
        return redirect('staff:my_profile')
    
    if request.method == 'POST':
        form = LeaveRequestForm(request.POST, request.FILES, staff=staff)
        if form.is_valid():
            leave_request = form.save(commit=False)
            leave_request.staff = staff
            leave_request.status = 'PENDING'
            
            # Calculate working days
            start = form.cleaned_data['start_date']
            end = form.cleaned_data['end_date']
            leave_request.total_days = (end - start).days + 1
            
            leave_request.save()
            
            # Generate approval workflow
            generate_approval_workflow(leave_request)
            
            # Update balance pending
            update_balance_pending(leave_request, 'add')
            
            messages.success(request, f'Leave request {leave_request.request_number} submitted successfully!')
            return redirect('leave:request_detail', pk=leave_request.pk)
    else:
        form = LeaveRequestForm(staff=staff)
    
    # Get current balances
    current_year = timezone.now().year
    balances = LeaveBalance.objects.filter(
        staff=staff,
        year=current_year
    ).select_related('leave_type')
    
    context = {
        'form': form,
        'balances': balances,
    }
    return render(request, 'leave/request_form.html', context)


@login_required
def leave_request_detail(request, pk):
    """View leave request details"""
    leave_request = get_object_or_404(LeaveRequest, pk=pk)
    
    # Check permission
    user_staff = getattr(request.user, 'staff_profile', None)
    is_owner = user_staff == leave_request.staff
    is_approver = LeaveApproval.objects.filter(
        leave_request=leave_request,
        approver=user_staff
    ).exists()
    is_hr = is_hr_admin(request.user)
    
    if not (is_owner or is_approver or is_hr):
        messages.error(request, "You don't have permission to view this request.")
        return redirect('leave:dashboard')
    
    # Get approval timeline
    approvals = leave_request.approvals.all().select_related('approver').order_by('level')
    
    context = {
        'leave_request': leave_request,
        'approvals': approvals,
        'is_owner': is_owner,
        'is_approver': is_approver,
        'is_hr': is_hr,
    }
    return render(request, 'leave/request_detail.html', context)


@login_required
def leave_request_cancel(request, pk):
    """Cancel pending leave request"""
    leave_request = get_object_or_404(LeaveRequest, pk=pk)
    
    # Check permission
    try:
        staff = request.user.staff_profile
        if leave_request.staff != staff:
            messages.error(request, "You can only cancel your own requests.")
            return redirect('leave:dashboard')
    except:
        messages.error(request, "Staff profile not found.")
        return redirect('leave:dashboard')
    
    # Can only cancel pending requests
    if leave_request.status != 'PENDING':
        messages.error(request, "Only pending requests can be cancelled.")
        return redirect('leave:request_detail', pk=pk)
    
    if request.method == 'POST':
        leave_request.status = 'CANCELLED'
        leave_request.save()
        
        # Update balance pending
        update_balance_pending(leave_request, 'remove')
        
        messages.success(request, 'Leave request cancelled successfully.')
        return redirect('leave:dashboard')
    
    context = {'leave_request': leave_request}
    return render(request, 'leave/request_cancel_confirm.html', context)


@login_required
def leave_request_appeal(request, pk):
    """Appeal rejected leave request"""
    leave_request = get_object_or_404(LeaveRequest, pk=pk)
    
    # Check permission
    try:
        staff = request.user.staff_profile
        if leave_request.staff != staff:
            messages.error(request, "You can only appeal your own requests.")
            return redirect('leave:dashboard')
    except:
        messages.error(request, "Staff profile not found.")
        return redirect('leave:dashboard')
    
    # Check if can appeal
    if not leave_request.can_appeal:
        messages.error(request, "This request cannot be appealed.")
        return redirect('leave:request_detail', pk=pk)
    
    # Check appeal deadline
    if leave_request.appeal_deadline and timezone.now().date() > leave_request.appeal_deadline:
        messages.error(request, "Appeal deadline has passed.")
        return redirect('leave:request_detail', pk=pk)
    
    if request.method == 'POST':
        form = LeaveAppealForm(request.POST)
        if form.is_valid():
            leave_request.status = 'UNDER_APPEAL'
            leave_request.appeal_reason = form.cleaned_data['appeal_reason']
            leave_request.appeal_date = timezone.now()
            leave_request.can_appeal = False
            leave_request.save()
            
            # Create appeal approval record
            create_appeal_approval(leave_request)
            
            messages.success(request, 'Appeal submitted successfully. It will be reviewed by the next authority.')
            return redirect('leave:request_detail', pk=pk)
    else:
        form = LeaveAppealForm()
    
    context = {
        'form': form,
        'leave_request': leave_request,
    }
    return render(request, 'leave/request_appeal.html', context)


# ============================================================================
# APPROVAL VIEWS - Manager & HR
# ============================================================================

@login_required
def pending_approvals(request):
    """View pending approvals for current user"""
    try:
        staff = request.user.staff_profile
    except:
        messages.error(request, "Staff profile not found.")
        return redirect('leave:dashboard')
    
    # Get approvals where current user is the approver
    approvals = LeaveApproval.objects.filter(
        approver=staff,
        status='PENDING',
        is_current=True
    ).select_related('leave_request', 'leave_request__staff', 'leave_request__leave_type').order_by('-leave_request__request_date')
    
    # For HR admin, also show approvals without specific approver
    if is_hr_admin(request.user):
        hr_approvals = LeaveApproval.objects.filter(
            approver__isnull=True,
            approver_role='HR_ADMIN',
            status='PENDING',
            is_current=True
        ).select_related('leave_request', 'leave_request__staff', 'leave_request__leave_type').order_by('-leave_request__request_date')
        
        # Combine querysets
        from itertools import chain
        approvals = list(chain(approvals, hr_approvals))
    
    context = {
        'approvals': approvals,
        'staff': staff,
    }
    return render(request, 'leave/pending_approvals.html', context)


@login_required
def approval_review(request, approval_pk):
    """Review and approve/reject leave request"""
    approval = get_object_or_404(LeaveApproval, pk=approval_pk)
    leave_request = approval.leave_request
    
    # Check permission
    try:
        staff = request.user.staff_profile
        can_approve = (
            approval.approver == staff or
            (approval.approver is None and is_hr_admin(request.user))
        )
        
        if not can_approve:
            messages.error(request, "You don't have permission to review this request.")
            return redirect('leave:pending_approvals')
    except:
        messages.error(request, "Staff profile not found.")
        return redirect('leave:dashboard')
    
    if request.method == 'POST':
        form = LeaveApprovalForm(request.POST, instance=approval)
        if form.is_valid():
            action = form.cleaned_data['action']
            approval.status = action
            approval.decision_date = timezone.now()
            approval.is_current = False
            approval.save()
            
            if action == 'APPROVED':
                # Move to next approval level or mark as approved
                next_approval = LeaveApproval.objects.filter(
                    leave_request=leave_request,
                    level__gt=approval.level,
                    status='PENDING'
                ).order_by('level').first()
                
                if next_approval:
                    next_approval.is_current = True
                    next_approval.save()
                    messages.success(request, f'Request approved. Forwarded to {next_approval.approver_role}.')
                else:
                    # Final approval
                    leave_request.status = 'APPROVED'
                    leave_request.save()
                    
                    # Update balance (move from pending to taken when leave starts)
                    update_balance_pending(leave_request, 'remove')
                    
                    messages.success(request, 'Leave request fully approved!')
            else:
                # Rejected
                leave_request.status = 'REJECTED'
                leave_request.can_appeal = True
                leave_request.appeal_deadline = timezone.now().date() + timedelta(days=3)
                leave_request.save()
                
                # Update balance pending
                update_balance_pending(leave_request, 'remove')
                
                messages.success(request, 'Leave request rejected. Staff can appeal within 3 days.')
            
            return redirect('leave:pending_approvals')
    else:
        form = LeaveApprovalForm(instance=approval)
    
    context = {
        'form': form,
        'approval': approval,
        'leave_request': leave_request,
    }
    return render(request, 'leave/approval_review.html', context)


# ============================================================================
# HR ADMIN VIEWS
# ============================================================================

@user_passes_test(is_hr_admin)
def hr_leave_requests(request):
    """HR view of all leave requests"""
    status_filter = request.GET.get('status', '')
    leave_type_filter = request.GET.get('leave_type', '')
    search = request.GET.get('search', '')
    
    requests = LeaveRequest.objects.all().select_related('staff', 'leave_type')
    
    if status_filter:
        requests = requests.filter(status=status_filter)
    if leave_type_filter:
        requests = requests.filter(leave_type_id=leave_type_filter)
    if search:
        requests = requests.filter(
            Q(request_number__icontains=search) |
            Q(staff__full_name__icontains=search) |
            Q(staff__staff_no__icontains=search)
        )
    
    requests = requests.order_by('-request_date')
    
    # Statistics
    stats = {
        'total': LeaveRequest.objects.count(),
        'pending': LeaveRequest.objects.filter(status='PENDING').count(),
        'approved': LeaveRequest.objects.filter(status='APPROVED').count(),
        'rejected': LeaveRequest.objects.filter(status='REJECTED').count(),
    }
    
    context = {
        'requests': requests,
        'stats': stats,
        'status_choices': LeaveRequest.STATUS_CHOICES,
        'leave_types': LeaveType.objects.filter(is_active=True),
        'status_filter': status_filter,
        'leave_type_filter': leave_type_filter,
        'search': search,
    }
    return render(request, 'leave/hr_requests_list.html', context)


@user_passes_test(is_hr_admin)
def hr_leave_balances(request):
    """HR view of all staff leave balances"""
    current_year = timezone.now().year
    campus_filter = request.GET.get('campus', '')
    leave_type_filter = request.GET.get('leave_type', '')
    search = request.GET.get('search', '')
    
    balances = LeaveBalance.objects.filter(year=current_year).select_related('staff', 'leave_type', 'staff__campus')
    
    if campus_filter:
        balances = balances.filter(staff__campus_id=campus_filter)
    if leave_type_filter:
        balances = balances.filter(leave_type_id=leave_type_filter)
    if search:
        balances = balances.filter(
            Q(staff__full_name__icontains=search) |
            Q(staff__staff_no__icontains=search)
        )
    
    balances = balances.order_by('staff__full_name', 'leave_type')
    
    context = {
        'balances': balances,
        'current_year': current_year,
        'leave_types': LeaveType.objects.filter(is_active=True),
    }
    return render(request, 'leave/hr_balances_list.html', context)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_appeal_approval(leave_request):
    """Create appeal approval record for next higher authority"""
    # Find the rejection
    rejection = leave_request.approvals.filter(status='REJECTED').first()
    
    if rejection:
        # Get next level approver
        if rejection.approver_role == 'SUPERVISOR':
            # Appeal to Director
            director = leave_request.staff.org_unit.managed_by.first() if hasattr(leave_request.staff.org_unit, 'managed_by') else None
            approver = director
            role = 'DIRECTOR'
        elif rejection.approver_role == 'DIRECTOR':
            # Appeal to DVC if exists
            approver = rejection.approver.supervisor if rejection.approver else None
            role = 'DVC' if approver else 'HR_ADMIN'
        else:
            # Appeal to HR
            approver = None
            role = 'HR_ADMIN'
        
        LeaveApproval.objects.create(
            leave_request=leave_request,
            level=rejection.level + 0.5,  # Insert between levels
            approver_role=role,
            approver=approver,
            status='PENDING',
            is_current=True,
            is_appeal_review=True
        )


