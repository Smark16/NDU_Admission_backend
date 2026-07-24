from django.db import models
from django.db.models import Q
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from accounts.models import User, Campus
from Programs.models import Program
from .utils.academic_year import get_default_academic_year_label
from .utils.reference import generate_reference

class Faculty(models.Model):
    name = models.CharField(max_length=200, unique=True)
    code = models.CharField(max_length=30, unique=True)
    campuses = models.ManyToManyField(Campus, related_name='faculties', blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Faculties"
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.code})"

class AcademicLevel(models.Model):
    name = models.CharField(max_length=50, unique=True)
    created_at = models.DateField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class AcademicYear(models.Model):
    """
    Canonical academic year labels (e.g. 2025/2026) used on intake and programme batches.
    """

    label = models.CharField(max_length=25, unique=True)
    is_current = models.BooleanField(
        default=False,
        help_text="Default year suggested when creating new batches.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Inactive years stay on old records but cannot be selected for new batches.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-label"]
        verbose_name = "Academic year"
        verbose_name_plural = "Academic years"

    def __str__(self):
        mark = " (current)" if self.is_current else ""
        return f"{self.label}{mark}"

    def save(self, *args, **kwargs):
        from .utils.academic_year import normalize_academic_year_label

        self.label = normalize_academic_year_label(self.label)
        super().save(*args, **kwargs)
        if self.is_current:
            AcademicYear.objects.filter(is_current=True).exclude(pk=self.pk).update(
                is_current=False
            )


class Batch(models.Model):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=40)
    programs = models.ManyToManyField(Program, related_name='batches')
    academic_year = models.CharField(max_length=25, blank=True)
    application_start_date = models.DateField()
    application_end_date = models.DateField()
    admission_start_date = models.DateField()
    admission_end_date = models.DateField()
    offer_start_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date from which admission offers become active for this batch.",
    )
    offer_end_date = models.DateField(
        null=True,
        blank=True,
        help_text=(
            "Date after which admission offers for this batch expire and the batch "
            "is no longer shown as active."
        ),
    )
    is_active = models.BooleanField(default=False)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_batches')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.academic_year:
            self.academic_year = get_default_academic_year_label()

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.code})"

    @property
    def is_application_open(self):
        from django.utils import timezone
        now = timezone.now()
        return self.application_start_date <= now <= self.application_end_date

    @property
    def is_offer_active(self):
        """True when today falls inside this intake's offer window (null bounds = always active)."""
        from admissions.utils.batch_offer_filters import dates_in_offer_window

        return dates_in_offer_window(self.offer_start_date, self.offer_end_date)

class OLevelSubject(models.Model):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=100)

    class Meta:
        ordering = ['name']
        verbose_name = "O-Level Subject"
        verbose_name_plural = "O-Level Subjects"

    def __str__(self):
        return f"{self.name} ({self.code})"

class ALevelSubject(models.Model):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=100)

    class Meta:
        ordering = ['name']
        verbose_name = "A-Level Subject"
        verbose_name_plural = "A-Level Subjects"

    def __str__(self):
        return f"{self.name} ({self.code})"

