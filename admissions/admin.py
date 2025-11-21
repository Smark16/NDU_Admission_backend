from django.contrib import admin
from django.utils.html import format_html
from admissions.models import *
from payments.models import Payment, MobileMoneyTransaction
from audit.models import AuditLog, UserActivity

@admin.register(Faculty)
class FacultyAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'is_active']
    search_fields = ['name', 'code']

@admin.register(AdmittedStudent)
class AdmittedStudentAdmin(admin.ModelAdmin):
    list_display = ['id', 'admitted_program', 'admitted_campus']

@admin.register(AcademicLevel)
class AcademicLevelAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name']

@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'application_start_date', 'application_end_date', 'is_active', 'created_by']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'code']
    filter_horizontal = ['programs']

@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ['id', 'full_name', 'batch', 'campus', 'status', 'application_fee_paid', 'created_at']
    list_filter = ['status', 'application_fee_paid', 'campus', 'batch', 'created_at']
    search_fields = ['first_name', 'last_name', 'email', 'phone']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['-created_at']

@admin.register(OLevelSubject)
class OLevelSubjectAdmin(admin.ModelAdmin):
    list_display = ['name', 'code']
    list_filter = ['code']
    search_fields = ['name', 'code']
    ordering = ['name']

@admin.register(ALevelSubject)
class ALevelSubjectAdmin(admin.ModelAdmin):
    list_display = ['name', 'code']
    list_filter = ['code']
    search_fields = ['name', 'code']
    ordering = ['name']

@admin.register(OLevelResult)
class OLevelResultAdmin(admin.ModelAdmin):
    list_display = ['application', 'subject', 'grade']
    list_filter = ['subject', 'grade']
    search_fields = ['application__first_name', 'application__last_name', 'subject__name']
    ordering = ['application', 'subject']

@admin.register(ALevelResult)
class ALevelResultAdmin(admin.ModelAdmin):
    list_display = ['application', 'subject', 'grade']
    list_filter = ['subject', 'grade']
    search_fields = ['application__first_name', 'application__last_name', 'subject__name']
    ordering = ['application', 'subject']

@admin.register(ApplicationDocument)
class ApplicationDocumentAdmin(admin.ModelAdmin):
    list_display = ['application','file', 'uploaded_at']
    list_filter = ['uploaded_at']
    search_fields = ['application__first_name', 'application__last_name']

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['application', 'amount', 'payment_method', 'status', 'created_at']
    list_filter = ['status', 'payment_method', 'created_at']
    search_fields = ['application__first_name', 'application__last_name', 'transaction_id']

@admin.register(MobileMoneyTransaction)
class MobileMoneyTransactionAdmin(admin.ModelAdmin):
    list_display = ['payment', 'phone_number', 'network', 'transaction_reference', 'created_at']
    list_filter = ['network', 'created_at']
    search_fields = ['phone_number', 'transaction_reference']


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['user', 'action', 'description', 'timestamp']
    list_filter = ['action', 'timestamp']
    search_fields = ['user__username', 'description']
    readonly_fields = ['timestamp']
    ordering = ['-timestamp']

@admin.register(UserActivity)
class UserActivityAdmin(admin.ModelAdmin):
    list_display = ['user', 'activity_type', 'timestamp']
    list_filter = ['activity_type', 'timestamp']
    search_fields = ['user__username', 'description']
    readonly_fields = ['timestamp']
    ordering = ['-timestamp']

@admin.register(PortalNotification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['recipient', 'title', 'message']
    list_filter = ['created_at']
    ordering = ['-created_at']
