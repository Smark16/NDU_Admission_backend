"""
Leave Management Models
Implements monthly accrual system with dynamic hierarchical approval workflow
"""
import uuid
from decimal import Decimal
from datetime import date, timedelta
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone

class LeaveType(models.Model):
    """
    Types of leave available (Annual, Sick, Maternity, etc.)
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=10, unique=True, help_text="Short code (e.g., ANN, SCK)")
    description = models.TextField(blank=True)
    
    # Policy settings
    max_days_per_year = models.IntegerField(
        default=21,
        help_text="Maximum days allowed per year"
    )
    requires_document = models.BooleanField(
        default=False,
        help_text="Requires supporting document (medical cert, etc.)"
    )
    is_paid = models.BooleanField(default=True)
    
    # Gender restrictions
    GENDER_CHOICES = [
        ('ALL', 'All Genders'),
        ('MALE', 'Male Only'),
        ('FEMALE', 'Female Only'),
    ]
    gender_specific = models.CharField(
        max_length=10,
        choices=GENDER_CHOICES,
        default='ALL'
    )
    
    # Accrual settings
    has_accrual = models.BooleanField(
        default=True,
        help_text="Whether this leave type accrues monthly"
    )
    carry_over_allowed = models.BooleanField(default=True)
    max_carry_over_days = models.IntegerField(
        default=10,
        help_text="Maximum days that can carry to next year"
    )
    carry_over_expiry_months = models.IntegerField(
        default=6,
        help_text="Months until carried leave expires"
    )
    
    # Display settings
    color = models.CharField(
        max_length=7,
        default='#3498db',
        help_text="Hex color for calendar display"
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['sort_order', 'name']
    
    def __str__(self):
        return f"{self.name} ({self.code})"


class LeavePolicy(models.Model):
    """
    Leave entitlement policies by campus/position
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    campus = models.ForeignKey(
        'accounts.Campus',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="Leave blank for global policy"
    )
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE)
    
    # Eligibility
    POSITION_CHOICES = [
        ('ALL', 'All Positions'),
        ('ACADEMIC', 'Academic Staff'),
        ('ADMINISTRATIVE', 'Administrative Staff'),
        ('SUPPORT', 'Support Staff'),
    ]
    position_category = models.CharField(
        max_length=20,
        choices=POSITION_CHOICES,
        default='ALL'
    )
    
    # Entitlement
    annual_entitlement_days = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=21.00,
        help_text="Days per year"
    )
    
    # Accrual method
    ACCRUAL_CHOICES = [
        ('MONTHLY', 'Monthly Accrual'),
        ('ANNUAL', 'Annual Lump Sum'),
        ('PRORATED', 'Pro-rated on Hire'),
    ]
    accrual_method = models.CharField(
        max_length=10,
        choices=ACCRUAL_CHOICES,
        default='MONTHLY'
    )
    
    # Request rules
    min_notice_days = models.IntegerField(
        default=3,
        help_text="Days advance notice required"
    )
    max_consecutive_days = models.IntegerField(
        default=30,
        help_text="Maximum consecutive days allowed"
    )
    
    effective_date = models.DateField(default=timezone.now)
    expiry_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['campus', 'leave_type']
        unique_together = ['campus', 'leave_type', 'position_category']
    
    def __str__(self):
        campus_str = self.campus.name if self.campus else "Global"
        return f"{self.leave_type.name} - {campus_str} - {self.position_category}"


