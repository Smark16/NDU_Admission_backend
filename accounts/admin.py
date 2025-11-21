from django.contrib import admin
from accounts.models import User, Campus, Profile

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ['id', 'email', 'first_name', 'last_name', 'role', 'is_staff', 'is_applicant', 'is_active']
    list_filter = ['role', 'is_active']
    search_fields = ['email', 'first_name', 'last_name']
    filter_horizontal = ['campuses']

@admin.register(Campus)
class CampusAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'code', 'email']
    list_filter = ['name']
    search_fields = ['name', 'code', 'email']

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ['id', 'user']


















