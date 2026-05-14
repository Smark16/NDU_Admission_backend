from django.contrib import admin
from .models import ApplicationPayment, ApplicationFee, TuitionLedger

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