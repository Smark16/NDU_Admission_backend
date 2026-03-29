from django.db import models
from accounts.models import User

# Create your models here.
class CustomisedAdmissionReportsPermissions(models.Model):
   user = models.ForeignKey(User, on_delete=models.CASCADE)
   class Meta:
        permissions = [
            ("view_admissionreports", "Can view Admission Reports"),
            ("view_setup", "Can View Academic Setup")
        ]