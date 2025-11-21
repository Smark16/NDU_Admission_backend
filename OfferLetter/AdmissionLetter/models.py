from django.db import models
from Programs.models import Program

# Create your models here.

class OfferLetterTemplate(models.Model):
    name = models.CharField(max_length=40, blank=True, null=True)
    file = models.FileField(upload_to='admission_template/')
    file_url = models.URLField(max_length=200, blank=True, null=True)
    programs = models.ManyToManyField(Program)
    status = models.CharField(default="active")
    uploaded_at = models.DateTimeField(auto_now_add=True)
