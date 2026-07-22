from decimal import Decimal

from django.conf import settings
from django.db import models

from accounts.models import Campus, User
from admissions.models import AcademicLevel, Batch, Program
# NEW: Programs.ProgramBatch / Semester (academic cohort & term), for semester tuition rules
from Programs.models import ProgramBatch, Semester

class ApplicationPayment(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PAID', 'Paid'),
        ('FAILED', 'Failed'),
    ]
    application = models.OneToOneField('admissions.Application', on_delete=models.CASCADE, related_name='payment', null=True, blank=True)

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    external_reference = models.CharField(max_length=50, unique=True)  
    payment_reference = models.CharField(max_length=50, blank=True, null=True)  

    amount = models.DecimalField(max_digits=10, decimal_places=2)
    phone_number = models.CharField(max_length=20)
    fee_type = models.CharField(max_length=40, default='Application Fees')

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')

    receipt_number = models.CharField(max_length=50, blank=True, null=True)
    transaction_id = models.CharField(max_length=50, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
   
class ApplicationFee(models.Model):
    fee_type = models.CharField(max_length=100)
    nationality_type = models.CharField(max_length=40)
    academic_level = models.ManyToManyField(AcademicLevel)
    amount = models.DecimalField(max_digits=50, decimal_places=2)
    admission_period = models.ForeignKey(Batch, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.nationality_type} - {self.academic_level}: {self.amount}"

class FeeHead(models.Model):
    """Catalog entry for a fee type (e.g. TUITION_FEE, FUNCTIONAL_FEE). NEW MODULE."""
    CATEGORY_CHOICES = [
        ('application', 'Application'),
        ('tuition', 'Tuition'),
        ('registration', 'Registration'),
        ('retake', 'Retake / resit'),
        ('exam', 'Examination'),
        ('service', 'Service / administrative'),
        ('other', 'Other'),
    ]

    code = models.CharField(max_length=20, unique=True, help_text="Unique code e.g., TUITION_FEE")
    name = models.CharField(max_length=100, help_text="Fee name")
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        default='other',
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category', 'name']
        verbose_name = "Fee Head"
        verbose_name_plural = "Fee Heads"

    def __str__(self):
        return f"{self.code} - {self.name}"


class FeePlan(models.Model):
    """Groups fee rules; tuition plans often one per program (plan_type=tuition). NEW MODULE."""
    PLAN_TYPE_CHOICES = [
        ('application', 'Application fees'),
        ('tuition', 'Tuition'),
        ('general', 'General / service fees'),
        ('other_schedule', 'Scheduled other fees (year/term milestones)'),
    ]
    PLAN_SCOPE_CHOICES = [
        ('program', 'Program'),
        ('intake', 'Intake/Batch'),
        ('class', 'Class'),
        ('term', 'Term/Semester'),
    ]
    FEE_PLAN_STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('approved', 'Approved'),
        ('inactive', 'Inactive'),
    ]

    plan_type = models.CharField(max_length=20, choices=PLAN_TYPE_CHOICES)
    name = models.CharField(max_length=200)
    term = models.CharField(max_length=50, blank=True, default='')
    scope = models.CharField(
        max_length=20,
        choices=PLAN_SCOPE_CHOICES,
        default='intake',
    )
    status = models.CharField(
        max_length=20,
        choices=FEE_PLAN_STATUS_CHOICES,
        default='draft',
    )
    version = models.IntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_fee_plans',
    )

    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, null=True, blank=True, related_name='fee_plans')
    nationality_type = models.CharField(max_length=20, blank=True, null=True)
    academic_levels = models.ManyToManyField(AcademicLevel, blank=True, related_name='fee_plans')

    program = models.ForeignKey(
        Program,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='fee_plans',
    )
    programs = models.ManyToManyField(
        Program,
        blank=True,
        related_name='fee_plan_programs',
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Fee Plan"
        verbose_name_plural = "Fee Plans"

    def __str__(self):
        return f"{self.name} ({self.get_plan_type_display()})"


class FeePlanRule(models.Model):
    """One amount line: fee_head + program_batch + semester (+ optional course_unit). NEW MODULE."""
    TRIGGER_STAGE_CHOICES = [
        ('form_submission', 'On Form Submission'),
        ('admission_approved', 'On Admission Approval'),
        ('semester_start', 'On Semester Start'),
        ('course_enrollment', 'On Course Enrollment'),
        ('course_retake', 'Course retake / resit'),
    ]

    fee_plan = models.ForeignKey(FeePlan, on_delete=models.CASCADE, related_name='rules')
    fee_head = models.ForeignKey(FeeHead, on_delete=models.CASCADE, related_name='rules')
    trigger_stage = models.CharField(max_length=30, choices=TRIGGER_STAGE_CHOICES, default='form_submission')

    campus = models.ForeignKey(Campus, on_delete=models.SET_NULL, null=True, blank=True)
    program = models.ForeignKey(Program, on_delete=models.SET_NULL, null=True, blank=True)

    program_batch = models.ForeignKey(
        ProgramBatch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    semester = models.ForeignKey(
        Semester,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    course_unit = models.ForeignKey(
        'Programs.CourseUnit',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='fee_plan_rules',
    )

    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='UGX')
    amount_international = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    currency_international = models.CharField(max_length=3, blank=True, default='')

    installment_number = models.PositiveIntegerField(null=True, blank=True)
    due_date_days = models.IntegerField(null=True, blank=True)
    billing_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date this fee becomes visible and billable on the student portal.",
    )

    payable_year_of_study = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="When set with payable_term_number, fee is due at this curriculum year/term.",
    )
    payable_term_number = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Term within payable_year_of_study (1-based).",
    )

    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['fee_plan', 'order', 'installment_number']
        verbose_name = "Fee Plan Rule"
        verbose_name_plural = "Fee Plan Rules"

    def __str__(self):
        return f"{self.fee_plan.name} - {self.fee_head.name} ({self.amount})"


