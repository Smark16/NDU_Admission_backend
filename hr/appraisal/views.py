"""
Views for Performance Appraisal module.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db.models import Q, Count, Avg
from django.utils import timezone
from django.http import HttpResponse
from datetime import datetime

from .models import (
    AppraisalCycle,
    StrategicObjective,
    DepartmentalObjective,
    Appraisal,
    AppraisalObjective,
    BehavioralCompetency,
    PerformanceFactor,
    DevelopmentObjective,
    PerformanceImprovementPlan,
    MidYearReview,
)
from hr.staff.models import StaffProfile
from accounts.models import Campus


# Permission helpers
def is_hr_admin(user):
    """Check if user is HR admin or superuser."""
    return user.is_superuser or getattr(user, 'user_type', '') == 'HR_ADMIN'


def is_manager(user):
    """Check if user is a manager."""
    try:
        return user.staff_profile.is_manager
    except:
        return False


# ==================== DASHBOARD ====================

@login_required
def appraisal_dashboard(request):
    """
    Main appraisal dashboard showing different views based on user role.
    """
    context = {}
    user = request.user
    
    try:
        staff_profile = user.staff_profile
    except:
        messages.warning(request, 'No staff profile linked to your account.')
        return redirect('staff:my_profile')
    
    # Get active cycle
    try:
        active_cycle = AppraisalCycle.objects.filter(
            campus=staff_profile.campus,
            is_active=True
        ).first()
        context['active_cycle'] = active_cycle
    except:
        active_cycle = None
    
    # Staff view - My appraisals
    my_appraisals = Appraisal.objects.filter(staff=staff_profile).order_by('-cycle__academic_year')
    context['my_appraisals'] = my_appraisals[:5]
    context['my_appraisals_count'] = my_appraisals.count()
    
    # Current appraisal
    if active_cycle:
        current_appraisal = my_appraisals.filter(cycle=active_cycle).first()
        context['current_appraisal'] = current_appraisal
    
    # Manager view - Team appraisals
    if staff_profile.is_manager:
        # Get appraisals for direct reports and staff in managed units
        team_appraisals = Appraisal.objects.filter(supervisor=staff_profile)
        
        # Include staff from managed org units
        if staff_profile.managed_org_units.exists():
            managed_units = []
            for unit in staff_profile.managed_org_units.all():
                managed_units.append(unit)
                managed_units.extend(unit.get_all_descendants())
            
            # Use Q objects to combine conditions
            team_appraisals = Appraisal.objects.filter(
                Q(supervisor=staff_profile) | Q(staff__org_unit__in=managed_units)
            ).distinct()
        
        context['team_appraisals_count'] = team_appraisals.count()
        context['team_pending_review'] = team_appraisals.filter(
            status='SELF_COMPLETED'
        ).count()
    
    # HR Admin view - All appraisals
    if is_hr_admin(user):
        all_appraisals = Appraisal.objects.filter(
            cycle__campus=staff_profile.campus
        )
        context['all_appraisals_count'] = all_appraisals.count()
        context['pending_hr_review'] = all_appraisals.filter(
            status='SUPERVISOR_REVIEW'
        ).count()
        context['completed_count'] = all_appraisals.filter(
            status__in=['APPROVED', 'PUBLISHED', 'ACKNOWLEDGED']
        ).count()
    
    return render(request, 'appraisal/dashboard.html', context)


# ==================== MY APPRAISALS (STAFF) ====================

@login_required
def my_appraisals_list(request):
    """List all appraisals for the logged-in staff member."""
    try:
        staff_profile = request.user.staff_profile
    except:
        messages.error(request, 'No staff profile found.')
        return redirect('staff:my_profile')
    
    appraisals = Appraisal.objects.filter(
        staff=staff_profile
    ).order_by('-cycle__academic_year')
    
    context = {
        'appraisals': appraisals,
    }
    return render(request, 'appraisal/my_appraisals_list.html', context)


@login_required
def my_appraisal_detail(request, pk):
    """View details of a specific appraisal."""
    try:
        staff_profile = request.user.staff_profile
    except:
        messages.error(request, 'No staff profile found.')
        return redirect('staff:my_profile')
    
    appraisal = get_object_or_404(Appraisal, pk=pk, staff=staff_profile)
    
    context = {
        'appraisal': appraisal,
        'objectives': appraisal.objectives.all(),
        'behavioral_competencies': appraisal.behavioral_competencies.all(),
        'performance_factors': appraisal.performance_factors.all(),
        'development_objectives': appraisal.development_objectives.all(),
    }
    return render(request, 'appraisal/my_appraisal_detail.html', context)


@login_required
def self_assessment_form(request, pk):
    """
    Self-assessment form for staff to complete their appraisal.
    """
    try:
        staff_profile = request.user.staff_profile
    except:
        messages.error(request, 'No staff profile found.')
        return redirect('staff:my_profile')
    
    appraisal = get_object_or_404(Appraisal, pk=pk, staff=staff_profile)
    
    # Check if allowed to edit
    if appraisal.status not in ['DRAFT', 'OBJECTIVES_SET', 'SELF_ASSESSMENT']:
        messages.warning(request, 'This appraisal is no longer editable.')
        return redirect('appraisal:my_appraisal_detail', pk=pk)
    
    if request.method == 'POST':
        # Save objectives self-assessment
        for objective in appraisal.objectives.all():
            obj_id = str(objective.id)
            score = request.POST.get(f'obj_score_{obj_id}')
            achievements = request.POST.get(f'obj_achievements_{obj_id}', '')
            
            if score:
                objective.individual_score_percentage = float(score)
            objective.achievements = achievements
            objective.save()
        
        # Save behavioral competencies self-assessment
        for comp in appraisal.behavioral_competencies.all():
            comp_id = str(comp.id)
            rating = request.POST.get(f'comp_self_{comp_id}')
            if rating:
                comp.self_assessment = int(rating)
                comp.save()
        
        # Save performance factors self-assessment
        for factor in appraisal.performance_factors.all():
            factor_id = str(factor.id)
            rating = request.POST.get(f'factor_self_{factor_id}')
            if rating:
                factor.self_assessment = int(rating)
                factor.save()
        
        # Update appraisal status
        action = request.POST.get('action')
        if action == 'submit':
            appraisal.status = 'SELF_COMPLETED'
            appraisal.self_completed_at = timezone.now()
            messages.success(request, 'Self-assessment submitted successfully!')
        else:
            appraisal.status = 'SELF_ASSESSMENT'
            messages.success(request, 'Draft saved successfully!')
        
        appraisal.save()
        return redirect('appraisal:my_appraisal_detail', pk=pk)
    
    context = {
        'appraisal': appraisal,
        'objectives': appraisal.objectives.all(),
        'behavioral_competencies': appraisal.behavioral_competencies.all(),
        'performance_factors': appraisal.performance_factors.all(),
    }
    return render(request, 'appraisal/self_assessment_form.html', context)


@login_required
def acknowledge_appraisal(request, pk):
    """Staff acknowledges their completed appraisal."""
    try:
        staff_profile = request.user.staff_profile
    except:
        messages.error(request, 'No staff profile found.')
        return redirect('staff:my_profile')
    
    appraisal = get_object_or_404(Appraisal, pk=pk, staff=staff_profile)
    
    if appraisal.status != 'PUBLISHED':
        messages.warning(request, 'This appraisal is not yet published.')
        return redirect('appraisal:my_appraisal_detail', pk=pk)
    
    if request.method == 'POST':
        comment = request.POST.get('acknowledgment_comment', '')
        appraisal.staff_acknowledgment_comment = comment
        appraisal.status = 'ACKNOWLEDGED'
        appraisal.acknowledged_at = timezone.now()
        appraisal.save()
        
        messages.success(request, 'Appraisal acknowledged successfully!')
        return redirect('appraisal:my_appraisal_detail', pk=pk)
    
    return render(request, 'appraisal/acknowledge_form.html', {'appraisal': appraisal})


# ==================== TEAM APPRAISALS (SUPERVISOR) ====================

@login_required
@user_passes_test(is_manager)
def team_appraisals_list(request):
    """List appraisals for team members under this supervisor."""
    try:
        staff_profile = request.user.staff_profile
    except:
        messages.error(request, 'No staff profile found.')
        return redirect('staff:my_profile')
    
    # Get appraisals for:
    # 1. Direct reports (where manager is set as supervisor)
    # 2. Staff in managed org units (and their descendants)
    
    # Start with direct reports
    appraisals = Appraisal.objects.filter(
        supervisor=staff_profile
    )
    
    # If manager has managed org units, also include staff from those units
    if staff_profile.managed_org_units.exists():
        managed_units = []
        for unit in staff_profile.managed_org_units.all():
            managed_units.append(unit)
            # Include all sub-units (descendants)
            managed_units.extend(unit.get_all_descendants())
        
        # Add appraisals from staff in managed units using OR query
        appraisals = Appraisal.objects.filter(
            Q(supervisor=staff_profile) | Q(staff__org_unit__in=managed_units)
        ).distinct()
    
    appraisals = appraisals.order_by('-cycle__academic_year', 'staff__full_name')
    
    # Filter by status if requested
    status_filter = request.GET.get('status')
    if status_filter:
        appraisals = appraisals.filter(status=status_filter)
    
    context = {
        'appraisals': appraisals,
        'pending_count': appraisals.filter(status='SELF_COMPLETED').count(),
    }
    return render(request, 'appraisal/team_appraisals_list.html', context)


@login_required
@user_passes_test(is_manager)
def team_appraisal_detail(request, pk):
    """View details of a team member's appraisal."""
    try:
        staff_profile = request.user.staff_profile
    except:
        messages.error(request, 'No staff profile found.')
        return redirect('staff:my_profile')
    
    appraisal = get_object_or_404(
        Appraisal,
        pk=pk,
        supervisor=staff_profile
    )
    
    context = {
        'appraisal': appraisal,
        'objectives': appraisal.objectives.all(),
        'behavioral_competencies': appraisal.behavioral_competencies.all(),
        'performance_factors': appraisal.performance_factors.all(),
    }
    return render(request, 'appraisal/team_appraisal_detail.html', context)


