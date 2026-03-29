from django.contrib import admin
from .models import ApplicationPayment

@admin.register(ApplicationPayment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'external_reference', 'payment_reference', 'transaction_id', 'status']