# --- Semester tuition billing: recorded payments + registration policy (singleton settings) ---

# tution Leder
class TuitionLedger(models.Model):

    STATUS_CHOICES = (
        ("Completed", "Completed"),
        ("Pending", "Pending"),
        ("Failed", "Failed"),
        ("Reversed", "Reversed"),
    )

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    student = models.ForeignKey(
        'admissions.AdmittedStudent',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tuition_ledgers'
    )

    amount = models.DecimalField(max_digits=12, decimal_places=2)

    payment_date_time = models.DateTimeField()

    schoolpay_receipt_number = models.CharField(
        max_length=100,
        unique=True,
        db_index=True
    )

    settlement_bank_code = models.CharField(max_length=50, null=True, blank=True)

    source_channel_trans_detail = models.TextField(blank=True)

    source_channel_transaction_id = models.CharField(
        max_length=100,
        db_index=True
    )

    source_payment_channel = models.CharField(max_length=100)

    student_name = models.CharField(max_length=255)

    student_payment_code = models.CharField(
        max_length=100,
        db_index=True
    )

    student_registration_number = models.CharField(
        max_length=100,
        blank=True
    )

    transaction_completion_status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES
    )

    raw_response = models.JSONField(default=dict)

    synced_at = models.DateTimeField(auto_now_add=True)

    reconciled = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-payment_date_time']
        indexes = [
            models.Index(fields=['student_payment_code']),
            models.Index(fields=['schoolpay_receipt_number']),
        ]

    def __str__(self):
        return f"{self.student_name} - {self.amount}"

