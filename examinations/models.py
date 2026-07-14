from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .services.scoring import PolicyValues, compute_course_result, lookup_grade_band


class AssessmentPolicy(models.Model):
    """Senate-style rules: CA /40 + exam weight + sit threshold + pass mark."""

    name = models.CharField(max_length=120)
    ca_max = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("40"))
    exam_weight = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal("0.60"),
        help_text="Exam contribution: final includes exam_mark × this (e.g. 0.60).",
    )
    min_ca_to_sit_exam = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("17.5"),
    )
    pass_mark = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("50"))
    academic_level = models.ForeignKey(
        "admissions.AcademicLevel",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assessment_policies",
        help_text="When set, applies to all programmes at this level. Leave blank for global fallback.",
    )
    is_default = models.BooleanField(default=False, db_index=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_default", "name"]
        verbose_name = "Assessment policy"
        constraints = [
            models.UniqueConstraint(
                fields=["academic_level"],
                condition=models.Q(academic_level__isnull=False),
                name="examinations_unique_policy_per_academic_level",
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        if self.is_default and self.academic_level_id:
            raise ValidationError(
                {"is_default": "Only the global fallback policy (no academic level) can be marked default."}
            )

    def save(self, *args, **kwargs):
        if self.is_default and self.academic_level_id:
            self.is_default = False
        if self.is_default:
            AssessmentPolicy.objects.filter(
                is_default=True, academic_level__isnull=True
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

    def as_policy_values(self) -> PolicyValues:
        return PolicyValues(
            ca_max=self.ca_max,
            exam_weight=self.exam_weight,
            min_ca_to_sit_exam=self.min_ca_to_sit_exam,
            pass_mark=self.pass_mark,
        )

    @classmethod
    def get_active_default(cls):
        return (
            cls.objects.filter(
                is_active=True, is_default=True, academic_level__isnull=True
            ).first()
            or cls.objects.filter(is_active=True, academic_level__isnull=True)
            .order_by("id")
            .first()
        )

    @classmethod
    def get_for_academic_level(cls, academic_level):
        if academic_level is None:
            return None
        return cls.objects.filter(is_active=True, academic_level=academic_level).first()


class GradeScale(models.Model):
    name = models.CharField(max_length=120)
    academic_level = models.ForeignKey(
        "admissions.AcademicLevel",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="grade_scales",
        help_text="When set, applies to programmes at this level. Leave blank for global fallback.",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["academic_level"],
                condition=models.Q(academic_level__isnull=False),
                name="examinations_unique_grade_scale_per_academic_level",
            ),
        ]

    def __str__(self):
        return self.name

    @classmethod
    def get_active_default(cls):
        return (
            cls.objects.filter(is_active=True, academic_level__isnull=True)
            .order_by("-id")
            .first()
        )

    @classmethod
    def get_for_academic_level(cls, academic_level):
        if academic_level is None:
            return None
        return cls.objects.filter(is_active=True, academic_level=academic_level).first()

    @classmethod
    def get_active(cls):
        """Backward-compatible alias — prefer resolve_grade_scale()."""
        return cls.get_active_default()


class GradeBand(models.Model):
    grade_scale = models.ForeignKey(GradeScale, on_delete=models.CASCADE, related_name="bands")
    letter = models.CharField(max_length=5)
    min_mark = models.DecimalField(max_digits=5, decimal_places=1)
    max_mark = models.DecimalField(max_digits=5, decimal_places=1)
    grade_point = models.DecimalField(max_digits=4, decimal_places=1)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["-min_mark", "order"]
        unique_together = [("grade_scale", "letter")]

    def __str__(self):
        return f"{self.letter} ({self.min_mark}-{self.max_mark})"


class AwardClassificationScheme(models.Model):
    """Degree class of award from cumulative CGPA (e.g. First Class)."""

    name = models.CharField(max_length=120)
    academic_level = models.ForeignKey(
        "admissions.AcademicLevel",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="award_classification_schemes",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Award classification scheme"
        constraints = [
            models.UniqueConstraint(
                fields=["academic_level"],
                condition=models.Q(academic_level__isnull=False),
                name="examinations_unique_award_scheme_per_academic_level",
            ),
        ]

    def __str__(self):
        return self.name

    @classmethod
    def get_active_default(cls):
        return (
            cls.objects.filter(is_active=True, academic_level__isnull=True)
            .order_by("-id")
            .first()
        )

    @classmethod
    def get_for_academic_level(cls, academic_level):
        if academic_level is None:
            return None
        return cls.objects.filter(is_active=True, academic_level=academic_level).first()


class AwardClassBand(models.Model):
    scheme = models.ForeignKey(
        AwardClassificationScheme,
        on_delete=models.CASCADE,
        related_name="bands",
    )
    title = models.CharField(max_length=80, help_text="e.g. First Class, Second Class (Upper)")
    min_cgpa = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        help_text="Award applies when CGPA is at or above this value.",
    )
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["-min_cgpa", "order"]

    def __str__(self):
        return f"{self.title} (≥ {self.min_cgpa})"


class CourseUnitResult(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_VERIFIED = "verified"
    STATUS_PUBLISHED = "published"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_VERIFIED, "Verified"),
        (STATUS_PUBLISHED, "Published"),
    ]

    enrollment = models.OneToOneField(
        "Programs.StudentCourseUnitEnrollment",
        on_delete=models.CASCADE,
        related_name="course_result",
    )
    policy = models.ForeignKey(
        AssessmentPolicy,
        on_delete=models.PROTECT,
        related_name="results",
    )
    ca_mark = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    exam_mark = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    final_mark = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    exam_sitting_allowed = models.BooleanField(default=False)
    is_pass = models.BooleanField(null=True, blank=True)
    grade_letter = models.CharField(max_length=5, blank=True, default="")
    grade_point = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    remark = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entered_course_results",
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_course_results",
    )
    published_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="verified_course_results",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    edit_unlocked = models.BooleanField(
        default=False,
        help_text="When true, staff allows one edit cycle on a published result (then clears).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        permissions = [
            ("enter_marks", "Can enter course marks (lecturer)"),
            ("publish_results", "Can publish examination results"),
            ("view_all_results", "Can view all examination results"),
        ]

    def __str__(self):
        return f"Result #{self.pk} ({self.enrollment_id})"

    def recompute(self, *, grade_scale: GradeScale | None = None):
        computed = compute_course_result(
            ca_mark=self.ca_mark,
            exam_mark=self.exam_mark,
            policy=self.policy.as_policy_values(),
        )
        self.ca_mark = computed.ca_mark
        self.exam_mark = computed.exam_mark
        self.final_mark = computed.final_mark
        self.exam_sitting_allowed = computed.exam_sitting_allowed
        self.is_pass = computed.is_pass

        if grade_scale is None:
            from .services.grade_scale_resolver import resolve_grade_scale

            grade_scale = resolve_grade_scale(enrollment=self.enrollment)
        if grade_scale and self.final_mark is not None:
            bands = list(grade_scale.bands.all())
            letter, gp = lookup_grade_band(self.final_mark, bands)
            self.grade_letter = letter or ""
            self.grade_point = gp
        else:
            self.grade_letter = ""
            self.grade_point = None

    def clean(self):
        if self.ca_mark is not None and self.ca_mark > self.policy.ca_max:
            raise ValidationError(
                {
                    "ca_mark": f"CA mark cannot exceed the policy maximum of {self.policy.ca_max}."
                }
            )
        if self.exam_mark is not None and self.exam_mark > 100:
            raise ValidationError(
                {
                    "exam_mark": "Exam mark cannot exceed 100."
                }
            )
        compute_course_result(
            ca_mark=self.ca_mark,
            exam_mark=self.exam_mark,
            policy=self.policy.as_policy_values(),
        )


class ExamSession(models.Model):
    """Scheduled exam sitting for a course unit (regular, retake, or supplementary)."""

    TYPE_REGULAR = "regular"
    TYPE_RETAKE = "retake"
    TYPE_SUPPLEMENTARY = "supplementary"
    TYPE_CHOICES = [
        (TYPE_REGULAR, "Regular"),
        (TYPE_RETAKE, "Retake"),
        (TYPE_SUPPLEMENTARY, "Supplementary"),
    ]

    course_unit = models.ForeignKey(
        "Programs.CourseUnit",
        on_delete=models.CASCADE,
        related_name="exam_sessions",
    )
    session_type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default=TYPE_REGULAR,
        db_index=True,
    )
    title = models.CharField(max_length=200, blank=True, default="")
    exam_date = models.DateField()
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    venue = models.ForeignKey(
        "Programs.Venue",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="exam_sessions",
    )
    venue_text = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Free-text room if not using the venue register.",
    )
    max_candidates = models.PositiveIntegerField(null=True, blank=True)
    is_published = models.BooleanField(
        default=False,
        help_text="When true, students enrolled on this course can see the session.",
    )
    notes = models.TextField(blank=True, default="")
    invigilators = models.ManyToManyField(
        "staff.StaffProfile",
        blank=True,
        related_name="exam_sessions_invigilating",
        help_text="Staff assigned to invigilate this sitting.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_exam_sessions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["exam_date", "start_time", "id"]
        permissions = [
            ("manage_exam_schedule", "Can manage examination timetable and sittings"),
        ]

    def __str__(self):
        label = self.title or self.get_session_type_display()
        return f"{self.course_unit_id} — {label} ({self.exam_date})"


class ExamRetakeRegistration(models.Model):
    """Student retake / supplementary registration for a course enrollment."""

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_SCHEDULED = "scheduled"
    STATUS_COMPLETED = "completed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_SCHEDULED, "Scheduled"),
        (STATUS_COMPLETED, "Completed"),
    ]

    enrollment = models.ForeignKey(
        "Programs.StudentCourseUnitEnrollment",
        on_delete=models.CASCADE,
        related_name="exam_retake_registrations",
    )
    exam_session = models.ForeignKey(
        ExamSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="retake_registrations",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    reason = models.TextField(blank=True, default="")
    admin_notes = models.TextField(blank=True, default="")
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_exam_retakes",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-requested_at"]
        permissions = [
            ("manage_retakes", "Can approve and schedule examination retakes"),
        ]

    def __str__(self):
        return f"Retake #{self.pk} enrollment={self.enrollment_id} ({self.status})"


