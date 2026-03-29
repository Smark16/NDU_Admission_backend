from django.db import models
from accounts.models import User
from admissions.models import AcademicLevel, Batch

class ApplicationPayment(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PAID', 'Paid'),
        ('FAILED', 'Failed'),
    ]
    application = models.OneToOneField('admissions.Application', on_delete=models.CASCADE, related_name='payment', null=True, blank=True)

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    external_reference = models.CharField(max_length=50, unique=True)  
    payment_reference = models.CharField(max_length=50, blank=True, null=True)  

    amount = models.DecimalField(max_digits=10, decimal_places=2)
    phone_number = models.CharField(max_length=20)
    fee_type = models.CharField(max_length=20, default='Application Fees')

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')

    receipt_number = models.CharField(max_length=50, blank=True, null=True)
    transaction_id = models.CharField(max_length=50, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
   
class ApplicationFee(models.Model):
    fee_type = models.CharField(max_length=100)
    nationality_type = models.CharField(max_length=20)
    academic_level = models.ManyToManyField(AcademicLevel)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    admission_period = models.ForeignKey(Batch, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.nationality_type} - {self.academic_level}: {self.amount}"





















