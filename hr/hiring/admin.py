from django.contrib import admin
from .models import JobOpening, JobApplication, Interview

@admin.register(JobOpening)
class JobOpeningAdmin(admin.ModelAdmin):
    list_display = ['id','title', 'department', 'employment_type', 'application_deadline', 'published_date', 'status']

@admin.register(JobApplication)
class JobApplication(admin.ModelAdmin):
    list_display = ['id', 'first_name', 'last_name', 'brief_description', 'reference', 'status']