class ResultChangeRequest(models.Model):
    """Post-publish mark change (ARMS result_approval pattern)."""

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]

    result = models.ForeignKey(
        CourseUnitResult,
        on_delete=models.CASCADE,
        related_name="change_requests",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="result_change_requests_made",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="result_change_requests_reviewed",
    )
    reason = models.TextField()
    review_notes = models.TextField(blank=True, default="")

    old_ca_mark = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    old_exam_mark = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    old_final_mark = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    old_grade_letter = models.CharField(max_length=5, blank=True, default="")

    new_ca_mark = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    new_exam_mark = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-requested_at"]
        permissions = [
            ("approve_result_changes", "Can approve post-publish result changes"),
        ]

    def __str__(self):
        return f"Change request #{self.pk} result={self.result_id} ({self.status})"


class ExamCardToken(models.Model):
    """Scannable pass for examination block entry; verify URL shows live payment status."""

    student = models.ForeignKey(
        "admissions.AdmittedStudent",
        on_delete=models.CASCADE,
        related_name="exam_card_tokens",
    )
    verification_code = models.UUIDField(unique=True, db_index=True, editable=False)
    exam_period_label = models.CharField(max_length=120, blank=True, default="")
    issued_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_revoked = models.BooleanField(default=False)

    class Meta:
        ordering = ["-issued_at"]

    def __str__(self):
        return f"Exam card {self.verification_code} ({self.student_id})"


