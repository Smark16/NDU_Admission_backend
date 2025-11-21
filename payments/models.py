from django.db import models
from accounts.models import User
from admissions.models import Application, AcademicLevel, Batch

class Payment(models.Model):
    """Model for application fee payments"""
    
    PAYMENT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]
    
    PAYMENT_METHOD_CHOICES = [
        ('mobile_money', 'Mobile Money'),
        ('bank_transfer', 'Bank Transfer'),
    ]
    
    application = models.OneToOneField(Application, on_delete=models.CASCADE, related_name='payment')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    transaction_id = models.CharField(max_length=100, unique=True)
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')
    mobile_money_number = models.CharField(max_length=20, blank=True)
    payment_reference = models.CharField(max_length=100, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Payment for {self.application.full_name} - {self.amount}"

class MobileMoneyTransaction(models.Model):
    """Model for mobile money transaction details"""
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='mobile_money_details')
    phone_number = models.CharField(max_length=20)
    network = models.CharField(max_length=20)  # MTN, Airtel, etc.
    transaction_reference = models.CharField(max_length=100)
    external_transaction_id = models.CharField(max_length=100, blank=True)
    status_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Mobile Money - {self.phone_number} - {self.payment.amount}"
    
class ApplicationFee(models.Model):
    fee_type = models.CharField(max_length=100)
    nationality_type = models.CharField(max_length=20)
    academic_level = models.ManyToManyField(AcademicLevel)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    admission_period = models.ForeignKey(Batch, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.nationality_type} - {self.academic_level}: {self.amount}"


