@login_required
@user_passes_test(is_manager)
def supervisor_review_form(request, pk):
    """
    Supervisor review form to assess team member's appraisal.
    """
    try:
        staff_profile = request.user.staff_profile
    except:
        messages.error(request, 'No staff profile found.')
        return redirect('staff:my_profile')
    
    appraisal = get_object_or_404(
        Appraisal,
        pk=pk,
        supervisor=staff_profile
    )
    
    if appraisal.status not in ['SELF_COMPLETED', 'SUPERVISOR_REVIEW']:
        messages.warning(request, 'This appraisal is not ready for supervisor review.')
        return redirect('appraisal:team_appraisal_detail', pk=pk)
    
    if request.method == 'POST':
        # Save objectives supervisor assessment
        for objective in appraisal.objectives.all():
            obj_id = str(objective.id)
            comments = request.POST.get(f'obj_comments_{obj_id}', '')
            agreed_score = request.POST.get(f'obj_agreed_{obj_id}')
            action = request.POST.get(f'obj_action_{obj_id}', '')
            
            objective.supervisor_comments = comments
            if agreed_score:
                objective.agreed_score = float(agreed_score)
            objective.action_required = action
            objective.save()
        
        # Save behavioral competencies supervisor assessment
        for comp in appraisal.behavioral_competencies.all():
            comp_id = str(comp.id)
            sup_rating = request.POST.get(f'comp_sup_{comp_id}')
            agreed_rating = request.POST.get(f'comp_agreed_{comp_id}')
            
            if sup_rating:
                comp.supervisor_assessment = int(sup_rating)
            if agreed_rating:
                comp.agreed_assessment = int(agreed_rating)
            comp.save()
        
        # Save performance factors supervisor assessment
        for factor in appraisal.performance_factors.all():
            factor_id = str(factor.id)
            sup_rating = request.POST.get(f'factor_sup_{factor_id}')
            agreed_rating = request.POST.get(f'factor_agreed_{factor_id}')
            
            if sup_rating:
                factor.supervisor_assessment = int(sup_rating)
            if agreed_rating:
                factor.agreed_assessment = int(agreed_rating)
            factor.save()
        
        # Save overall comments
        overall_comment = request.POST.get('overall_comment', '')
        appraisal.supervisor_overall_comment = overall_comment
        
        # Calculate scores
        appraisal.calculate_scores()
        
        # Update status
        action = request.POST.get('action')
        if action == 'submit':
            appraisal.status = 'HR_REVIEW'
            appraisal.supervisor_completed_at = timezone.now()
            messages.success(request, 'Supervisor review submitted successfully!')
        else:
            appraisal.status = 'SUPERVISOR_REVIEW'
            messages.success(request, 'Draft saved successfully!')
        
        appraisal.save()
        return redirect('appraisal:team_appraisal_detail', pk=pk)
    
    context = {
        'appraisal': appraisal,
        'objectives': appraisal.objectives.all(),
        'behavioral_competencies': appraisal.behavioral_competencies.all(),
        'performance_factors': appraisal.performance_factors.all(),
    }
    return render(request, 'appraisal/supervisor_review_form.html', context)


