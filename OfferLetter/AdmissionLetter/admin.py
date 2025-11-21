from django.contrib import admin
from .models import *

# Register your models here.

@admin.register(OfferLetterTemplate)
class OfferLetterAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'file', 'file_url', 'status']
