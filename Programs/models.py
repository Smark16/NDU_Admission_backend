from decimal import Decimal

from django.db import models
from accounts.models import Campus
from admissions.models import *

# Create your models here.
class Program(models.Model):

    CALENDAR_TYPE_CHOICES = [
        ('semester', 'Semester'),
        ('trimester', 'Trimester'),
    ]

    name = models.CharField(max_length=200)
    short_form = models.CharField(max_length=200)
    code = models.CharField(max_length=40)
    faculty = models.ForeignKey('admissions.Faculty', on_delete=models.CASCADE, related_name='programs', null=True, blank=True)
    academic_level = models.ForeignKey('admissions.AcademicLevel', on_delete=models.CASCADE)
    campuses = models.ManyToManyField(Campus, related_name='programs', blank=True)
    min_years = models.PositiveIntegerField()
    max_years = models.PositiveIntegerField()
    calendar_type = models.CharField(
        max_length=20,
        choices=CALENDAR_TYPE_CHOICES,
        default='semester',
        help_text="Academic calendar structure: semester (2 terms/year) or trimester (3 terms/year).",
    )
    minimum_graduation_load = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Minimum total credit units a student must accumulate to graduate from this programme.",
    )
    has_specialization = models.BooleanField(
        default=False,
        help_text="Set to True if this programme branches into specialization tracks.",
    )
    specialization_entry_year = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Year of study when students must choose a specialization "
            "(e.g. 3 for Year 3). Only relevant when has_specialization is True."
        ),
    )
    specialization_entry_term = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Term within specialization_entry_year when the choice is required "
            "(e.g. 1 for the first term of Year 3)."
        ),
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['name']),
        ]

    def __str__(self):
        return f"{self.name}"

    @property
    def max_terms_per_year(self):
        """Returns the number of valid terms per year based on calendar_type."""
        return 3 if self.calendar_type == 'trimester' else 2

    def credit_summary(self, curriculum_version=None):
        """Compute curriculum completeness against effective minimum graduation load.

        When ``curriculum_version`` is set, compares totals to that version's
        effective minimum (version override if set, else programme default).
        Queries active curriculum lines only. Returns a plain dict for API use.
        """
        from django.db.models import Sum

        lines = self.curriculum_lines.filter(is_active=True)
        if curriculum_version is not None:
            lines = lines.filter(curriculum_version=curriculum_version)
        agg = lines.aggregate(
            total=Sum('catalog_course__credit_units'),
            mandatory=Sum(
                'catalog_course__credit_units',
                filter=models.Q(course_type='mandatory'),
            ),
            elective=Sum(
                'catalog_course__credit_units',
                filter=models.Q(course_type='elective'),
            ),
        )

        total = agg['total'] or Decimal('0.00')
        mandatory = agg['mandatory'] or Decimal('0.00')
        elective = agg['elective'] or Decimal('0.00')
        programme_min = self.minimum_graduation_load or Decimal('0.00')
        if curriculum_version is not None:
            min_load = curriculum_version.effective_minimum_graduation_load
            inherits_programme_default = curriculum_version.minimum_graduation_load is None
        else:
            min_load = programme_min
            inherits_programme_default = True

        if min_load == Decimal('0.00'):
            credit_status = 'unknown'
        elif total < min_load:
            credit_status = 'deficit'
        elif total == min_load:
            credit_status = 'ok'
        else:
            credit_status = 'excess'

        return {
            'minimum_graduation_load': str(min_load),
            'programme_minimum_graduation_load': str(programme_min),
            'graduation_load_inherits_from_programme': inherits_programme_default,
            'total_mapped_credits': str(total),
            'mandatory_credits': str(mandatory),
            'elective_credits': str(elective),
            'credit_status': credit_status,
            'credit_deficit': str(max(Decimal('0.00'), min_load - total)),
            'credit_excess': str(max(Decimal('0.00'), total - min_load)),
        }