# ==================== HR ADMIN - APPRAISAL MANAGEMENT ====================

@login_required
@user_passes_test(is_hr_admin)
def appraisal_manage_list(request):
    """HR Admin view of all appraisals."""
    # Handle users without staff profile
    try:
        staff_profile = request.user.staff_profile
        campus = staff_profile.campus
    except:
        # If superuser without staff profile, show all campuses
        if request.user.is_superuser:
            campus = Campus.objects.first()
        else:
            messages.error(request, 'No staff profile linked to your account.')
            return redirect('staff:my_profile')
    
    if campus:
        appraisals = Appraisal.objects.filter(
            cycle__campus=campus
        ).order_by('-cycle__academic_year', 'staff__full_name')
        cycles = AppraisalCycle.objects.filter(campus=campus)
    else:
        appraisals = Appraisal.objects.all().order_by('-cycle__academic_year', 'staff__full_name')
        cycles = AppraisalCycle.objects.all()
    
    # Filters
    status_filter = request.GET.get('status')
    cycle_filter = request.GET.get('cycle')
    
    if status_filter:
        appraisals = appraisals.filter(status=status_filter)
    if cycle_filter:
        appraisals = appraisals.filter(cycle_id=cycle_filter)
    
    context = {
        'appraisals': appraisals,
        'cycles': cycles,
        'pending_approval': appraisals.filter(status='HR_REVIEW').count(),
    }
    return render(request, 'appraisal/manage_list.html', context)