class MarksEntryWindow(models.Model):
    """Controls when lecturers may enter marks for a batch, semester, or course."""

    name = models.CharField(max_length=160)
    program_batch = models.ForeignKey(
        "Programs.ProgramBatch",
        on_delete=models.CASCADE,
        related_name="marks_entry_windows",
    )
    semester = models.ForeignKey(
        "Programs.Semester",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="marks_entry_windows",
    )
    course_unit = models.ForeignKey(
        "Programs.CourseUnit",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="marks_entry_windows",
    )
    opens_at = models.DateTimeField(null=True, blank=True)
    closes_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_marks_entry_windows",
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="closed_marks_entry_windows",
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_active", "program_batch__name", "semester__order", "course_unit__code"]
        permissions = [
            ("manage_marks_windows", "Can open and close examination marks entry windows"),
        ]
        indexes = [
            models.Index(fields=["program_batch", "semester", "course_unit", "is_active"]),
            models.Index(fields=["opens_at", "closes_at"]),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        if self.course_unit_id and self.course_unit.program_batch_id != self.program_batch_id:
            raise ValidationError(
                {"course_unit": "Course unit must belong to the selected programme batch."}
            )
        if self.semester_id and self.course_unit_id and self.course_unit.semester_id != self.semester_id:
            raise ValidationError(
                {"course_unit": "Course unit must belong to the selected semester."}
            )
        if self.opens_at and self.closes_at and self.opens_at >= self.closes_at:
            raise ValidationError({"closes_at": "Closing time must be after opening time."})