class ProgramCurriculumVersion(models.Model):
    """Versioned curriculum container under a programme.

    A single Program can have multiple curriculum versions (alternatives) so
    old cohorts/students stay pinned to historical mappings while new cohorts
    can use newer versions.
    """

    program = models.ForeignKey(
        Program,
        on_delete=models.CASCADE,
        related_name='curriculum_versions',
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    minimum_graduation_load = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=(
            "Optional minimum total credit units for this version. "
            "Leave blank to use the programme's minimum_graduation_load."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_default', 'name', '-created_at']
        unique_together = [('program', 'name')]
        verbose_name = "Program Curriculum Version"
        verbose_name_plural = "Program Curriculum Versions"

    def __str__(self):
        tag = " (default)" if self.is_default else ""
        return f"{self.program.short_form} - {self.name}{tag}"

    @property
    def effective_minimum_graduation_load(self) -> Decimal:
        """Minimum credits for summaries: version override, else programme default."""
        if self.minimum_graduation_load is not None:
            return self.minimum_graduation_load
        return self.program.minimum_graduation_load or Decimal('0.00')


def resolve_program_default_curriculum_version(program: Program):
    """Best-effort default curriculum version resolver for backward compatibility."""
    if not program:
        return None
    default_version = program.curriculum_versions.filter(is_default=True).first()
    if default_version:
        return default_version
    return program.curriculum_versions.order_by('id').first()


def ensure_program_default_curriculum_version(program: Program):
    """Return the programme's default curriculum version, creating one if missing.

    Older programmes (pre–curriculum-version feature) had no rows here, which
    blocked the admin UI from loading versions or mapping catalog courses.
    """
    if not program:
        return None
    existing = resolve_program_default_curriculum_version(program)
    if existing:
        return existing

    from django.db import IntegrityError

    try:
        return ProgramCurriculumVersion.objects.create(
            program=program,
            name="Default curriculum",
            description="Created automatically. Rename or add more versions as needed.",
            is_active=True,
            is_default=True,
        )
    except IntegrityError:
        return ProgramCurriculumVersion.objects.filter(program=program).order_by("id").first()


# =============================================================================
# Programme specialization tracks
# -----------------------------------------------------------------------------
# When Program.has_specialization is True, this table is the authoritative list
# of allowed track names.  ProgramCurriculumLine.specialization values should
# match one of these names (case-insensitive).
# =============================================================================


class ProgramSpecialization(models.Model):
    """Authoritative specialization/track options for a programme.

    One row per track name per programme.  Used to:
      - Drive the curriculum line specialization dropdown (admin)
      - Validate student specialization selection at registration
      - Replace ad-hoc free-text on ProgramCurriculumLine when the programme
        has has_specialization=True
    """

    program = models.ForeignKey(
        Program,
        on_delete=models.CASCADE,
        related_name='specializations',
        help_text="The programme this track belongs to.",
    )
    name = models.CharField(
        max_length=100,
        help_text="Track name, e.g. 'Accounting', 'Marketing'. Must be unique per programme.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        unique_together = [('program', 'name')]
        verbose_name = 'Program Specialization'
        verbose_name_plural = 'Program Specializations'

    def __str__(self):
        return f"{self.program.short_form} → {self.name}"


# =============================================================================
# Course catalog (reusable academic definitions — not tied to a programme)
# -----------------------------------------------------------------------------
# ProgramCurriculumLine FKs to CourseCatalogUnit (see below).
# Operational CourseUnit rows (semester/batch) may optionally set catalog_unit
# to reference the same catalog definition when an offering is instantiated.
# =============================================================================


class CourseCatalogUnit(models.Model):
    """Shared catalog entry for a module/component (independent of programme mapping)."""

    code = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Unique catalog code (e.g. CS101).",
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    credit_units = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Credit weight (e.g. 3.0).",
    )
    lecture_hours = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Scheduled lecture hours (optional; used for contact total).",
    )
    practical_hours = models.PositiveSmallIntegerField(null=True, blank=True)
    tutorial_hours = models.PositiveSmallIntegerField(null=True, blank=True)
    contact_hours = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Total contact hours; left blank to auto-sum L+P+T on save.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code", "title"]
        verbose_name = "Course catalog unit"
        verbose_name_plural = "Course catalog units"

    def __str__(self):
        return f"{self.code} — {self.title}"

    def save(self, *args, **kwargs):
        lh = self.lecture_hours or 0
        ph = self.practical_hours or 0
        th = self.tutorial_hours or 0
        summed = lh + ph + th
        if self.contact_hours is None:
            self.contact_hours = summed
        super().save(*args, **kwargs)


# =============================================================================
# Programme curriculum mapping
# -----------------------------------------------------------------------------
# ProgramCurriculumLine bridges a Programme and the reusable CourseCatalogUnit.
# It is the authoritative list of what a student *should* study in each
# year/semester of a given programme.  Operational CourseUnit rows are created
# from this blueprint when a semester is actually scheduled.
# =============================================================================


class ProgramCurriculumLine(models.Model):
    """Maps a catalogue course to a programme slot (year + semester).

    This is the blueprint layer — it defines *what* is taught, not *when* a
    specific cohort runs it.  Operational scheduling lives in CourseUnit.
    """

    COURSE_TYPE_CHOICES = [
        ('mandatory', 'Mandatory'),
        ('elective', 'Elective'),
    ]

    program = models.ForeignKey(
        Program,
        on_delete=models.CASCADE,
        related_name='curriculum_lines',
    )
    curriculum_version = models.ForeignKey(
        ProgramCurriculumVersion,
        on_delete=models.CASCADE,
        related_name='lines',
        help_text="Curriculum version this line belongs to.",
    )
    catalog_course = models.ForeignKey(
        CourseCatalogUnit,
        on_delete=models.PROTECT,
        related_name='curriculum_lines',
        help_text="Catalogue entry being mapped into this programme slot.",
    )
    year_of_study = models.PositiveSmallIntegerField(
        help_text="Academic year within the programme (1-based, e.g. 1, 2, 3).",
    )
    term_number = models.PositiveSmallIntegerField(
        help_text="Term within the year. Valid values depend on the programme calendar: 1–2 for semester, 1–3 for trimester.",
    )
    course_type = models.CharField(
        max_length=20,
        choices=COURSE_TYPE_CHOICES,
        default='mandatory',
    )
    elective_group = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Groups electives for selection rules (e.g. 'Group A'). Null for mandatory courses.",
    )
    specialization = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Reserved for future specialization/track filtering.",
    )
    sort_order = models.PositiveSmallIntegerField(
        default=0,
        help_text="Display order within a year/semester block.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['year_of_study', 'term_number', 'sort_order', 'catalog_course__code']
        constraints = [
            models.UniqueConstraint(
                fields=('curriculum_version', 'catalog_course', 'year_of_study', 'term_number'),
                name='unique_curriculum_slot',
            )
        ]
        verbose_name = 'Program Curriculum Line'
        verbose_name_plural = 'Program Curriculum Lines'

    def __str__(self):
        return (
            f"{self.program.short_form} "
            f"Y{self.year_of_study}T{self.term_number} — "
            f"{self.catalog_course.code}"
        )

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.year_of_study and self.program_id:
            if self.year_of_study > self.program.max_years:
                raise ValidationError({
                    'year_of_study': (
                        f"Year of study ({self.year_of_study}) exceeds this "
                        f"programme's max years ({self.program.max_years})."
                    )
                })
        if self.term_number and self.program_id:
            max_terms = self.program.max_terms_per_year
            valid = set(range(1, max_terms + 1))
            if self.term_number not in valid:
                raise ValidationError({
                    'term_number': (
                        f"Term number must be between 1 and {max_terms} "
                        f"for a {self.program.calendar_type}-based programme."
                    )
                })


# =============================================================================
# NEW MODULE: Program academic structure (batch / semester / course units)
# -----------------------------------------------------------------------------
# ProgramBatch = academic cohort for a degree program (e.g. Year 1), NOT the
# same as admissions.Batch (application/admission intake periods).
# Semester = term inside a ProgramBatch. CourseUnit / enrollment / progression
# support timetabling and future student flows. Used by:
#   - Programs/batch_views.py, semester_update_view.py, Programs/urls.py
#   - payments: semester tuition matrix (FeePlanRule × program_batch × semester)
# =============================================================================


class ProgramBatch(models.Model):
    """Academic batch/cohort for a program (e.g., Year 1, Year 2)."""
    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name='program_batches')
    curriculum_version = models.ForeignKey(
        ProgramCurriculumVersion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='program_batches',
        help_text=(
            "Curriculum version used by this cohort/batch. "
            "If blank, fallback logic resolves the programme default."
        ),
    )
    name = models.CharField(max_length=100, help_text="e.g., Year 1, Year 2, Level 3")
    academic_year = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Cohort year label (e.g. 2024/2025).",
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start_date', 'name']
        verbose_name = 'Program Batch'
        verbose_name_plural = 'Program Batches'
        unique_together = ['program', 'name']

    def __str__(self):
        return f"{self.program.short_form} - {self.name}"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.curriculum_version_id and self.curriculum_version.program_id != self.program_id:
            raise ValidationError("curriculum_version does not belong to the selected program.")