class Application(models.Model): 
    applicant = models.ForeignKey(User, on_delete=models.CASCADE, related_name='applications')
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name='applications')
    campus = models.ForeignKey(Campus, on_delete=models.CASCADE, related_name='applications')
    academic_level = models.ForeignKey(AcademicLevel, on_delete=models.CASCADE)
    # Personal Information
    first_name = models.CharField(max_length=100)
    title = models.CharField(max_length=100, null=True, blank=True)
    last_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    date_of_birth = models.DateField()
    gender = models.CharField(max_length=20)
    nationality = models.CharField(max_length=100)
    applicant_category = models.CharField(
        max_length=20,
        choices=[
            ("local", "Local"),
            ("international", "International"),
        ],
        default="local",
    )
    phone = models.CharField(max_length=20)
    email = models.EmailField()
    address = models.TextField(max_length=255, blank=True, null=True)
    nin = models.CharField(max_length=20, blank=True, null=True)
    passport_number = models.CharField(max_length=20, blank=True, null=True)
    disabled = models.CharField(max_length=5, null=True, blank=True)
    is_refugee = models.BooleanField(default=False)
    refugee_status_proof = models.FileField(upload_to='refugee_proofs/', blank=True, null=True)

    # Next of Kin Information
    next_of_kin_name = models.CharField(max_length=200)
    next_of_kin_contact = models.CharField(max_length=25)
    next_of_kin_relationship = models.CharField(max_length=20)
    
    # O-Level Information
    olevel_year = models.PositiveIntegerField(null=True, blank=True)
    olevel_index_number = models.CharField(max_length=50, null=True, blank=True)
    olevel_school = models.CharField(max_length=200, null=True, blank=True)
    
    # O-Level / A-Level flags (column exists in DB; must be set explicitly on every INSERT)
    has_olevel = models.BooleanField(default=False)
    has_alevel = models.BooleanField(default=False)
    alevel_year = models.PositiveIntegerField(null=True, blank=True)
    alevel_index_number = models.CharField(max_length=50, null=True, blank=True)
    alevel_school = models.CharField(max_length=200, null=True, blank=True)
    alevel_combination = models.CharField(max_length=10, null=True, blank=True)
    
    # Source / audit tracing (direct entry, legacy migration, portal)
    SOURCE_PORTAL = 'portal'
    SOURCE_DIRECT = 'direct_entry'
    SOURCE_LEGACY = 'legacy_import'
    SOURCE_CHOICES = [
        (SOURCE_PORTAL, 'Applicant Portal'),
        (SOURCE_DIRECT, 'Direct Entry'),
        (SOURCE_LEGACY, 'Legacy Import'),
    ]
    source = models.CharField(max_length=30, choices=SOURCE_CHOICES, default=SOURCE_PORTAL)
    legacy_application_number = models.CharField(max_length=100, blank=True, null=True)
    # Staff wizard (multi-step direct application) — mirrors admission portal v2
    is_direct_entry = models.BooleanField(default=False)
    entered_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entered_applications",
    )

    # Document uploads — passport_photo nullable so direct/legacy entry works without an upload
    passport_photo = models.ImageField(upload_to='passport_photos/', blank=True, null=True)
    payment_proof = models.FileField(upload_to='payment_proofs/', blank=True, null=True, help_text="Payment Proof (PDF)")
   
    # Application Status
    status = models.CharField(max_length=20, default='draft')
    pending_reason = models.TextField(max_length=255, blank=True, null=True)
    application_reference = models.CharField(max_length=50, unique=True, blank=True, null=True)
    school_pay_reference = models.CharField(max_length=100, blank=True, null=True)
    application_fee_paid = models.BooleanField(default=False)
    application_fee_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Review Information
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_applications')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)

    # revocation
    is_revoked = models.BooleanField(default=False)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revoked_admissions",
    )
    revocation_reason = models.TextField(blank=True, default="")

    admission_letter_docx = models.FileField(upload_to="admission_template/", null=True, blank=True)
    admission_letter_pdf = models.FileField(upload_to="admission_template/", null=True, blank=True)
    offer_letter_status = models.CharField(max_length=20, default='pending')
    offer_letter_progress = models.IntegerField(default=0)
    # Offer letter authenticity (QR + public verify page)
    offer_letter_verification_token = models.CharField(
        max_length=64, unique=True, null=True, blank=True, db_index=True
    )
    offer_letter_generated_at = models.DateTimeField(null=True, blank=True)
    offer_letter_generated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_offer_letters",
    )

    program_choices_verification_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the applicant was asked to review/confirm programme choices (e.g. bulk email).",
    )
    program_choices_confirmed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When programme choices were confirmed in the portal (applicant or staff).",
    )
    program_choices_confirmed_by = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text="Who confirmed: applicant (portal) or staff (change programme). Empty = legacy.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        default_permissions = ('add', 'change', 'delete', 'view')
        permissions = [
            (
                'approve_application',
                'Can approve applications (mark accepted for admission processing)',
            ),
            ('reject_application', 'Can reject applications'),
            (
                'admit_applicant',
                'Can admit applicants (create or finalize admission records)',
            ),
            (
                'edit_application_registration',
                'Can edit applicant registration data and programme choices (admin)',
            ),
        ]

        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['applicant']),
            models.Index(fields=['batch'])
        ]

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.middle_name} {self.last_name}".strip()