#student tution payment records (one per payment attempt, including failed/waived)  
class StudentTuitionPayment(models.Model):
    PAYMENT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]
    PAYMENT_METHOD_CHOICES = [
        ('mobile_money', 'Mobile Money'),
        ('bank_transfer', 'Bank Transfer'),
        ('cash', 'Cash'),
        ('other', 'Other'),
    ]
    SOURCE_CHOICES = [
        ('scheduled', 'Scheduled (semester fee)'),
        ('ad_hoc', 'Ad-hoc (individual charge)'),
        ('scholarship', 'Scholarship credit'),
    ]

    student = models.ForeignKey(
        'admissions.AdmittedStudent',
        on_delete=models.CASCADE,
        related_name='tuition_payments',
    )
    fee_plan_rule = models.ForeignKey(
        FeePlanRule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='student_payments',
    )
    semester = models.ForeignKey(
        Semester,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tuition_payments',
    )

    # --- ad-hoc charge fields (null for scheduled fees) ---
    source = models.CharField(max_length=12, choices=SOURCE_CHOICES, default='scheduled')
    fee_head = models.ForeignKey(
        FeeHead,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ad_hoc_payments',
        help_text="For ad-hoc charges: the fee category (retake, service, etc.). NULL for scheduled.",
    )
    label = models.CharField(
        max_length=200,
        blank=True,
        help_text="Human-readable description e.g. 'Late registration penalty – Sem 2 2025'",
    )
    charged_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='issued_charges',
        help_text="Staff member who created this ad-hoc charge.",
    )
    is_waived = models.BooleanField(default=False, help_text="Soft-cancel: charge exists but is not owed.")
    waived_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='waived_charges',
    )
    waived_at = models.DateTimeField(null=True, blank=True)

    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='UGX')
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, blank=True, default='')
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')

    transaction_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    payment_reference = models.CharField(max_length=100, blank=True)
    receipt_number = models.CharField(max_length=100, blank=True)

    paid_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_tuition_payments',
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Student Tuition Payment"
        verbose_name_plural = "Student Tuition Payments"

    def __str__(self):
        return f"{self.student.student_id} - {self.amount} {self.currency} ({self.status})"