class Semester(models.Model):
    """Academic semester/term within a program batch.

    ``year_of_study`` and ``term_number`` are optional but strongly recommended.
    When set they align this operational semester with the programme's
    ProgramCurriculumLine blueprint (same field names, same meaning).
    Leaving them null keeps full backward-compatibility with existing records.
    """
    program_batch = models.ForeignKey(ProgramBatch, on_delete=models.CASCADE, related_name='semesters')
    name = models.CharField(max_length=100, help_text="e.g., Semester 1, Year 1 Sem 1")
    order = models.PositiveIntegerField(default=1, help_text="Absolute semester sequence number within this batch.")
    # --- curriculum position (aligns with ProgramCurriculumLine) ---
    year_of_study = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Academic year this semester belongs to (1-based). "
            "Aligns with ProgramCurriculumLine.year_of_study. "
            "Required to use curriculum suggestions."
        ),
    )
    term_number = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Term within the year (1–2 for semester, 1–3 for trimester). "
            "Aligns with ProgramCurriculumLine.term_number."
        ),
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['program_batch', 'order', 'start_date']
        unique_together = ['program_batch', 'order']

    def __str__(self):
        pos = f" (Y{self.year_of_study}T{self.term_number})" if self.year_of_study and self.term_number else ""
        return f"{self.program_batch.program.short_form} - {self.program_batch.name} - {self.name}{pos}"

    def clean(self):
        from django.core.exceptions import ValidationError
        # year_of_study and term_number must be set together or not at all
        both_set = self.year_of_study is not None and self.term_number is not None
        either_set = self.year_of_study is not None or self.term_number is not None
        if either_set and not both_set:
            raise ValidationError(
                "year_of_study and term_number must both be set together, or both left blank."
            )
        if both_set:
            program = self.program_batch.program
            if self.year_of_study < 1 or self.year_of_study > program.max_years:
                raise ValidationError({
                    'year_of_study': (
                        f"Year of study ({self.year_of_study}) must be between 1 and "
                        f"{program.max_years} for this programme."
                    )
                })
            max_terms = program.max_terms_per_year
            if self.term_number not in range(1, max_terms + 1):
                raise ValidationError({
                    'term_number': (
                        f"Term number must be between 1 and {max_terms} "
                        f"for a {program.calendar_type}-based programme."
                    )
                })
            # No two semesters in the same batch should occupy the same curriculum slot
            qs = Semester.objects.filter(
                program_batch=self.program_batch,
                year_of_study=self.year_of_study,
                term_number=self.term_number,
            )
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError(
                    f"A semester at Year {self.year_of_study} Term {self.term_number} "
                    f"already exists in this batch."
                )