# program choices
class ApplicationProgramChoice(models.Model):
    application = models.ForeignKey("Application", on_delete=models.CASCADE, related_name="program_choices")

    program = models.ForeignKey("Programs.Program", on_delete=models.CASCADE)

    choice_order = models.PositiveIntegerField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["choice_order"]
        unique_together = ("application", "choice_order")

    def __str__(self):
        return f"{self.application.id} - Choice {self.choice_order} - {self.program.name}"

class OLevelResult(models.Model):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='olevel_results')
    subject = models.ForeignKey(OLevelSubject, on_delete=models.CASCADE)
    grade = models.CharField(max_length=10)

    class Meta:
        ordering = ['subject__name']
        unique_together = ['application', 'subject']
        verbose_name = "O-Level Result"
        verbose_name_plural = "O-Level Results"

        indexes = [
            models.Index(fields=['application'])
        ]

    def __str__(self):
        return f"{self.application.full_name} - {self.subject.name}: {self.grade}"

class ALevelResult(models.Model):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='alevel_results')
    subject = models.ForeignKey(ALevelSubject, on_delete=models.CASCADE)
    grade = models.CharField(max_length=10)

    class Meta:
        ordering = ['subject__name']
        unique_together = ['application', 'subject']
        verbose_name = "A-Level Result"
        verbose_name_plural = "A-Level Results"

        indexes = [
            models.Index(fields=['application'])
        ]

    def __str__(self):
        return f"{self.application.full_name} - {self.subject.name}: {self.grade}"

class ApplicationDocument(models.Model): 
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='documents')
    name = models.CharField(max_length=25, null=True, blank=True)
    document_type = models.CharField(max_length=30)
    file_url = models.URLField(max_length=100, null=True, blank=True)
    file = models.FileField(upload_to='application_documents/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']

        indexes = [
            models.Index(fields=['application'])
        ]

class AdditionalQualifications(models.Model):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='additionals', null=True, blank=True)
    additional_qualification_institution = models.CharField(max_length=200, blank=True, help_text="Institution Name")
    additional_qualification_type = models.CharField(max_length=30, blank=True)
    additional_qualification_year = models.CharField(max_length=100, blank=True, null=True, help_text="Award Year")
    class_of_award = models.CharField(max_length=200, blank=True, null=True)

