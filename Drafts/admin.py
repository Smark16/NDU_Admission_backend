from django.contrib import admin
from .models import *

# Register your models here.
@admin.register(DraftApplication)
class DraftAdmin(admin.ModelAdmin):
    list_display = ['applicant', 'batch', 'first_name', 'last_name', 'applicant_category', 'nin', 'phone']
    search_fields = ['first_name', 'last_name', 'phone']
    list_filter = ['applicant_category', 'batch', 'created_at', 'updated_at']