class CourseUnit(models.Model):
    """Course unit/subject offered in a semester (optional; used by batch subject API).

    Three optional upstream links (all nullable for backward compatibility):
      catalog_unit      — shared course catalog entry (CourseCatalogUnit)
      curriculum_line   — the curriculum blueprint this was instantiated from
    When ``curriculum_line`` is set the system knows this course came from the
    programme blueprint and can use it for registration/exam traceability.
    """
    catalog_unit = models.ForeignKey(
        CourseCatalogUnit,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scheduled_offerings",
        help_text="Optional link to the shared catalog row; leave empty for legacy/offline entries.",
    )
    curriculum_line = models.ForeignKey(
        'ProgramCurriculumLine',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='offered_course_units',
        help_text=(
            "Optional link to the curriculum blueprint this operational course was created from. "
            "Set this to make the course traceable to the programme curriculum."
        ),
    )
    semester = models.ForeignKey(Semester, on_delete=models.CASCADE, related_name='course_units', null=True, blank=True)
    program_batch = models.ForeignKey(ProgramBatch, on_delete=models.CASCADE, related_name='course_units', null=True, blank=True)
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50)
    credit_units = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    lecturers = models.ManyToManyField('accounts.User', blank=True, related_name='course_units', help_text="Staff assigned to teach this course unit")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['code', 'name']
        unique_together = ['code', 'semester']

    def __str__(self):
        return f"{self.code} - {self.name}"


