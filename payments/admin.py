from django.contrib import admin
from .models import ApplicationPayment, ApplicationFee

@admin.register(ApplicationPayment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'external_reference', 'payment_reference', 'transaction_id', 'status']
    search_fields = ['user__first_name', 'user__last_name', 'external_reference', 'payment_reference', 'transaction_id']
    list_filter = ['status', 'created_at', 'updated_at']

@admin.register(ApplicationFee)
class ApplicationFeeAdmin(admin.ModelAdmin):
    list_display = ['id', 'fee_type', 'nationality_type', 'amount', 'admission_period']
