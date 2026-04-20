from django.contrib import admin
from .models import *

# Register your models here.
@admin.register(DraftApplication)
class DraftAdmin(admin.ModelAdmin):
    list_display = ['applicant', 'batch', 'first_name', 'last_name', 'date_of_birth', 'nin']
    search_fields = ['first_name', 'last_name']
    list_filter = ['batch', 'created_at', 'updated_at']