class StudentCourseUnitEnrollment(models.Model):
    """Track which students are enrolled in which course units."""
    student = models.ForeignKey('admissions.AdmittedStudent', on_delete=models.CASCADE, related_name='course_unit_enrollments')
    course_unit = models.ForeignKey(CourseUnit, on_delete=models.CASCADE, related_name='student_enrollments')
    enrollment_date = models.DateTimeField(auto_now_add=True)
    registration_date = models.DateTimeField(null=True, blank=True, help_text="Date when student registered for this course")
    status = models.CharField(
        max_length=20,
        choices=[
            ('enrolled', 'Enrolled'),
            ('completed', 'Completed'),
            ('withdrawn', 'Withdrawn'),
            ('failed', 'Failed'),
        ],
        default='enrolled',
    )
    grade = models.CharField(max_length=10, blank=True, null=True, help_text="Final grade if completed")
    source = models.CharField(
        max_length=20,
        choices=[
            ('self_registered', 'Self Registered'),
            ('admin_assigned',  'Admin Assigned'),
            ('transferred',     'Transferred Credit'),
            ('exempted',        'Exempted'),
        ],
        default='self_registered',
        help_text=(
            "How this enrollment came to exist. "
            "'self_registered' = student registered via portal. "
            "'admin_assigned' = admin enrolled the student directly. "
            "'transferred' = credit recognised from another institution. "
            "'exempted' = course waived by faculty decision."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_registered(self):
        return self.registration_date is not None

    class Meta:
        ordering = ['-enrollment_date']
        unique_together = ('student', 'course_unit')
        verbose_name = "Student Course Unit Enrollment"
        verbose_name_plural = "Student Course Unit Enrollments"

    def __str__(self):
        return f"{self.student.student_id} - {self.course_unit.code}"


class StudentSemesterProgression(models.Model):
    """Track student progression through semesters."""
    student = models.ForeignKey('admissions.AdmittedStudent', on_delete=models.CASCADE, related_name='semester_progressions')
    semester = models.ForeignKey(Semester, on_delete=models.CASCADE, related_name='student_progressions')
    program_batch = models.ForeignKey(ProgramBatch, on_delete=models.CASCADE, related_name='student_progressions')
    status = models.CharField(
        max_length=20,
        choices=[
            ('active', 'Active'),
            ('completed', 'Completed'),
            ('detained', 'Detained'),
            ('promoted', 'Promoted'),
        ],
        default='active',
    )
    enrollment_date = models.DateTimeField(auto_now_add=True)
    completion_date = models.DateTimeField(null=True, blank=True)
    promotion_date = models.DateTimeField(null=True, blank=True)
    detained_date = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-enrollment_date']
        unique_together = ('student', 'semester')
        verbose_name = "Student Semester Progression"
        verbose_name_plural = "Student Semester Progressions"

    def __str__(self):
        return f"{self.student.student_id} - {self.semester.name} ({self.status})"


# =============================================================================
# Academic enrollment — commitment-fee gate
# -----------------------------------------------------------------------------
# StudentProgrammeEnrollment is created AFTER the commitment fee is confirmed
# by an admin.  It represents academic placement, NOT semester registration.
#
# Flow:
#   1. Student is admitted  (AdmittedStudent.is_admitted = True)
#   2. Student pays commitment fee (150 000 UGX)
#   3. Admin verifies payment → creates/activates StudentProgrammeEnrollment
#      (status = 'enrolled')
#   4. Student can now log in and see their curriculum / course list
#   5. Later: pay ≥60% of tuition → semester registration (future module)
#
# Relationship to existing models:
#   - StudentSemesterProgression  — records per-semester promotion history
#   - StudentCourseUnitEnrollment — admin adds student to specific CourseUnits
#   - StudentProgrammeEnrollment  — the GATE: must be 'enrolled' before any
#                                   of the above is meaningful to the student
# =============================================================================


class StudentProgrammeEnrollment(models.Model):
    """Academic enrollment record created after commitment fee is confirmed.

    One record per admitted student.  ``current_year_of_study`` and
    ``current_term_number`` are updated in place as the student progresses;
    they are NOT re-created each term.

    Status lifecycle:
        pending   → commitment fee not yet confirmed (default)
        enrolled  → commitment fee confirmed by admin; student has portal access
        suspended → access blocked (e.g. non-payment, disciplinary)
        completed → programme finished
        withdrawn → student left voluntarily or administratively
    """

    STATUS_CHOICES = [
        ('pending',   'Pending Commitment Fee'),
        ('enrolled',  'Enrolled'),
        ('suspended', 'Suspended'),
        ('completed', 'Completed'),
        ('withdrawn', 'Withdrawn'),
    ]

    student = models.OneToOneField(
        'admissions.AdmittedStudent',
        on_delete=models.CASCADE,
        related_name='programme_enrollment',
        help_text="Each admitted student has at most one academic enrollment record.",
    )
    program = models.ForeignKey(
        Program,
        on_delete=models.PROTECT,
        related_name='student_enrollments',
        help_text="Must match program_batch.program.",
    )
    program_batch = models.ForeignKey(
        ProgramBatch,
        on_delete=models.PROTECT,
        related_name='student_enrollments',
        help_text="The academic cohort the student is placed in.",
    )
    curriculum_version = models.ForeignKey(
        ProgramCurriculumVersion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='student_enrollments',
        help_text=(
            "Pinned curriculum version for this student. "
            "Once set, expected/registration courses resolve from this version."
        ),
    )
    # ── Entry point (immutable after first save) ──────────────────────────────
    entry_year_of_study = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text=(
            "The year of study the student actually started at. "
            "Set once at enrollment and never changed. "
            "Differs from current_year_of_study for advanced-entry / transfer students."
        ),
    )
    entry_term_number = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text=(
            "The term the student actually started at (e.g. 2 for January intake). "
            "Set once at enrollment and never changed."
        ),
    )
    # ── Current position (advances as student progresses) ────────────────────
    current_year_of_study = models.PositiveSmallIntegerField(
        default=1,
        help_text="Student's current academic year (1-based). Updated on progression.",
    )
    current_term_number = models.PositiveSmallIntegerField(
        default=1,
        help_text="Student's current term within the year. Updated on progression.",
    )
    specialization = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text=(
            "Selected track/specialization for programmes that branch "
            "(e.g. Accounting, Management, Marketing)."
        ),
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True,
    )
    enrolled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set automatically when status transitions to 'enrolled'.",
    )
    enrolled_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='enrolled_students',
        help_text="Admin who confirmed the commitment fee and activated enrollment.",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Student Programme Enrollment'
        verbose_name_plural = 'Student Programme Enrollments'
        ordering = ['-enrolled_at', '-created_at']

    def __str__(self):
        return (
            f"{self.student.student_id} → "
            f"{self.program.short_form} / {self.program_batch.name} "
            f"Y{self.current_year_of_study}T{self.current_term_number} "
            f"({self.get_status_display()})"
        )

    @property
    def is_enrolled(self):
        return self.status == 'enrolled'

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.program_id and self.program_batch_id:
            if self.program_batch.program_id != self.program_id:
                raise ValidationError(
                    "program_batch does not belong to the selected program."
                )
        if self.curriculum_version_id and self.program_id:
            if self.curriculum_version.program_id != self.program_id:
                raise ValidationError(
                    "curriculum_version does not belong to the selected program."
                )
        if self.current_year_of_study and self.program_id:
            if self.current_year_of_study > self.program.max_years:
                raise ValidationError({
                    'current_year_of_study': (
                        f"Year {self.current_year_of_study} exceeds programme "
                        f"max years ({self.program.max_years})."
                    )
                })
        if self.current_term_number and self.program_id:
            max_terms = self.program.max_terms_per_year
            if self.current_term_number not in range(1, max_terms + 1):
                raise ValidationError({
                    'current_term_number': (
                        f"Term {self.current_term_number} is out of range for a "
                        f"{self.program.calendar_type}-based programme (max {max_terms})."
                    )
                })

    def save(self, *args, **kwargs):
        from django.utils import timezone
        # Auto-stamp enrolled_at on first transition to 'enrolled'
        if self.status == 'enrolled' and self.enrolled_at is None:
            self.enrolled_at = timezone.now()
        # Auto-populate entry point from current position on first creation
        if self.entry_year_of_study is None:
            self.entry_year_of_study = self.current_year_of_study
        if self.entry_term_number is None:
            self.entry_term_number = self.current_term_number
        super().save(*args, **kwargs)