@login_required
@user_passes_test(is_hr_admin)
def appraisal_manage_detail(request, pk):
    """HR Admin detail view of an appraisal."""
    appraisal = get_object_or_404(Appraisal, pk=pk)
    
    context = {
        'appraisal': appraisal,
        'objectives': appraisal.objectives.all(),
        'behavioral_competencies': appraisal.behavioral_competencies.all(),
        'performance_factors': appraisal.performance_factors.all(),
        'development_objectives': appraisal.development_objectives.all(),
    }
    return render(request, 'appraisal/manage_detail.html', context)


@login_required
@user_passes_test(is_hr_admin)
def hr_approve_appraisal(request, pk):
    """HR Admin approves an appraisal."""
    appraisal = get_object_or_404(Appraisal, pk=pk)
    
    if request.method == 'POST':
        hr_comments = request.POST.get('hr_comments', '')
        appraisal.hr_comments = hr_comments
        appraisal.status = 'APPROVED'
        appraisal.hr_approved_at = timezone.now()
        appraisal.save()
        
        messages.success(request, f'Appraisal for {appraisal.staff.full_name} approved!')
        return redirect('appraisal:manage_detail', pk=pk)
    
    return render(request, 'appraisal/hr_approve_form.html', {'appraisal': appraisal})


@login_required
@user_passes_test(is_hr_admin)
def hr_publish_appraisal(request, pk):
    """HR Admin publishes an approved appraisal to staff."""
    appraisal = get_object_or_404(Appraisal, pk=pk)
    
    if appraisal.status != 'APPROVED':
        messages.warning(request, 'Appraisal must be approved before publishing.')
        return redirect('appraisal:manage_detail', pk=pk)
    
    appraisal.status = 'PUBLISHED'
    appraisal.published_at = timezone.now()
    appraisal.save()
    
    messages.success(request, f'Appraisal published to {appraisal.staff.full_name}!')
    return redirect('appraisal:manage_detail', pk=pk)


# ==================== CYCLES MANAGEMENT ====================

@login_required
@user_passes_test(is_hr_admin)
def cycle_list(request):
    """List all appraisal cycles."""
    try:
        staff_profile = request.user.staff_profile
        cycles = AppraisalCycle.objects.filter(campus=staff_profile.campus)
    except:
        # Superuser without staff profile - show all cycles
        cycles = AppraisalCycle.objects.all()
    
    context = {'cycles': cycles}
    return render(request, 'appraisal/cycle_list.html', context)


