from django.db import models
from accounts.models import User, Campus
from Programs.models import Program
from admissions.models import *

# Create your models here.
class DraftApplication(models.Model):
    applicant = models.ForeignKey(User, on_delete=models.CASCADE, related_name='drafts')
    batch = models.ForeignKey(Batch, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Personal Information - All optional
    first_name = models.CharField(max_length=100, blank=True, null=True)
    last_name = models.CharField(max_length=100, blank=True, null=True)
    middle_name = models.CharField(max_length=100, blank=True, null=True)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=20, blank=True, null=True)
    nationality = models.CharField(max_length=100, blank=True, null=True)
    nin = models.CharField(max_length=20, blank=True, null=True)
    passport_number = models.CharField(max_length=20, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    disabled = models.CharField(max_length=5, blank=True, null=True)

    # Next of Kin
    next_of_kin_name = models.CharField(max_length=200, blank=True, null=True)
    next_of_kin_contact = models.CharField(max_length=20, blank=True, null=True)
    next_of_kin_relationship = models.CharField(max_length=20, blank=True, null=True)

    # Program & Campus
    campus = models.ForeignKey(Campus, on_delete=models.SET_NULL, null=True, blank=True)
    programs = models.ManyToManyField(Program, blank=True)
    academic_level = models.ForeignKey(AcademicLevel, on_delete=models.SET_NULL, null=True, blank=True)

    # Academic Results (stored as JSON for flexibility)
    olevel_data = models.JSONField(default=dict)   
    alevel_data = models.JSONField(default=dict)
    additional_qualifications = models.JSONField(default=list)

    # Status
    status = models.CharField(max_length=20, default='draft')

    class Meta:
        ordering = ['-updated_at']
        verbose_name = "Draft Application"
        verbose_name_plural = "Draft Applications"

    def __str__(self):
        return f"Draft by {self.applicant.get_full_name() or self.applicant.email} - {self.updated_at}"

    @property
    def is_empty(self):
        return not any([self.first_name, self.last_name, self.programs.exists()])