class AdmittedStudent(models.Model):
    application = models.OneToOneField(Application, on_delete=models.CASCADE, related_name='admission')
    student_user = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='student_admission')
    student_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    study_mode = models.CharField(max_length=30)
    reg_no = models.CharField(max_length=100, unique=True)
    admitted_program = models.ForeignKey(Program, on_delete=models.CASCADE)
    admitted_batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name='admitted_students')
    admitted_campus = models.ForeignKey(Campus, on_delete=models.CASCADE, related_name='admitted_students')
    intended_program_batch = models.ForeignKey(
        'Programs.ProgramBatch',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='intended_admissions',
        help_text=(
            'The academic cohort this student should be placed in. Set at time of admission.'
        ),
    )
    admitted_specialization = models.ForeignKey(
        'Programs.ProgramSpecialization',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='admitted_students',
        help_text=(
            'Teaching subject combination / programme track selected at admission '
            '(required for programmes with has_specialization=True).'
        ),
    )
    schoolpay_code = models.CharField(max_length=100, unique=True, null=True, blank=True)
    is_registered_with_schoolpay = models.BooleanField(default=False)

    # Admission information
    admission_date = models.DateTimeField(default=timezone.now)
    admission_letter_sent = models.BooleanField(default=False)
    admission_letter_sent_at = models.DateTimeField(null=True, blank=True)
    is_admitted= models.BooleanField(default=False)
    
    # Registration information (official registration only — do not conflate with document checks)
    admission_fee_paid = models.BooleanField(default=False, db_index=True)
    admission_fee_paid_at = models.DateTimeField(
        null=True,
        blank=True
    )
    is_registered = models.BooleanField(default=False)
    registration_date = models.DateTimeField(null=True, blank=True)

    # Physical document verification (original hard-copy check — after accounts clearance)
    physical_documents_verified = models.BooleanField(default=False)
    physical_documents_verified_at = models.DateTimeField(null=True, blank=True)
    physical_documents_verified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="physical_document_verifications",
    )
    physical_documents_notes = models.TextField(
        blank=True,
        help_text="Staff notes when documents were verified at the desk",
    )

    # Accounts clearance for registration card / desk clearance after payment
    # (required for new and continuing students before the portal registration card appears)
    accounts_registration_cleared = models.BooleanField(
        default=False,
        db_index=True,
        help_text=(
            "Accounts confirmed payment and cleared this student. Required before the "
            "student portal registration card is available (new and continuing students)."
        ),
    )
    accounts_registration_cleared_at = models.DateTimeField(null=True, blank=True)
    accounts_registration_cleared_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="accounts_registration_clearances",
    )
    accounts_registration_clearance_notes = models.TextField(blank=True)

    # Notes
    admission_notes = models.TextField(blank=True, help_text="Notes about the admission")
    admitted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='admitted_students')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-admission_date']
        verbose_name = "Admitted Student"
        verbose_name_plural = "Admitted Students"
        permissions = [
            ("verify_physical_documents", "Can verify physical admission documents"),
            ("clear_accounts_registration", "Can clear students for registration after payment"),
            ("revoke_admission", "Can revoke admitted students"),
            ("restore_revoked_admission", "Can restore revoked admissions"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["schoolpay_code"],
                condition=Q(schoolpay_code__isnull=False) & ~Q(schoolpay_code=""),
                name="unique_admittedstudent_schoolpay_code",
            ),
        ]
 
        indexes = [
            models.Index(fields=['application', 'created_at']),
            models.Index(fields=['student_id']),
            models.Index(fields=['is_registered']),
            models.Index(fields=['admitted_batch', 'is_admitted']),
            models.Index(fields=['is_admitted']),
            models.Index(fields=['physical_documents_verified']),
            models.Index(fields=['accounts_registration_cleared']),
            models.Index(
                fields=['is_admitted', 'admission_fee_paid', '-created_at'],
                name='admitted_bonafide_list_idx',
            ),
        ]
    
    def __str__(self):
        return f"{self.application.full_name} - {self.student_id}"

    def save(self, *args, **kwargs):
        if not self.is_registered_with_schoolpay and not (self.schoolpay_code or "").strip():
            self.schoolpay_code = None
        super().save(*args, **kwargs)

    @property
    def effective_schoolpay_code(self):
        gateway_code = (self.schoolpay_code or "").strip()
        if self.is_registered_with_schoolpay and gateway_code:
            return gateway_code
        return (self.reg_no or "").strip()
    
    @property
    def full_name(self):
        if not self.application_id:
            return ""
        try:
            return self.application.full_name
        except Exception:
            return ""
    
    @property
    def email(self):
        if not self.application_id:
            return ""
        try:
            return self.application.email
        except Exception:
            return ""
    
    @property
    def phone(self):
        if not self.application_id:
            return ""
        try:
            return self.application.phone
        except Exception:
            return ""


class StudentPortalAccountAction(models.Model):
    """History of portal login deactivate / activate actions (with reason)."""

    ACTION_DEACTIVATE = "deactivate"
    ACTION_ACTIVATE = "activate"
    ACTION_CHOICES = [
        (ACTION_DEACTIVATE, "Deactivate"),
        (ACTION_ACTIVATE, "Activate"),
    ]

    student = models.ForeignKey(
        AdmittedStudent,
        on_delete=models.CASCADE,
        related_name="portal_account_actions",
    )
    portal_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="student_portal_account_actions_as_subject",
        help_text="The student login user that was toggled.",
    )
    action = models.CharField(max_length=16, choices=ACTION_CHOICES)
    reason = models.TextField()
    performed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="student_portal_account_actions_performed",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Student portal account action"
        verbose_name_plural = "Student portal account actions"

    def __str__(self):
        return f"{self.action} · student={self.student_id} · {self.created_at}"