class LeaveBalance(models.Model):
    """
    Leave balance per staff member per year
    Tracks accruals, taken, and available leave
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    staff = models.ForeignKey(
        'staff.StaffProfile',
        on_delete=models.CASCADE,
        related_name='leave_balances'
    )
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE)
    year = models.IntegerField()
    
    # Balance tracking
    total_entitled = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=0.00,
        help_text="Total days entitled for the year"
    )
    carried_over = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=0.00,
        help_text="Days carried from previous year"
    )
    carried_expiry_date = models.DateField(
        null=True,
        blank=True,
        help_text="When carried days expire"
    )
    earned_this_year = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=0.00,
        help_text="Days accrued so far this year"
    )
    adjustments = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=0.00,
        help_text="Manual HR adjustments (+/-)"
    )
    taken = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=0.00,
        help_text="Days already taken (approved leaves)"
    )
    pending = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=0.00,
        help_text="Days in pending requests"
    )
    
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-year', 'staff', 'leave_type']
        unique_together = ['staff', 'leave_type', 'year']
    
    def __str__(self):
        return f"{self.staff.full_name} - {self.leave_type.name} - {self.year}"
    
    @property
    def available(self):
        """Calculate available balance"""
        total = (
            Decimal(str(self.total_entitled)) +
            Decimal(str(self.carried_over)) +
            Decimal(str(self.earned_this_year)) +
            Decimal(str(self.adjustments))
        )
        used = Decimal(str(self.taken)) + Decimal(str(self.pending))
        return float(total - used)
    
    @property
    def monthly_accrual_rate(self):
        """Calculate monthly accrual rate"""
        if self.total_entitled > 0:
            return float(Decimal(str(self.total_entitled)) / 12)
        return 0.0


class LeaveRequest(models.Model):
    """
    Leave request submitted by staff
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    request_number = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        help_text="Auto-generated: LV-2026-0001"
    )
    
    staff = models.ForeignKey(
        'staff.StaffProfile',
        on_delete=models.CASCADE,
        related_name='leave_requests'
    )
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT)
    
    # Dates
    start_date = models.DateField()
    end_date = models.DateField()
    total_days = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        help_text="Calculated working days"
    )
    
    # Request details
    reason = models.TextField(help_text="Reason for leave request")
    contact_during_leave = models.CharField(
        max_length=200,
        blank=True,
        help_text="Phone/email for emergencies"
    )
    attachment = models.FileField(
        upload_to='leave/attachments/%Y/%m/',
        null=True,
        blank=True,
        help_text="Medical certificate, etc."
    )
    
    # Status tracking
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('PENDING', 'Pending Approval'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('UNDER_APPEAL', 'Under Appeal'),
        ('APPEAL_REJECTED', 'Appeal Rejected'),
        ('CANCELLED', 'Cancelled by Staff'),
        ('COMPLETED', 'Completed'),
    ]
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='DRAFT'
    )
    
    request_date = models.DateTimeField(auto_now_add=True)
    
    # Comments
    supervisor_comment = models.TextField(blank=True)
    hr_comment = models.TextField(blank=True)
    
    # Appeal functionality
    can_appeal = models.BooleanField(default=False)
    appeal_reason = models.TextField(blank=True)
    appeal_date = models.DateTimeField(null=True, blank=True)
    appeal_deadline = models.DateField(
        null=True,
        blank=True,
        help_text="Deadline to file appeal (3 days after rejection)"
    )
    
    class Meta:
        ordering = ['-request_date']
    
    def __str__(self):
        return f"{self.request_number} - {self.staff.get_full_name}"
    
    def save(self, *args, **kwargs):
        if not self.request_number:
            # Generate request number
            year = timezone.now().year
            last_request = LeaveRequest.objects.filter(
                request_number__startswith=f'LV-{year}-'
            ).order_by('-request_number').first()
            
            if last_request:
                last_num = int(last_request.request_number.split('-')[-1])
                new_num = last_num + 1
            else:
                new_num = 1
            
            self.request_number = f'LV-{year}-{new_num:04d}'
        
        super().save(*args, **kwargs)


class LeaveApproval(models.Model):
    """
    Approval workflow for leave requests
    Dynamic based on staff hierarchy
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    leave_request = models.ForeignKey(
        LeaveRequest,
        on_delete=models.CASCADE,
        related_name='approvals'
    )
    
    level = models.IntegerField(help_text="Approval sequence (1, 2, 3...)")
    
    ROLE_CHOICES = [
        ('SUPERVISOR', 'Supervisor/Team Leader'),
        ('DIRECTOR', 'Director/Head of Department'),
        ('DVC', 'Deputy Vice Chancellor'),
        ('HR_ADMIN', 'HR Administrator'),
    ]
    approver_role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    
    approver = models.ForeignKey(
        'staff.StaffProfile',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='leave_approvals',
        help_text="Specific person or null for any HR"
    )
    
    STATUS_CHOICES = [
        ('PENDING', 'Pending Review'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('SKIPPED', 'Skipped (No Supervisor)'),
    ]
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='PENDING'
    )
    
    decision_date = models.DateTimeField(null=True, blank=True)
    comments = models.TextField(blank=True)
    
    is_current = models.BooleanField(
        default=False,
        help_text="Is this the current pending level?"
    )
    is_appeal_review = models.BooleanField(
        default=False,
        help_text="Is this an appeal review?"
    )
    
    class Meta:
        ordering = ['leave_request', 'level']
        unique_together = ['leave_request', 'level']
    
    def __str__(self):
        return f"{self.leave_request.request_number} - Level {self.level} - {self.approver_role}"


class LeaveAccrual(models.Model):
    """
    History of leave accruals (monthly automatic entries)
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    staff = models.ForeignKey(
        'staff.StaffProfile',
        on_delete=models.CASCADE,
        related_name='leave_accruals'
    )
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE)
    
    accrual_date = models.DateField()
    days_accrued = models.DecimalField(max_digits=5, decimal_places=2)
    
    TRANSACTION_TYPES = [
        ('ANNUAL_GRANT', 'Annual Entitlement Grant'),
        ('MONTHLY_ACCRUAL', 'Monthly Accrual'),
        ('CARRY_FORWARD', 'Carry Forward from Previous Year'),
        ('ADJUSTMENT', 'Manual HR Adjustment'),
        ('ENCASHMENT', 'Leave Encashment'),
    ]
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-accrual_date', 'staff']
    
    def __str__(self):
        return f"{self.staff.full_name} - {self.days_accrued} days - {self.accrual_date}"


class PublicHoliday(models.Model):
    """
    Public holidays (non-working days)
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    name = models.CharField(max_length=200)
    date = models.DateField()
    
    campus = models.ForeignKey(
        'accounts.Campus',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="Leave blank for all campuses"
    )
    
    is_recurring = models.BooleanField(
        default=True,
        help_text="Repeats every year?"
    )
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['date']
    
    def __str__(self):
        return f"{self.name} - {self.date}"