@login_required
@user_passes_test(is_hr_admin)
def cycle_create(request):
    """Create a new appraisal cycle."""
    # Get campus
    try:
        campus = request.user.staff_profile.campus
    except:
        # Superuser - use first campus or show error
        campus = Campus.objects.first()
        if not campus:
            messages.error(request, 'No campus available. Please create a campus first.')
            return redirect('staff:campus_list')
    
    if request.method == 'POST':
        # Simple form processing
        academic_year = request.POST.get('academic_year')
        period_from = request.POST.get('period_from')
        period_to = request.POST.get('period_to')
        review_window_from = request.POST.get('review_window_from')
        review_window_to = request.POST.get('review_window_to')
        
        cycle = AppraisalCycle.objects.create(
            campus=campus,
            academic_year=academic_year,
            period_from=period_from,
            period_to=period_to,
            review_window_from=review_window_from,
            review_window_to=review_window_to,
            status='PLANNING'
        )
        
        messages.success(request, f'Appraisal cycle {academic_year} created!')
        return redirect('appraisal:cycle_detail', pk=cycle.pk)
    
    return render(request, 'appraisal/cycle_form.html', {'action': 'Create'})


@login_required
@user_passes_test(is_hr_admin)
def cycle_detail(request, pk):
    """View cycle details."""
    cycle = get_object_or_404(AppraisalCycle, pk=pk)
    appraisals = cycle.appraisals.all()
    
    context = {
        'cycle': cycle,
        'appraisals_count': appraisals.count(),
        'completed_count': appraisals.filter(status='ACKNOWLEDGED').count(),
    }
    return render(request, 'appraisal/cycle_detail.html', context)


@login_required
@user_passes_test(is_hr_admin)
def cycle_edit(request, pk):
    """Edit a cycle."""
    cycle = get_object_or_404(AppraisalCycle, pk=pk)
    
    if request.method == 'POST':
        cycle.academic_year = request.POST.get('academic_year')
        cycle.period_from = request.POST.get('period_from')
        cycle.period_to = request.POST.get('period_to')
        cycle.review_window_from = request.POST.get('review_window_from')
        cycle.review_window_to = request.POST.get('review_window_to')
        cycle.status = request.POST.get('status')
        cycle.save()
        
        messages.success(request, 'Cycle updated!')
        return redirect('appraisal:cycle_detail', pk=pk)
    
    return render(request, 'appraisal/cycle_form.html', {'cycle': cycle, 'action': 'Edit'})


@login_required
@user_passes_test(is_hr_admin)
def cycle_activate(request, pk):
    """Activate a cycle (deactivate others)."""
    cycle = get_object_or_404(AppraisalCycle, pk=pk)
    
    # Deactivate other cycles
    AppraisalCycle.objects.filter(campus=cycle.campus).update(is_active=False)
    
    # Activate this cycle
    cycle.is_active = True
    cycle.status = 'ACTIVE'
    cycle.save()
    
    messages.success(request, f'Cycle {cycle.academic_year} activated!')
    return redirect('appraisal:cycle_detail', pk=pk)


# ==================== STRATEGIC OBJECTIVES ====================

@login_required
@user_passes_test(is_hr_admin)
def strategic_objectives_list(request):
    """List all strategic objectives."""
    objectives = StrategicObjective.objects.all()
    return render(request, 'appraisal/strategic_objectives_list.html', {'objectives': objectives})


@login_required
@user_passes_test(is_hr_admin)
def strategic_objective_create(request):
    """Create a strategic objective."""
    if request.method == 'POST':
        code = request.POST.get('code')
        title = request.POST.get('title')
        description = request.POST.get('description', '')
        
        StrategicObjective.objects.create(
            code=code,
            title=title,
            description=description
        )
        
        messages.success(request, f'Strategic objective {code} created!')
        return redirect('appraisal:strategic_objectives')
    
    return render(request, 'appraisal/strategic_objective_form.html', {'action': 'Create'})


