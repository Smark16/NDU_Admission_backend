from django.contrib import admin

from .models import (
    CourseCatalogUnit,
    Program,
    ProgramBatch,
    ProgramCurriculumLine,
    Semester,
    StudentProgrammeEnrollment,
    StudentCurriculumOverride,
    StudentCourseUnitEnrollment,
    RoomType,
    TimetableSession,
    Venue,
)

# NEW MODULE: ProgramBatch + Semester inline (academic structure; not admissions.Batch)


@admin.register(CourseCatalogUnit)
class CourseCatalogUnitAdmin(admin.ModelAdmin):
    list_display = ["id", "code", "title", "credit_units", "contact_hours", "is_active", "updated_at"]
    list_filter = ["is_active"]
    search_fields = ["code", "title"]
    ordering = ["code", "title"]


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'name', 'short_form', 'academic_level',
        'calendar_type', 'min_years', 'max_years',
        'minimum_graduation_load', 'is_active',
    ]
    list_filter = ['academic_level', 'calendar_type', 'is_active', 'campuses']
    search_fields = ['name', 'code', 'short_form']
    filter_horizontal = ['campuses']


class SemesterInline(admin.TabularInline):
    model = Semester
    extra = 0
    fields = ['name', 'order', 'year_of_study', 'term_number', 'start_date', 'end_date', 'is_active']


@admin.register(ProgramBatch)
class ProgramBatchAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'program', 'academic_year', 'start_date', 'offer_start_date', 'offer_end_date', 'is_active']
    list_filter = ['is_active', 'program']
    search_fields = ['name', 'academic_year']
    inlines = [SemesterInline]


class ProgramCurriculumLineInline(admin.TabularInline):
    model = ProgramCurriculumLine
    extra = 0
    fields = ['catalog_course', 'year_of_study', 'term_number', 'course_type', 'elective_group', 'sort_order', 'is_active']
    autocomplete_fields = ['catalog_course']


@admin.register(ProgramCurriculumLine)
class ProgramCurriculumLineAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'program', 'catalog_course', 'year_of_study',
        'term_number', 'course_type', 'elective_group', 'sort_order', 'is_active',
    ]
    list_filter = ['program', 'year_of_study', 'term_number', 'course_type', 'is_active']
    search_fields = ['catalog_course__code', 'catalog_course__title', 'program__name', 'program__code']
    ordering = ['program', 'year_of_study', 'term_number', 'sort_order']
    autocomplete_fields = ['catalog_course']


@admin.register(StudentProgrammeEnrollment)
class StudentProgrammeEnrollmentAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'student', 'program', 'program_batch',
        'entry_year_of_study', 'entry_term_number',
        'current_year_of_study', 'current_term_number',
        'status', 'enrolled_at', 'enrolled_by',
    ]
    list_filter = ['status', 'program', 'program_batch', 'current_year_of_study']
    search_fields = [
        'student__student_id', 'student__application__first_name',
        'student__application__last_name', 'program__name',
    ]
    ordering = ['-enrolled_at', '-created_at']
    readonly_fields = ['enrolled_at', 'created_at', 'updated_at']
    raw_id_fields = ['student', 'enrolled_by']
    fieldsets = [
        ('Student & Programme', {
            'fields': ('student', 'program', 'program_batch', 'status', 'enrolled_by', 'notes'),
        }),
        ('Entry Point (immutable)', {
            'fields': ('entry_year_of_study', 'entry_term_number'),
            'description': 'Where this student started. Set once; do not change after enrollment.',
        }),
        ('Current Position', {
            'fields': ('current_year_of_study', 'current_term_number'),
            'description': 'Updated as the student progresses through the programme.',
        }),
        ('Timestamps', {
            'fields': ('enrolled_at', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    ]


class StudentCurriculumOverrideInline(admin.TabularInline):
    model = StudentCurriculumOverride
    extra = 0
    fields = [
        'curriculum_line', 'override_type',
        'effective_year_of_study', 'effective_term_number',
        'transferred_grade', 'transferred_institution',
        'substituted_by', 'notes', 'decided_by',
    ]
    autocomplete_fields = ['curriculum_line']
    raw_id_fields = ['decided_by', 'substituted_by']


@admin.register(StudentCurriculumOverride)
class StudentCurriculumOverrideAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'get_student_id', 'get_curriculum_code',
        'override_type', 'effective_year_of_study', 'effective_term_number',
        'transferred_grade', 'decided_by', 'decided_at',
    ]
    list_filter = ['override_type', 'enrollment__program']
    search_fields = [
        'enrollment__student__student_id',
        'curriculum_line__catalog_course__code',
        'curriculum_line__catalog_course__title',
    ]
    ordering = ['enrollment', 'curriculum_line__year_of_study', 'curriculum_line__term_number']
    raw_id_fields = ['enrollment', 'curriculum_line', 'substituted_by', 'decided_by']

    def get_student_id(self, obj):
        return obj.enrollment.student.student_id
    get_student_id.short_description = 'Student ID'

    def get_curriculum_code(self, obj):
        return obj.curriculum_line.catalog_course.code
    get_curriculum_code.short_description = 'Course Code'


@admin.register(StudentCourseUnitEnrollment)
class StudentCourseUnitEnrollmentAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'student', 'course_unit', 'source',
        'status', 'enrollment_date', 'registration_date', 'grade',
    ]
    list_filter = ['source', 'status', 'course_unit__semester__program_batch']
    search_fields = ['student__student_id', 'course_unit__code', 'course_unit__name']
    ordering = ['-enrollment_date']


@admin.register(RoomType)
class RoomTypeAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "is_active", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["name"]


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "code",
        "name",
        "building",
        "campus",
        "room_type",
        "capacity",
        "is_active",
    ]
    list_filter = ["is_active", "campus", "room_type"]
    search_fields = ["name", "code", "building"]


@admin.register(TimetableSession)
class TimetableSessionAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "course_unit",
        "day_of_week",
        "start_time",
        "end_time",
        "venue",
        "session_type",
        "delivery_mode",
        "is_published",
        "is_active",
    ]
    list_filter = ["day_of_week", "session_type", "is_published", "is_active"]
    search_fields = ["course_unit__code", "course_unit__name", "room_label"]
    raw_id_fields = ["course_unit", "venue"]