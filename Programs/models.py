from django.db import models
from accounts.models import Campus
from admissions.models import *

# Create your models here.
class Program(models.Model):
    name = models.CharField(max_length=200)
    short_form = models.CharField(max_length=200)
    code = models.CharField(max_length=20)
    faculty = models.ForeignKey('admissions.Faculty', on_delete=models.CASCADE, related_name='programs', null=True, blank=True)
    academic_level = models.ForeignKey('admissions.AcademicLevel', on_delete=models.CASCADE)
    campuses = models.ManyToManyField(Campus, related_name='programs', blank=True)
    min_years = models.PositiveIntegerField()
    max_years = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name}"

class BulkUploadPrograms(models.Model):
    file_name = models.CharField(max_length=255)
    file_path = models.FileField(upload_to='bulk_uploads/')
    status = models.CharField(max_length=20, default='pending')
    total_records = models.IntegerField(default=0)
    processed_records = models.IntegerField(default=0)
    success_records = models.IntegerField(default=0)
    failed_records = models.IntegerField(default=0)
    error_log = models.TextField(blank=True, null=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.file_name}"