from django.contrib import admin

from .models import GraduationAssignment, GraduationCeremony, GraduationSession


class GraduationSessionInline(admin.TabularInline):
    model = GraduationSession
    extra = 0


@admin.register(GraduationCeremony)
class GraduationCeremonyAdmin(admin.ModelAdmin):
    list_display = ["name", "completion_date", "show_marks_on_transcript", "is_active"]
    list_filter = ["is_active"]
    inlines = [GraduationSessionInline]


@admin.register(GraduationAssignment)
class GraduationAssignmentAdmin(admin.ModelAdmin):
    list_display = ["student", "session", "cgpa_at_assignment", "award_class", "assigned_at"]
    list_filter = ["session__ceremony", "session"]
    search_fields = ["student__reg_no", "student__full_name"]