class StudentIdCard(models.Model):
    """Physical / digital student ID card issuance tied to an admission record."""

    STATUS_GENERATED = "generated"
    STATUS_PRINTED = "printed"
    STATUS_ACTIVE = "active"
    STATUS_REVOKED = "revoked"
    STATUS_REISSUED = "reissued"
    STATUS_CHOICES = [
        (STATUS_GENERATED, "Generated"),
        (STATUS_PRINTED, "Printed"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_REVOKED, "Revoked"),
        (STATUS_REISSUED, "Reissued"),
    ]

    admitted_student = models.ForeignKey(
        AdmittedStudent,
        on_delete=models.CASCADE,
        related_name="id_cards",
    )
    card_number = models.CharField(max_length=48, unique=True, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_GENERATED,
    )
    is_active = models.BooleanField(
        default=True,
        help_text="False when revoked or superseded by a reissue.",
    )
    issue_date = models.DateField(default=timezone.now)
    expiry_date = models.DateField(null=True, blank=True)
    print_count = models.PositiveIntegerField(default=0)
    revoke_reason = models.TextField(blank=True, default="")
    reissue_reason = models.TextField(blank=True, default="")
    replaced_by = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="supersedes",
    )
    issued_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="issued_id_cards",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Student ID card"
        verbose_name_plural = "Student ID cards"
        permissions = [
            (
                "manage_id_cards",
                "Issue, revoke, and reissue student ID cards",
            ),
        ]
        indexes = [
            models.Index(fields=["admitted_student", "is_active"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"{self.card_number} ({self.admitted_student_id})"


class IdCardPdfTemplate(models.Model):
    """PDF ID card blank: map merge fields to coordinates (same idea as offer letter PDF templates)."""

    key = models.SlugField(
        max_length=80,
        unique=True,
        db_index=True,
        help_text="Stable key; must match SystemSettings.active_id_card_template when this layout is active.",
    )
    name = models.CharField(max_length=120)
    template_pdf = models.FileField(upload_to="id_card_templates/", help_text="PDF artwork (e.g. card front)")
    field_positions = models.JSONField(default=dict, blank=True)
    front_title = models.CharField(max_length=200, blank=True, default="")
    institution = models.CharField(max_length=200, blank=True, default="")
    issuer_title = models.CharField(max_length=120, blank=True, default="")
    issuer_signatory = models.CharField(max_length=120, blank=True, default="")
    return_to = models.TextField(blank=True, default="")
    tel = models.CharField(max_length=80, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "ID card PDF template"
        verbose_name_plural = "ID card PDF templates"

    def __str__(self):
        return f"{self.name} ({self.key})"


class AdmissionChangeRequest(models.Model):
    CHANGE_TYPE_CHOICES = [
        ('program', 'Programme Change'),
        ('campus', 'Campus Transfer'),
        ('study_mode', 'Study Mode Change'),
        ('dead_semester', 'Dead Semester'),
        ('dead_year', 'Dead Year'),
        ('exemption', 'Course Exemption'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    admitted_student = models.ForeignKey(
        AdmittedStudent, on_delete=models.CASCADE, related_name='change_requests'
    )
    change_type = models.CharField(max_length=20, choices=CHANGE_TYPE_CHOICES)
    requested_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='submitted_change_requests'
    )

    # Snapshot of current values at time of request
    current_program = models.ForeignKey(
        Program, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    current_campus = models.ForeignKey(
        Campus, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    current_study_mode = models.CharField(max_length=30, blank=True)

    # Requested new values (only the relevant one is filled)
    new_program = models.ForeignKey(
        Program, on_delete=models.SET_NULL, null=True, blank=True, related_name='transfer_requests'
    )
    new_campus = models.ForeignKey(
        Campus, on_delete=models.SET_NULL, null=True, blank=True, related_name='transfer_requests'
    )
    new_study_mode = models.CharField(max_length=30, blank=True)

    # For dead semester / dead year requests
    requested_year = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Year of study being declared dead (e.g. 1, 2, 3)"
    )
    requested_semester = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Semester number being declared dead (e.g. 1 or 2); leave blank for dead year"
    )

    reason = models.TextField(help_text="Student's reason for requesting the change")

    # Exemption form fee (UGX 50,000 one-time access charge)
    form_fee_charge = models.ForeignKey(
        'payments.StudentTuitionPayment',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='exemption_form_fee_for_requests',
        help_text="Ad-hoc charge that unlocks the exemption application form.",
    )
    form_fee_paid_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_change_requests'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True, help_text="Admin notes on approval or rejection")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Admission Change Request"
        verbose_name_plural = "Admission Change Requests"
        default_permissions = ('add', 'change', 'delete', 'view')
        permissions = [
            (
                'manage_admission_change_requests',
                'Can approve or reject admission change requests (programme, campus, etc.)',
            ),
            (
                'approve_exemption_requests',
                'Can approve or reject course exemption change requests',
            ),
        ]

    def __str__(self):
        return f"{self.admitted_student.student_id} — {self.get_change_type_display()} [{self.status}]"


class ExemptionRequestLine(models.Model):
    """Course unit selected on an exemption change request."""

    change_request = models.ForeignKey(
        AdmissionChangeRequest,
        on_delete=models.CASCADE,
        related_name='exemption_lines',
    )
    curriculum_line = models.ForeignKey(
        'Programs.ProgramCurriculumLine',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='exemption_request_lines',
    )
    course_code = models.CharField(max_length=40, blank=True, default='')
    course_name = models.CharField(max_length=255, blank=True, default='')
    year_of_study = models.PositiveSmallIntegerField(null=True, blank=True)
    term_number = models.PositiveSmallIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['year_of_study', 'term_number', 'course_code', 'id']
        verbose_name = "Exemption Request Line"
        verbose_name_plural = "Exemption Request Lines"

    def __str__(self):
        return f"{self.course_code or self.curriculum_line_id} ({self.change_request_id})"


class PortalNotification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=200)
    message = models.TextField(blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

        indexes = [
            models.Index(fields=['recipient']),
        ]

    def __str__(self):
        return f"{self.recipient.email} - {self.title}"


class EmailTemplate(models.Model):
    KEY_APPLICATION_SUBMITTED = "application_submitted"
    KEY_ADMISSION_ACCEPTED = "admission_accepted"
    KEY_ADMISSION_UPDATED = "admission_updated"
    KEY_OFFER_LETTER_SENT = "offer_letter_sent"
    KEY_WEEKLY_ADMISSIONS_DIGEST = "weekly_admissions_digest"

    TEMPLATE_KEY_CHOICES = [
        (KEY_APPLICATION_SUBMITTED, "Application Submitted"),
        (KEY_ADMISSION_ACCEPTED, "Admission Accepted"),
        (KEY_ADMISSION_UPDATED, "Admission Updated"),
        (KEY_OFFER_LETTER_SENT, "Offer Letter Sent"),
        (KEY_WEEKLY_ADMISSIONS_DIGEST, "Weekly Admissions Digest"),
    ]

    key = models.CharField(max_length=80, unique=True, choices=TEMPLATE_KEY_CHOICES)
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    subject_template = models.CharField(max_length=255)
    body_template_html = models.TextField()
    is_active = models.BooleanField(default=True)
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_email_templates",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Email Template"
        verbose_name_plural = "Email Templates"

    def __str__(self):
        return f"{self.name} ({self.key})"


class WeeklyReportSettings(models.Model):
    """Singleton-style configuration for the weekly admissions digest email."""

    WEEKDAY_CHOICES = [
        (0, "Monday"),
        (1, "Tuesday"),
        (2, "Wednesday"),
        (3, "Thursday"),
        (4, "Friday"),
        (5, "Saturday"),
        (6, "Sunday"),
    ]

    is_enabled = models.BooleanField(default=False)
    schedule_day = models.PositiveSmallIntegerField(choices=WEEKDAY_CHOICES, default=0)
    schedule_hour = models.PositiveSmallIntegerField(default=8)
    schedule_minute = models.PositiveSmallIntegerField(default=0)
    last_sent_at = models.DateTimeField(null=True, blank=True)
    last_sent_summary = models.CharField(max_length=255, blank=True, default="")
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_weekly_report_settings",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Weekly report settings"
        verbose_name_plural = "Weekly report settings"

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Weekly admissions digest settings"


class WeeklyReportRecipient(models.Model):
    """Staff email addresses that receive the weekly admissions health digest."""

    email = models.EmailField(unique=True)
    name = models.CharField(max_length=120, blank=True, default="")
    is_active = models.BooleanField(default=True)
    notes = models.CharField(max_length=255, blank=True, default="")
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="weekly_report_recipients_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["email"]
        verbose_name = "Weekly report recipient"
        verbose_name_plural = "Weekly report recipients"

    def __str__(self):
        label = self.name.strip() or self.email
        return label

