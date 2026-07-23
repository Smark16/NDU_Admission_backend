from django.contrib import admin
from .models import (
    ApplicationPayment,
    ApplicationFee,
    TuitionLedger,
    BursarWeeklyReportSettings,
    BursarWeeklyReportRecipient,
)

@admin.register(ApplicationPayment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'application', 'external_reference', 'created_at', 'transaction_id', 'status']
    search_fields = ['user__first_name', 'user__last_name', 'external_reference', 'payment_reference', 'transaction_id']
    list_filter = ['status', 'created_at', 'updated_at']

@admin.register(ApplicationFee)
class ApplicationFeeAdmin(admin.ModelAdmin):
    list_display = ['id', 'fee_type', 'nationality_type', 'amount', 'admission_period']

@admin.register(TuitionLedger)
class TuitionLedgerAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'student', 'amount', 'payment_date_time', 'source_payment_channel', 'student_registration_number', 'transaction_completion_status']
    search_fields = ['user__first_name', 'user__last_name', 'student_registration_number']
    list_filter = ['transaction_completion_status', 'created_at', 'synced_at']


@admin.register(BursarWeeklyReportSettings)
class BursarWeeklyReportSettingsAdmin(admin.ModelAdmin):
    list_display = ["is_enabled", "schedule_day", "schedule_hour", "schedule_minute", "last_sent_at"]


@admin.register(BursarWeeklyReportRecipient)
class BursarWeeklyReportRecipientAdmin(admin.ModelAdmin):
    list_display = ["email", "name", "is_active", "updated_at"]
    list_filter = ["is_active"]
    search_fields = ["email", "name"]
