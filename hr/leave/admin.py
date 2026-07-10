"""
Leave Management Admin Interface
"""
from django.contrib import admin
from django.utils.html import format_html
from .models import (
    LeaveType,
    LeavePolicy,
    LeaveBalance,
    LeaveRequest,
    LeaveApproval,
    LeaveAccrual,
    PublicHoliday,
)


@admin.register(LeaveType)
class LeaveTypeAdmin(admin.ModelAdmin):
    list_display = [
        'name',
        'code',
        'max_days_per_year',
        'has_accrual',
        'carry_over_allowed',
        'color_badge',
        'is_active',
    ]
    list_filter = ['is_active', 'has_accrual', 'carry_over_allowed', 'gender_specific']
    search_fields = ['name', 'code', 'description']
    ordering = ['sort_order', 'name']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'code', 'description', 'sort_order')
        }),
        ('Policy Settings', {
            'fields': (
                'max_days_per_year',
                'requires_document',
                'is_paid',
                'gender_specific',
            )
        }),
        ('Accrual Settings', {
            'fields': (
                'has_accrual',
                'carry_over_allowed',
                'max_carry_over_days',
                'carry_over_expiry_months',
            )
        }),
        ('Display', {
            'fields': ('color', 'is_active')
        }),
    )
    
    def color_badge(self, obj):
        return format_html(
            '<span style="background-color: {}; padding: 5px 10px; color: white; border-radius: 3px;">{}</span>',
            obj.color,
            obj.code
        )
    color_badge.short_description = 'Color'


@admin.register(LeavePolicy)
class LeavePolicyAdmin(admin.ModelAdmin):
    list_display = [
        'leave_type',
        'campus',
        'position_category',
        'annual_entitlement_days',
        'accrual_method',
        'is_active',
    ]
    list_filter = ['campus', 'position_category', 'accrual_method', 'is_active']
    search_fields = ['leave_type__name']
    ordering = ['campus', 'leave_type']
    
    fieldsets = (
        ('Policy Details', {
            'fields': ('campus', 'leave_type', 'position_category')
        }),
        ('Entitlement', {
            'fields': ('annual_entitlement_days', 'accrual_method')
        }),
        ('Request Rules', {
            'fields': ('min_notice_days', 'max_consecutive_days')
        }),
        ('Validity', {
            'fields': ('effective_date', 'expiry_date', 'is_active')
        }),
    )


class LeaveApprovalInline(admin.TabularInline):
    model = LeaveApproval
    extra = 0
    readonly_fields = ['level', 'approver_role', 'approver', 'status', 'decision_date']
    can_delete = False
    
    def has_add_permission(self, request, obj=None):
        return False


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = [
        'request_number',
        'staff',
        'leave_type',
        'start_date',
        'end_date',
        'total_days',
        'status_badge',
        'request_date',
    ]
    list_filter = ['status', 'leave_type', 'staff__campus', 'start_date']
    search_fields = ['request_number', 'staff__full_name', 'reason']
    readonly_fields = ['request_number', 'request_date', 'can_appeal', 'appeal_deadline']
    ordering = ['-request_date']
    date_hierarchy = 'start_date'
    
    inlines = [LeaveApprovalInline]
    
    fieldsets = (
        ('Request Details', {
            'fields': (
                'request_number',
                'staff',
                'leave_type',
                'start_date',
                'end_date',
                'total_days',
            )
        }),
        ('Reason & Contact', {
            'fields': ('reason', 'contact_during_leave', 'attachment')
        }),
        ('Status', {
            'fields': ('status', 'request_date')
        }),
        ('Comments', {
            'fields': ('supervisor_comment', 'hr_comment'),
            'classes': ('collapse',)
        }),
        ('Appeal', {
            'fields': ('can_appeal', 'appeal_reason', 'appeal_date', 'appeal_deadline'),
            'classes': ('collapse',)
        }),
    )
    
    def status_badge(self, obj):
        colors = {
            'DRAFT': 'gray',
            'PENDING': 'orange',
            'APPROVED': 'green',
            'REJECTED': 'red',
            'UNDER_APPEAL': 'purple',
            'APPEAL_REJECTED': 'darkred',
            'CANCELLED': 'lightgray',
            'COMPLETED': 'blue',
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="background-color: {}; padding: 3px 8px; color: white; border-radius: 3px; font-size: 11px;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = 'Status'


@admin.register(LeaveBalance)
class LeaveBalanceAdmin(admin.ModelAdmin):
    list_display = [
        'staff',
        'leave_type',
        'year',
        'total_entitled',
        'earned_this_year',
        'taken',
        'pending',
        'available_display',
    ]
    list_filter = ['year', 'leave_type', 'staff__campus']
    search_fields = ['staff__full_name', 'staff__staff_no']
    ordering = ['-year', 'staff', 'leave_type']
    
    fieldsets = (
        ('Balance Details', {
            'fields': ('staff', 'leave_type', 'year')
        }),
        ('Entitlement', {
            'fields': ('total_entitled', 'carried_over', 'carried_expiry_date')
        }),
        ('Accrual', {
            'fields': ('earned_this_year',)
        }),
        ('Usage', {
            'fields': ('taken', 'pending', 'adjustments')
        }),
        ('Notes', {
            'fields': ('notes',),
            'classes': ('collapse',)
        }),
    )
    
    def available_display(self, obj):
        available = obj.available
        color = 'green' if available > 5 else 'orange' if available > 0 else 'red'
        return format_html(
            '<strong style="color: {};">{:.1f} days</strong>',
            color,
            available
        )
    available_display.short_description = 'Available'


@admin.register(LeaveAccrual)
class LeaveAccrualAdmin(admin.ModelAdmin):
    list_display = [
        'staff',
        'leave_type',
        'accrual_date',
        'days_accrued',
        'transaction_type',
    ]
    list_filter = ['transaction_type', 'leave_type', 'accrual_date']
    search_fields = ['staff__full_name', 'staff__staff_no']
    ordering = ['-accrual_date', 'staff']
    date_hierarchy = 'accrual_date'
    readonly_fields = ['accrual_date']


@admin.register(PublicHoliday)
class PublicHolidayAdmin(admin.ModelAdmin):
    list_display = ['name', 'date', 'campus', 'is_recurring', 'is_active']
    list_filter = ['is_recurring', 'is_active', 'campus', 'date']
    search_fields = ['name']
    ordering = ['date']
    date_hierarchy = 'date'
    
    fieldsets = (
        ('Holiday Details', {
            'fields': ('name', 'date', 'campus')
        }),
        ('Settings', {
            'fields': ('is_recurring', 'is_active')
        }),
    )
