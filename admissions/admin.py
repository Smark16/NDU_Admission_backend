from django.contrib import admin
from django.utils.html import format_html
from admissions.models import *
from payments.models import ApplicationPayment
from audit.models import AuditLog

@admin.register(Faculty)
class FacultyAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'is_active']
    search_fields = ['name', 'code']

@admin.register(AdmittedStudent)
class AdmittedStudentAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'application',
        'student_id',
        'reg_no',
        'schoolpay_code',
        'admission_fee_paid',
        'is_registered',
        'is_registered_with_schoolpay',
        'physical_documents_verified',
        'admitted_batch',
        'admitted_program',
        'admitted_by',
    ]
    list_filter = [
        'is_registered',
        'is_registered_with_schoolpay',
        'physical_documents_verified',
        'admitted_batch',
        'admitted_campus',
        'is_admitted',
    ]
    search_fields = ['student_id', 'reg_no', 'schoolpay_code', 'application__first_name', 'application__last_name']
    raw_id_fields = ('physical_documents_verified_by',)

@admin.register(AcademicLevel)
class AcademicLevelAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name']


@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ['label', 'is_current', 'is_active', 'updated_at']
    list_filter = ['is_current', 'is_active']
    search_fields = ['label']
    ordering = ['-label']

@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = [
        'name',
        'code',
        'application_start_date',
        'application_end_date',
        'admission_start_date',
        'admission_end_date',
        'is_active',
        'created_by',
    ]
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'code']
    filter_horizontal = ['programs']
    fieldsets = (
        (None, {'fields': ('name', 'code', 'programs', 'academic_year', 'is_active')}),
        (
            'Application window',
            {'fields': ('application_start_date', 'application_end_date')},
        ),
        (
            'Admission window',
            {'fields': ('admission_start_date', 'admission_end_date')},
        ),
        ('Meta', {'fields': ('created_by', 'created_at', 'updated_at')}),
    )
    readonly_fields = ['created_at', 'updated_at']

@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ['id', 'full_name', 'batch', 'campus', 'status', 'application_fee_paid', 'created_at']
    list_filter = ['status', 'application_fee_paid', 'campus', 'batch', 'created_at']
    search_fields = ['first_name', 'last_name', 'email', 'phone']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['-created_at']

@admin.register(ApplicationProgramChoice)
class ApplicationProgramChoiceAdmin(admin.ModelAdmin):
    list_display = ['application', 'program', 'choice_order']
    search_fields = ['program__name', 'application__first_name', 'application__last_name']

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

# @admin.register(ApplicationPayment)
# class PaymentAdmin(admin.ModelAdmin):
#     list_display = ['application', 'amount', 'payment_method', 'status', 'created_at']
#     list_filter = ['status', 'payment_method', 'created_at']
#     search_fields = ['application__first_name', 'application__last_name', 'transaction_id']

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['user', 'action', 'description', 'timestamp']
    list_filter = ['action', 'timestamp']
    search_fields = ['user__username', 'description']
    readonly_fields = ['timestamp']
    ordering = ['-timestamp']

@admin.register(PortalNotification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['recipient', 'title', 'message']
    list_filter = ['created_at']
    ordering = ['-created_at']


@admin.register(IdCardPdfTemplate)
class IdCardPdfTemplateAdmin(admin.ModelAdmin):
    list_display = ["name", "key", "updated_at"]
    search_fields = ["name", "key"]


@admin.register(StudentIdCard)
class StudentIdCardAdmin(admin.ModelAdmin):
    list_display = [
        "card_number",
        "admitted_student",
        "status",
        "is_active",
        "issue_date",
        "expiry_date",
        "issued_by",
        "created_at",
    ]
    list_filter = ["status", "is_active", "issue_date"]
    search_fields = [
        "card_number",
        "admitted_student__student_id",
        "admitted_student__reg_no",
        "admitted_student__application__first_name",
        "admitted_student__application__last_name",
    ]
    raw_id_fields = ("admitted_student", "issued_by", "replaced_by")
    readonly_fields = ["created_at", "updated_at"]


@admin.register(EmailTemplate)
class EmailTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'key', 'is_active', 'updated_by', 'updated_at']
    list_filter = ['is_active', 'key']
    search_fields = ['name', 'key', 'subject_template']
    readonly_fields = ['created_at', 'updated_at']

