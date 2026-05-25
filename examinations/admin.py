from django.contrib import admin

from .models import (
    AssessmentPolicy,
    AwardClassBand,
    AwardClassificationScheme,
    CourseUnitResult,
    ExamCardToken,
    ExamRetakeRegistration,
    ExamSession,
    GradeBand,
    GradeScale,
    ResultChangeRequest,
)


class GradeBandInline(admin.TabularInline):
    model = GradeBand
    extra = 1


@admin.register(GradeScale)
class GradeScaleAdmin(admin.ModelAdmin):
    list_display = ("name", "academic_level", "is_active")
    list_filter = ("academic_level", "is_active")
    inlines = [GradeBandInline]


class AwardClassBandInline(admin.TabularInline):
    model = AwardClassBand
    extra = 1


@admin.register(AwardClassificationScheme)
class AwardClassificationSchemeAdmin(admin.ModelAdmin):
    list_display = ("name", "academic_level", "is_active")
    list_filter = ("academic_level", "is_active")
    inlines = [AwardClassBandInline]


@admin.register(AssessmentPolicy)
class AssessmentPolicyAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "academic_level",
        "ca_max",
        "min_ca_to_sit_exam",
        "pass_mark",
        "is_default",
        "is_active",
    )
    list_filter = ("academic_level", "is_active", "is_default")


@admin.register(CourseUnitResult)
class CourseUnitResultAdmin(admin.ModelAdmin):
    list_display = (
        "enrollment",
        "ca_mark",
        "exam_mark",
        "final_mark",
        "grade_letter",
        "status",
        "published_at",
    )
    list_filter = ("status", "is_pass", "edit_unlocked")
    search_fields = ("enrollment__student__reg_no", "enrollment__course_unit__code")
    raw_id_fields = ("enrollment", "entered_by", "published_by")


@admin.register(ExamCardToken)
class ExamCardTokenAdmin(admin.ModelAdmin):
    list_display = ("student", "verification_code", "exam_period_label", "issued_at", "is_revoked")
    list_filter = ("is_revoked", "issued_at")
    search_fields = ("student__reg_no", "student__student_id", "verification_code")
    raw_id_fields = ("student",)


@admin.register(ExamSession)
class ExamSessionAdmin(admin.ModelAdmin):
    list_display = (
        "course_unit",
        "session_type",
        "exam_date",
        "start_time",
        "venue",
        "is_published",
    )
    list_filter = ("session_type", "is_published", "exam_date")
    search_fields = ("course_unit__code", "title", "venue_text")
    raw_id_fields = ("course_unit", "venue", "created_by")


@admin.register(ExamRetakeRegistration)
class ExamRetakeRegistrationAdmin(admin.ModelAdmin):
    list_display = ("enrollment", "status", "exam_session", "requested_at")
    list_filter = ("status",)
    raw_id_fields = ("enrollment", "exam_session", "reviewed_by")


@admin.register(ResultChangeRequest)
class ResultChangeRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "result", "status", "requested_at", "reviewed_at")
    list_filter = ("status",)
    raw_id_fields = ("result", "requested_by", "reviewed_by")
