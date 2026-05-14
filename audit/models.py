from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from accounts.models import User

class AuditLog(models.Model): 
    ACTION_CHOICES = [
        ('login', 'Login'),
        ('register', 'register'),
        ('phys_verify', 'Physical documents verified'),
        ('phys_clear', 'Physical documents verification cleared'),
        ('id_card_generate', 'ID card generated'),
        ('id_card_revoke', 'ID card revoked'),
        ('id_card_reissue', 'ID card reissued'),
        ('passport_photo_update', 'Passport / ID photo updated at desk'),
        ('passport_photo_delete', 'Passport / ID photo removed at desk'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=32, choices=ACTION_CHOICES)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    content_object = GenericForeignKey('content_type', 'object_id')
    description = models.TextField()
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = "Audit Log"
        verbose_name_plural = "Audit Logs"

    def __str__(self):
        return f"{self.user} - {self.action} - {self.timestamp}"



















