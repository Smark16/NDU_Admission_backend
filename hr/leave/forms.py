"""
Leave Management Forms
"""
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta
from .models import LeaveRequest, LeaveApproval, LeaveBalance


class LeaveRequestForm(forms.ModelForm):
    """
    Form for staff to submit leave requests
    """
    class Meta:
        model = LeaveRequest
        fields = [
            'leave_type',
            'start_date',
            'end_date',
            'reason',
            'contact_during_leave',
            'attachment',
        ]
        widgets = {
            'start_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control',
            }),
            'end_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control',
            }),
            'reason': forms.Textarea(attrs={
                'rows': 4,
                'class': 'form-control',
                'placeholder': 'Please provide reason for your leave request...'
            }),
            'contact_during_leave': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Phone number or email for emergencies'
            }),
            'leave_type': forms.Select(attrs={'class': 'form-select'}),
            'attachment': forms.FileInput(attrs={'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        self.staff = kwargs.pop('staff', None)
        super().__init__(*args, **kwargs)
        
        # Only show active leave types
        self.fields['leave_type'].queryset = self.fields['leave_type'].queryset.filter(
            is_active=True
        )
    
    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        leave_type = cleaned_data.get('leave_type')
        
        if start_date and end_date:
            # Validate date range
            if end_date < start_date:
                raise ValidationError("End date cannot be before start date.")
            
            # Check minimum notice
            if self.staff:
                today = timezone.now().date()
                days_until_leave = (start_date - today).days
                
                # Get policy for this leave type
                from .models import LeavePolicy
                policy = LeavePolicy.objects.filter(
                    leave_type=leave_type,
                    is_active=True
                ).first()
                
                if policy and days_until_leave < policy.min_notice_days:
                    raise ValidationError(
                        f"Minimum {policy.min_notice_days} days advance notice required for {leave_type.name}."
                    )
                
                # Calculate working days
                total_days = (end_date - start_date).days + 1
                
                # Check maximum consecutive days
                if policy and total_days > policy.max_consecutive_days:
                    raise ValidationError(
                        f"Maximum {policy.max_consecutive_days} consecutive days allowed for {leave_type.name}."
                    )
                
                # Check available balance
                try:
                    balance = LeaveBalance.objects.get(
                        staff=self.staff,
                        leave_type=leave_type,
                        year=start_date.year
                    )
                    
                    if balance.available < total_days:
                        raise ValidationError(
                            f"Insufficient leave balance. Available: {balance.available:.1f} days, Requested: {total_days} days."
                        )
                except LeaveBalance.DoesNotExist:
                    raise ValidationError(
                        f"No leave balance found for {leave_type.name} in {start_date.year}."
                    )
        
        return cleaned_data


class LeaveApprovalForm(forms.ModelForm):
    """
    Form for approvers to approve/reject leave requests
    """
    ACTION_CHOICES = [
        ('APPROVED', 'Approve'),
        ('REJECTED', 'Reject'),
    ]
    
    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        widget=forms.RadioSelect,
        required=True
    )
    
    class Meta:
        model = LeaveApproval
        fields = ['comments']
        widgets = {
            'comments': forms.Textarea(attrs={
                'rows': 3,
                'class': 'form-control',
                'placeholder': 'Add comments (optional for approval, required for rejection)...'
            }),
        }
    
    def clean(self):
        cleaned_data = super().clean()
        action = cleaned_data.get('action')
        comments = cleaned_data.get('comments')
        
        # Require comments for rejection
        if action == 'REJECTED' and not comments:
            raise ValidationError("Comments are required when rejecting a leave request.")
        
        return cleaned_data


class LeaveAppealForm(forms.Form):
    """
    Form for staff to appeal rejected leave requests
    """
    appeal_reason = forms.CharField(
        widget=forms.Textarea(attrs={
            'rows': 4,
            'class': 'form-control',
            'placeholder': 'Explain why you are appealing this rejection...'
        }),
        required=True,
        label='Appeal Reason'
    )
    
    def clean_appeal_reason(self):
        reason = self.cleaned_data.get('appeal_reason')
        if len(reason) < 20:
            raise ValidationError("Please provide a detailed reason (at least 20 characters).")
        return reason


class LeaveBalanceAdjustmentForm(forms.ModelForm):
    """
    Form for HR to manually adjust leave balances
    """
    adjustment_reason = forms.CharField(
        widget=forms.Textarea(attrs={
            'rows': 3,
            'class': 'form-control',
            'placeholder': 'Reason for adjustment...'
        }),
        required=True
    )
    
    class Meta:
        model = LeaveBalance
        fields = ['adjustments']
        widgets = {
            'adjustments': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.5',
                'placeholder': 'Enter positive or negative value'
            }),
        }
    
    def clean_adjustments(self):
        adjustment = self.cleaned_data.get('adjustments')
        if adjustment == 0:
            raise ValidationError("Adjustment cannot be zero.")
        return adjustment