class RegistrationSettings(models.Model):
    """Singleton-style registration policy (min tuition %, windows, gates)."""
    min_tuition_payment_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=50.00,
        help_text="Minimum % of semester tuition that must be paid before course registration",
    )
    registration_start_date = models.DateTimeField(null=True, blank=True)
    registration_end_date = models.DateTimeField(null=True, blank=True)
    require_admission_approval = models.BooleanField(default=True)
    require_enrollment = models.BooleanField(
        default=True,
        help_text="Require student to have an admission intake batch assigned (legacy gate).",
    )
    require_programme_enrollment = models.BooleanField(
        default=True,
        help_text=(
            "Require student to have an active StudentProgrammeEnrollment "
            "(status='enrolled', i.e. commitment fee confirmed). "
            "This is the main academic enrollment gate."
        ),
    )
    skip_tuition_check = models.BooleanField(
        default=False,
        help_text=(
            "When True, the minimum tuition payment percentage threshold is skipped entirely. "
            "Students can register regardless of how much tuition they have paid."
        ),
    )
    is_active = models.BooleanField(default=True, help_text="Master switch for course registration")
    auto_enroll_on_admission = models.BooleanField(
        default=False,
        help_text=(
            "When enabled, students are automatically academically enrolled on admission "
            "(skips commitment fee gate)."
        ),
    )
    auto_assign_course_units_after_commitment = models.BooleanField(
        default=True,
        help_text=(
            "When enabled, commitment-based enrollment activation also auto-assigns "
            "active course units for the student's current batch semester."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_registration_settings',
    )

    class Meta:
        verbose_name = "Registration Settings"
        verbose_name_plural = "Registration Settings"

    def __str__(self):
        return f"Registration Settings ({self.min_tuition_payment_percentage}% min tuition)"

    def save(self, *args, **kwargs):
        if not self.pk and RegistrationSettings.objects.exists():
            existing = RegistrationSettings.objects.first()
            existing.min_tuition_payment_percentage = self.min_tuition_payment_percentage
            existing.registration_start_date = self.registration_start_date
            existing.registration_end_date = self.registration_end_date
            existing.require_admission_approval = self.require_admission_approval
            existing.require_enrollment = self.require_enrollment
            existing.require_programme_enrollment = self.require_programme_enrollment
            existing.skip_tuition_check = self.skip_tuition_check
            existing.is_active = self.is_active
            existing.auto_enroll_on_admission = self.auto_enroll_on_admission
            existing.auto_assign_course_units_after_commitment = self.auto_assign_course_units_after_commitment
            existing.updated_by = self.updated_by
            return existing.save(*args, **kwargs)
        return super().save(*args, **kwargs)

    @classmethod
    def get_settings(cls):
        settings, _ = cls.objects.get_or_create(
            defaults={
                'min_tuition_payment_percentage': 50.00,
                'require_admission_approval': True,
                'require_enrollment': True,
                'require_programme_enrollment': True,
                'skip_tuition_check': False,
                'is_active': True,
                'auto_enroll_on_admission': False,
                'auto_assign_course_units_after_commitment': True,
            }
        )
        return settings


# ---------------------------------------------------------------------------
# Scholarships (programmes, student awards, fee-head waivers → ledger credits)
# ---------------------------------------------------------------------------


class ScholarshipProgramme(models.Model):
    """Named scholarship pot, e.g. State House, HESFB, Sports."""

    name = models.CharField(max_length=150)
    code = models.CharField(
        max_length=40,
        unique=True,
        help_text="Unique code e.g. STATE_HOUSE, HESFB, SPORTS",
    )
    sponsor = models.CharField(max_length=150, blank=True, default="")
    description = models.TextField(blank=True, default="")
    fund_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Optional programme ceiling. Null = no hard cap.",
    )
    currency = models.CharField(max_length=3, default="UGX")
    academic_year = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="e.g. 2025/2026",
    )
    # by_programme = use programme_rates as default amounts (HESFB);
    # per_student = each award amount entered manually (Sports).
    AWARDING_BY_PROGRAMME = "by_programme"
    AWARDING_PER_STUDENT = "per_student"
    AWARDING_MODE_CHOICES = [
        (AWARDING_BY_PROGRAMME, "By academic programme (rate table)"),
        (AWARDING_PER_STUDENT, "Per student (manual amount)"),
    ]
    awarding_mode = models.CharField(
        max_length=20,
        choices=AWARDING_MODE_CHOICES,
        default=AWARDING_PER_STUDENT,
        help_text="HESFB-style rates vs Sports-style per-student amounts.",
    )
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_scholarship_programmes",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Scholarship programme"
        verbose_name_plural = "Scholarship programmes"

    def __str__(self):
        return f"{self.code} — {self.name}"


class ScholarshipProgrammeWaiver(models.Model):
    """Default fee-head waiver template copied onto awards when a student is attached."""

    WAIVER_FULL = "full"
    WAIVER_PERCENT = "percent"
    WAIVER_MODE_CHOICES = [
        (WAIVER_FULL, "Entire fee (100%)"),
        (WAIVER_PERCENT, "Percentage of fee"),
    ]

    programme = models.ForeignKey(
        ScholarshipProgramme,
        on_delete=models.CASCADE,
        related_name="default_waivers",
    )
    fee_head = models.ForeignKey(
        FeeHead,
        on_delete=models.PROTECT,
        related_name="scholarship_programme_waivers",
    )
    waiver_mode = models.CharField(
        max_length=10,
        choices=WAIVER_MODE_CHOICES,
        default=WAIVER_FULL,
    )
    percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Required when waiver_mode=percent (e.g. 50.00).",
    )

    class Meta:
        unique_together = [("programme", "fee_head")]
        ordering = ["fee_head__code"]
        verbose_name = "Scholarship programme waiver"
        verbose_name_plural = "Scholarship programme waivers"

    def __str__(self):
        return f"{self.programme.code} / {self.fee_head.code} ({self.waiver_mode})"