# =============================================================================
# Student-specific curriculum override layer
# -----------------------------------------------------------------------------
# This model exists ONLY when a student's path differs from the programme
# blueprint defined in ProgramCurriculumLine.
#
# Absence of a record = standard path.
# Do NOT create records for standard students.
#
# Supported cases:
#   exempted    — course waived by faculty; counts as satisfied
#   transferred — credit from another institution; carries an external grade
#   deferred    — course postponed to a later term (e.g. January entrants)
#   backlog     — course not completed on time; must still be taken
#   substituted — a different curriculum line satisfies this one
# =============================================================================


class StudentCurriculumOverride(models.Model):
    """Student-specific override to the programme blueprint.

    One record per student per curriculum line.  Only created when the
    student's path deviates from the default ProgramCurriculumLine.

    Links to StudentProgrammeEnrollment (not AdmittedStudent directly)
    because overrides are academic decisions tied to the enrollment record.
    """

    OVERRIDE_TYPE_CHOICES = [
        ('exempted',    'Exempted'),
        ('transferred', 'Transferred Credit'),
        ('deferred',    'Deferred'),
        ('backlog',     'Backlog'),
        ('substituted', 'Substituted'),
    ]

    enrollment = models.ForeignKey(
        StudentProgrammeEnrollment,
        on_delete=models.CASCADE,
        related_name='curriculum_overrides',
        help_text="The academic enrollment this override belongs to.",
    )
    curriculum_line = models.ForeignKey(
        ProgramCurriculumLine,
        on_delete=models.CASCADE,
        related_name='student_overrides',
        help_text="The blueprint line being overridden for this student.",
    )
    override_type = models.CharField(
        max_length=20,
        choices=OVERRIDE_TYPE_CHOICES,
        help_text=(
            "exempted = waived entirely. "
            "transferred = credit from another institution. "
            "deferred = postponed to a later term. "
            "backlog = must be taken alongside a later-term cohort. "
            "substituted = another line satisfies this one."
        ),
    )
    # ── Effective position (for deferred/backlog) ─────────────────────────────
    effective_year_of_study = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text=(
            "When should this student actually take this course? "
            "Required for deferred and backlog types. "
            "Null means: use the blueprint year."
        ),
    )
    effective_term_number = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Term within effective_year_of_study. Required alongside effective_year_of_study.",
    )
    # ── Transfer credit fields ────────────────────────────────────────────────
    transferred_grade = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        help_text="Grade awarded from the transferring institution (for transferred type).",
    )
    transferred_institution = models.CharField(
        max_length=200,
        blank=True,
        help_text="Name of the institution from which the credit was transferred.",
    )
    # ── Substitution ─────────────────────────────────────────────────────────
    substituted_by = models.ForeignKey(
        ProgramCurriculumLine,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='substitutes_for',
        help_text="The curriculum line that satisfies this one (for substituted type).",
    )
    # ── Audit ─────────────────────────────────────────────────────────────────
    notes = models.TextField(
        blank=True,
        help_text="Faculty decision reference, reason, or supporting note.",
    )
    decided_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='curriculum_override_decisions',
        help_text="Staff member who created this override.",
    )
    decided_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Student Curriculum Override'
        verbose_name_plural = 'Student Curriculum Overrides'
        ordering = ['enrollment', 'curriculum_line__year_of_study', 'curriculum_line__term_number']
        constraints = [
            models.UniqueConstraint(
                fields=('enrollment', 'curriculum_line'),
                name='unique_student_curriculum_override',
            )
        ]

    def __str__(self):
        return (
            f"{self.enrollment.student.student_id} | "
            f"{self.curriculum_line.catalog_course.code} | "
            f"{self.get_override_type_display()}"
        )

    def clean(self):
        from django.core.exceptions import ValidationError
        # deferred and backlog require effective position
        if self.override_type in ('deferred', 'backlog'):
            if not self.effective_year_of_study or not self.effective_term_number:
                raise ValidationError(
                    "effective_year_of_study and effective_term_number are required "
                    f"for override type '{self.override_type}'."
                )
        # substituted requires substituted_by
        if self.override_type == 'substituted' and not self.substituted_by_id:
            raise ValidationError(
                "substituted_by is required for override type 'substituted'."
            )
        # transferred benefits from a grade (warn but don't block)
        # enrollment programme must match curriculum_line programme
        if self.curriculum_line_id and self.enrollment_id:
            if self.curriculum_line.program_id != self.enrollment.program_id:
                raise ValidationError(
                    "The curriculum line belongs to a different programme than the enrollment."
                )


# --- Existing: bulk program upload (unchanged) ---


class BulkUploadPrograms(models.Model):
    file_name = models.CharField(max_length=255)
    file_path = models.FileField(upload_to='bulk_uploads/')
    status = models.CharField(max_length=20, default='pending')
    total_records = models.IntegerField(default=0)
    processed_records = models.IntegerField(default=0)
    success_records = models.IntegerField(default=0)
    failed_records = models.IntegerField(default=0)
    error_log = models.TextField(blank=True, null=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.file_name}"
