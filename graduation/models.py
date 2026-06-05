from django.conf import settings
from django.db import models


class GraduationCeremony(models.Model):
    """Top-level congregation (e.g. July 2026 Graduation)."""

    name = models.CharField(max_length=200)
    completion_date = models.DateField(
        help_text="Month/year of completion shown on documents.",
    )
    show_marks_on_transcript = models.BooleanField(
        default=True,
        help_text="When true, transcripts printed for this ceremony include numeric marks.",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_graduation_ceremonies",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-completion_date", "name"]
        verbose_name_plural = "Graduation ceremonies"
        permissions = [
            ("manage_ceremonies", "Can manage graduation ceremonies and sessions"),
        ]

    def __str__(self):
        return self.name


class GraduationSession(models.Model):
    """Ceremony day / sitting (ARMS GraduationDetail)."""

    ceremony = models.ForeignKey(
        GraduationCeremony,
        on_delete=models.CASCADE,
        related_name="sessions",
    )
    name = models.CharField(max_length=200, help_text="e.g. Day 1 — Business")
    graduation_date = models.DateField()
    venue = models.CharField(max_length=200, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["graduation_date", "name"]
        permissions = [
            ("assign_students", "Can assign students to graduation sessions"),
        ]

    def __str__(self):
        return f"{self.ceremony.name} — {self.name}"


class GraduationAssignment(models.Model):
    """Student assigned to walk on a graduation day."""

    session = models.ForeignKey(
        GraduationSession,
        on_delete=models.CASCADE,
        related_name="assignments",
    )
    student = models.ForeignKey(
        "admissions.AdmittedStudent",
        on_delete=models.CASCADE,
        related_name="graduation_assignments",
    )
    cgpa_at_assignment = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )
    credit_units_at_assignment = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
    )
    award_class = models.CharField(max_length=80, blank=True, default="")
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="graduation_assignments_made",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    enrollment_completed = models.BooleanField(
        default=False,
        help_text="When true, programme enrollment was set to completed.",
    )

    class Meta:
        ordering = ["session__graduation_date", "student__reg_no"]
        unique_together = [("session", "student")]
        permissions = [
            ("view_qualified_lists", "Can view graduation qualified lists"),
            ("view_graduation_lists", "Can view printable graduation lists"),
        ]

    def __str__(self):
        return f"{self.student_id} → {self.session_id}"
