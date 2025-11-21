from django.contrib import admin
from .models import Program

# Register your models here.
@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'academic_level', 'min_years','max_years', 'is_active']
    list_filter = ['academic_level', 'is_active', 'campuses']
    search_fields = ['name']
    filter_horizontal = ['campuses']