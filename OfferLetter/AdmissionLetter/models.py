from django.db import models
from Programs.models import Program

# Create your models here.

HALL_CHOICES = [
    ("AKIIBUA", "Akiibua"),
    ("NJUKI", "Njuki"),
    ("MUTEESA", "Muteesa"),
    ("KAKUNGULU", "Kakungulu"),
    ("YOKANA", "Yokana"),
    ("RANDOM", "Assign Randomly"),
]

class OfferLetterTemplate(models.Model):
    name = models.CharField(max_length=50, blank=True, null=True)
    file = models.FileField(upload_to='admission_template/')
    file_url = models.URLField(max_length=200, blank=True, null=True)
    programs = models.ManyToManyField(Program)
    status = models.CharField(default="active")
    start_date = models.DateField(blank=True, null=True)
    hall_of_residence = models.CharField(max_length=20, choices=HALL_CHOICES, blank=True, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
   
    class Meta:
        indexes = [
                models.Index(fields=['status', 'uploaded_at']),
            ]
