from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _
from django.db.models.signals import post_save

class Campus(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=10, unique=True)
    address = models.TextField()
    email = models.EmailField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Campuses"
        ordering = ['name']

    def __str__(self):
        return self.name

class User(AbstractUser):
    role = models.CharField(max_length=20, blank=True, null=True)
    campuses = models.ManyToManyField(Campus, blank=True, related_name='users')
    phone = models.CharField(max_length=20, blank=True, null=True)
    is_staff = models.BooleanField(default=False)
    is_applicant = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.get_full_name()}"
    
class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    email = models.EmailField(max_length=100)
    phone = models.PositiveBigIntegerField()
    profile_photo = models.ImageField(upload_to='passport_photos/')
    is_staff = models.BooleanField(default=False)
    is_applicant = models.BooleanField(default=False)
    date_joined = models.DateTimeField()

def create_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance, 
        first_name=instance.first_name, 
        last_name=instance.last_name, 
        date_joined=instance.date_joined,
        is_staff=instance.is_staff,
        is_applicant=instance.is_applicant,
        email=instance.email,
        phone=instance.phone
        )

def save_profile(sender, instance, **kwargs):
    if hasattr(instance, 'profile'):
        instance.profile.save()

post_save.connect(create_profile, sender=User)
post_save.connect(save_profile, sender=User) 