class ScholarshipProgrammeRate(models.Model):
    """Amount this scholarship pays for a given academic programme (e.g. HESFB Engineering 3.5M)."""

    scholarship = models.ForeignKey(
        ScholarshipProgramme,
        on_delete=models.CASCADE,
        related_name="programme_rates",
    )
    academic_program = models.ForeignKey(
        Program,
        on_delete=models.CASCADE,
        related_name="scholarship_rates",
        help_text="Student's admitted academic programme (e.g. BSc Computer Science).",
    )
    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        help_text="Award amount for students on this academic programme.",
    )
    notes = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        unique_together = [("scholarship", "academic_program")]
        ordering = ["academic_program__name"]
        verbose_name = "Scholarship programme rate"
        verbose_name_plural = "Scholarship programme rates"

    def __str__(self):
        return f"{self.scholarship.code} / {self.academic_program} = {self.amount}"


class ScholarshipAward(models.Model):
    """A student attached to a scholarship programme with an award ceiling."""

    STATUS_ACTIVE = "active"
    STATUS_REVOKED = "revoked"
    STATUS_EXHAUSTED = "exhausted"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_REVOKED, "Revoked"),
        (STATUS_EXHAUSTED, "Exhausted"),
    ]

    programme = models.ForeignKey(
        ScholarshipProgramme,
        on_delete=models.CASCADE,
        related_name="awards",
    )
    student = models.ForeignKey(
        "admissions.AdmittedStudent",
        on_delete=models.CASCADE,
        related_name="scholarship_awards",
    )
    award_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        help_text="Maximum credit this student may receive from this award.",
    )
    currency = models.CharField(max_length=3, default="UGX")
    status = models.CharField(
        max_length=12,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
        db_index=True,
    )
    notes = models.TextField(blank=True, default="")
    applied_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Sum of active (non-reversed) scholarship credits posted.",
    )
    awarded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="issued_scholarship_awards",
    )
    awarded_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revoked_scholarship_awards",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-awarded_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["programme", "student"],
                condition=models.Q(status="active"),
                name="uniq_active_scholarship_award_per_student",
            ),
        ]
        verbose_name = "Scholarship award"
        verbose_name_plural = "Scholarship awards"

    def __str__(self):
        return f"{self.programme.code} → {self.student_id} ({self.status})"

    @property
    def remaining_amount(self):
        rem = (self.award_amount or Decimal("0")) - (self.applied_amount or Decimal("0"))
        return rem if rem > 0 else Decimal("0")


class ScholarshipAwardWaiver(models.Model):
    """Per-award fee-head waiver (entire or %)."""

    award = models.ForeignKey(
        ScholarshipAward,
        on_delete=models.CASCADE,
        related_name="waivers",
    )
    fee_head = models.ForeignKey(
        FeeHead,
        on_delete=models.PROTECT,
        related_name="scholarship_award_waivers",
    )
    waiver_mode = models.CharField(
        max_length=10,
        choices=ScholarshipProgrammeWaiver.WAIVER_MODE_CHOICES,
        default=ScholarshipProgrammeWaiver.WAIVER_FULL,
    )
    percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )

    class Meta:
        unique_together = [("award", "fee_head")]
        ordering = ["fee_head__code"]
        verbose_name = "Scholarship award waiver"
        verbose_name_plural = "Scholarship award waivers"

    def __str__(self):
        return f"Award {self.award_id} / {self.fee_head.code}"


class ScholarshipCredit(models.Model):
    """Ledger credit posted for an award (backed by a completed StudentTuitionPayment)."""

    award = models.ForeignKey(
        ScholarshipAward,
        on_delete=models.CASCADE,
        related_name="credits",
    )
    fee_head = models.ForeignKey(
        FeeHead,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scholarship_credits",
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3, default="UGX")
    payment = models.OneToOneField(
        StudentTuitionPayment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scholarship_credit",
    )
    applied_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="applied_scholarship_credits",
    )
    applied_at = models.DateTimeField(auto_now_add=True)
    is_reversed = models.BooleanField(default=False)
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reversed_scholarship_credits",
    )
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-applied_at"]
        verbose_name = "Scholarship credit"
        verbose_name_plural = "Scholarship credits"

    def __str__(self):
        return f"Credit {self.amount} on award {self.award_id}"












