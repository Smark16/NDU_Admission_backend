"""
Admin configuration for staff app.
"""
from django.contrib import admin
from .models import *

@admin.register(SupervisionAssignment)
class SupervisionAssignmentAdmin(admin.ModelAdmin):
    list_display = ['supervisor', 'team', 'staff_member']
    search_fields = ['supervisor__first_name']    

@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ['id', 'name']

@admin.register(PositonLevel)
class PositionAdmin(admin.ModelAdmin):
    list_display = ['id', 'name']