@login_required
@user_passes_test(is_hr_admin)
def strategic_objective_edit(request, pk):
    """Edit a strategic objective."""
    objective = get_object_or_404(StrategicObjective, pk=pk)
    
    if request.method == 'POST':
        objective.code = request.POST.get('code')
        objective.title = request.POST.get('title')
        objective.description = request.POST.get('description', '')
        objective.is_active = request.POST.get('is_active') == 'on'
        objective.save()
        
        messages.success(request, 'Strategic objective updated!')
        return redirect('appraisal:strategic_objectives')
    
    return render(request, 'appraisal/strategic_objective_form.html', {
        'objective': objective,
        'action': 'Edit'
    })


# ==================== REPORTS ====================

@login_required
@user_passes_test(is_hr_admin)
def appraisal_reports(request):
    """Analytics and reports dashboard."""
    try:
        staff_profile = request.user.staff_profile
        # Get all appraisals for campus
        appraisals = Appraisal.objects.filter(cycle__campus=staff_profile.campus)
    except:
        # Superuser without staff profile - show all appraisals
        appraisals = Appraisal.objects.all()
    
    # Statistics
    total_appraisals = appraisals.count()
    completed = appraisals.filter(status='ACKNOWLEDGED').count()
    avg_score = appraisals.filter(overall_score__isnull=False).aggregate(
        Avg('overall_score')
    )['overall_score__avg']
    
    # Rating distribution
    rating_distribution = {
        'exceptional': appraisals.filter(overall_rating='EXCEPTIONAL').count(),
        'excellent': appraisals.filter(overall_rating='EXCELLENT').count(),
        'satisfactory': appraisals.filter(overall_rating='SATISFACTORY').count(),
        'unsatisfactory': appraisals.filter(overall_rating='UNSATISFACTORY').count(),
    }
    
    context = {
        'total_appraisals': total_appraisals,
        'completed': completed,
        'avg_score': round(avg_score, 2) if avg_score else 0,
        'rating_distribution': rating_distribution,
    }
    return render(request, 'appraisal/reports.html', context)


@login_required
@user_passes_test(is_hr_admin)
def export_appraisals(request, cycle_id):
    """Export appraisals to CSV."""
    # Simple CSV export placeholder
    messages.info(request, 'Export feature coming soon!')
    return redirect('appraisal:reports')


# ==================== PIP MANAGEMENT ====================

@login_required
@user_passes_test(is_hr_admin)
def pip_list(request):
    """List all Performance Improvement Plans."""
    pips = PerformanceImprovementPlan.objects.all().order_by('-start_date')
    return render(request, 'appraisal/pip_list.html', {'pips': pips})


@login_required
@user_passes_test(is_hr_admin)
def pip_detail(request, pk):
    """View PIP details."""
    pip = get_object_or_404(PerformanceImprovementPlan, pk=pk)
    return render(request, 'appraisal/pip_detail.html', {'pip': pip})


@login_required
@user_passes_test(is_hr_admin)
def pip_create(request, appraisal_id):
    """Create a PIP for an appraisal."""
    appraisal = get_object_or_404(Appraisal, pk=appraisal_id)
    
    if request.method == 'POST':
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        improvement_areas = request.POST.get('improvement_areas')
        improvement_targets = request.POST.get('improvement_targets')
        
        PerformanceImprovementPlan.objects.create(
            appraisal=appraisal,
            start_date=start_date,
            end_date=end_date,
            improvement_areas=improvement_areas,
            improvement_targets=improvement_targets,
            status='ACTIVE'
        )
        
        messages.success(request, f'PIP created for {appraisal.staff.full_name}!')
        return redirect('appraisal:pip_list')
    
    return render(request, 'appraisal/pip_form.html', {'appraisal': appraisal})


# ==================== OBJECTIVE SETTING (SUPERVISOR) ====================

@login_required
@user_passes_test(is_manager)
def set_objectives_form(request, pk):
    """
    Supervisor sets objectives for team member at the start of the appraisal cycle.
    This is the FIRST step in the collaborative approach.
    """
    try:
        staff_profile = request.user.staff_profile
    except:
        messages.error(request, 'No staff profile found.')
        return redirect('staff:my_profile')
    
    appraisal = get_object_or_404(
        Appraisal,
        pk=pk,
        supervisor=staff_profile
    )
    
    # Only allow setting objectives if status is DRAFT
    if appraisal.status not in ['DRAFT', 'OBJECTIVES_SET']:
        messages.warning(request, 'Objectives can only be set when appraisal is in Draft status.')
        return redirect('appraisal:team_appraisal_detail', pk=pk)
    
    # Get all strategic objectives for dropdown
    strategic_objectives = StrategicObjective.objects.filter(is_active=True)
    
    if request.method == 'POST':
        # Save existing objectives
        for objective in appraisal.objectives.all():
            obj_id = str(objective.id)
            
            # Check if this objective should be deleted
            if request.POST.get(f'delete_obj_{obj_id}') == 'yes':
                objective.delete()
                continue
            
            # Update objective fields
            strategic_obj_id = request.POST.get(f'obj_strategic_{obj_id}')
            if strategic_obj_id:
                objective.strategic_objective_id = strategic_obj_id
            
            objective.individual_objective = request.POST.get(f'obj_title_{obj_id}', '')
            objective.indicative_tasks = request.POST.get(f'obj_tasks_{obj_id}', '')
            objective.target_percentage = float(request.POST.get(f'obj_target_{obj_id}', 95))
            objective.baseline_percentage = float(request.POST.get(f'obj_baseline_{obj_id}', 80))
            objective.weight = float(request.POST.get(f'obj_weight_{obj_id}', 5))
            objective.save()
        
        # Add new objectives
        new_obj_count = int(request.POST.get('new_obj_count', 0))
        for i in range(new_obj_count):
            strategic_obj_id = request.POST.get(f'new_obj_strategic_{i}')
            title = request.POST.get(f'new_obj_title_{i}', '').strip()
            
            if title and strategic_obj_id:  # Only create if both are provided
                AppraisalObjective.objects.create(
                    appraisal=appraisal,
                    strategic_objective_id=strategic_obj_id,
                    individual_objective=title,
                    indicative_tasks=request.POST.get(f'new_obj_tasks_{i}', ''),
                    target_percentage=float(request.POST.get(f'new_obj_target_{i}', 95)),
                    baseline_percentage=float(request.POST.get(f'new_obj_baseline_{i}', 80)),
                    weight=float(request.POST.get(f'new_obj_weight_{i}', 5)),
                )
        
        # Update appraisal status
        action = request.POST.get('action')
        if action == 'finalize':
            appraisal.status = 'OBJECTIVES_SET'
            appraisal.save()
            messages.success(request, f'Objectives finalized for {appraisal.staff.full_name}. Staff can now view and accept them.')
            return redirect('appraisal:team_appraisals')
        else:
            messages.success(request, 'Objectives saved as draft.')
    
    context = {
        'appraisal': appraisal,
        'objectives': appraisal.objectives.all(),
        'strategic_objectives': strategic_objectives,
    }
    return render(request, 'appraisal/set_objectives_form.html', context)


# ==================== VIEW OBJECTIVES (STAFF) ====================

@login_required
def view_objectives(request, pk):
    """
    Staff member views objectives set by their supervisor.
    They can add comments/questions before accepting.
    """
    try:
        staff_profile = request.user.staff_profile
    except:
        messages.error(request, 'No staff profile found.')
        return redirect('staff:my_profile')
    
    appraisal = get_object_or_404(Appraisal, pk=pk, staff=staff_profile)
    
    # Only allow viewing if objectives have been set
    if appraisal.status not in ['OBJECTIVES_SET', 'SELF_ASSESSMENT', 'SELF_COMPLETED', 
                                 'SUPERVISOR_REVIEW', 'HR_REVIEW', 'APPROVED', 'PUBLISHED', 'ACKNOWLEDGED']:
        messages.warning(request, 'Objectives have not been set yet by your supervisor.')
        return redirect('appraisal:my_appraisal_detail', pk=pk)
    
    if request.method == 'POST':
        # Staff can add comments to objectives
        for objective in appraisal.objectives.all():
            obj_id = str(objective.id)
            comment = request.POST.get(f'obj_comment_{obj_id}', '')
            if comment:
                # Store staff comment (we can add a field for this if needed)
                # For now, we'll just acknowledge acceptance
                pass
        
        # Staff accepts objectives
        action = request.POST.get('action')
        if action == 'accept':
            # Keep status as OBJECTIVES_SET - they can now proceed to self-assessment
            messages.success(request, 'You have acknowledged your objectives. You can now proceed to self-assessment when ready.')
            return redirect('appraisal:my_appraisal_detail', pk=pk)
    
    context = {
        'appraisal': appraisal,
        'objectives': appraisal.objectives.all(),
    }
    return render(request, 'appraisal/view_objectives.html', context)
