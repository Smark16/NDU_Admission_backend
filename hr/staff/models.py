from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from datetime import date, timedelta
from .utils.staff_no import generate_number
from hr.hiring.models import JobApplication

class StaffType(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateField(auto_now_add=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return self.name
    
class PositonLevel(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateField(auto_now_add=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return self.name


class PayScale(models.Model):
    """Ugandan public university / IPPS-style salary scale (e.g. U1–U17, P1–P5)."""

    CATEGORY_CHOICES = [
        ("ACADEMIC", "Academic"),
        ("ADMINISTRATIVE", "Administrative"),
        ("SUPPORT", "Support"),
    ]

    code = models.CharField(max_length=10, unique=True, help_text="Scale code, e.g. U7 or P2")
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="ADMINISTRATIVE")
    rank_order = models.PositiveSmallIntegerField(
        default=0,
        help_text="Lower numbers = junior grades (used for sorting)",
    )
    description = models.TextField(blank=True)
    typical_roles = models.CharField(
        max_length=500,
        blank=True,
        help_text="Example job titles commonly placed on this scale",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateField(auto_now_add=True)

    class Meta:
        ordering = ["rank_order", "code"]
        verbose_name = "Pay scale"
        verbose_name_plural = "Pay scales"

    def __str__(self):
        return f"{self.code} — {self.name}"

class Department(models.Model):
    name = models.CharField(max_length=20)
    code = models.CharField(max_length=10)
    description = models.TextField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
    
class DepartmentTeams(models.Model):
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='teams')
    team_name = models.CharField(max_length=20)
    description = models.TextField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.team_name

# class OrgUnit(models.Model):
#     campus = models.ForeignKey(
#         'accounts.Campus',
#         on_delete=models.CASCADE,
#         related_name='org_units'
#     )
#     name = models.CharField(max_length=200)
#     unit_type = models.ForeignKey(
#         UnitType,
#         on_delete=models.PROTECT,
#         related_name='org_units',
#         help_text="Type of organizational unit"
#     )
#     parent = models.ForeignKey(
#         'self',
#         on_delete=models.SET_NULL,
#         null=True,
#         blank=True,
#         related_name='children',
#         help_text="Parent organizational unit"
#     )
    
#     class Meta:
#         ordering = ['campus', 'name']
#         unique_together = [['campus', 'name']]
    
#     def __str__(self):
#         return f"{self.name} ({self.unit_type.name})"
    
#     def get_all_descendants(self):
#         """
#         Get all descendant org units (children, grandchildren, etc.).
#         Returns a queryset of all org units in the subtree below this unit.
#         """
#         descendants = []
#         children = self.children.all()
#         for child in children:
#             descendants.append(child)
#             # Recursively get descendants of each child
#             descendants.extend(child.get_all_descendants())
#         return descendants
    
#     def get_hierarchy_path(self):
#         """
#         Get the full hierarchy path from root to this unit.
#         Example: 'Faculty of Engineering > Department of Computer Science > AI Lab'
#         """
#         path = [self.name]
#         current = self.parent
#         while current:
#             path.insert(0, current.name)
#             current = current.parent
#         return ' > '.join(path)
    
#     def get_level(self):
#         """
#         Get the depth level in the hierarchy.
#         0 = root level (no parent), 1 = first level, etc.
#         """
#         level = 0
#         current = self.parent
#         while current:
#             level += 1
#             current = current.parent
#         return level

class StaffProfile(models.Model):
    campus = models.ManyToManyField(
        'accounts.Campus',
        related_name='staff_profiles'
    )
    user = models.OneToOneField(
        'accounts.User',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='staff_profile',
    )
    application = models.ForeignKey(JobApplication, on_delete=models.SET_NULL, null=True, blank=True)

    staff_type = models.ForeignKey(StaffType, on_delete=models.SET_NULL, null=True, blank=True)
    is_supervisor = models.BooleanField(default=False)
    is_hr = models.BooleanField(default=False)
    
    # Manager fields - for users who manage departments/units
    is_director = models.BooleanField(default=False)
    managed_org_units = models.ManyToManyField(
        Department,
        blank=True,
        related_name='managed_by',
    )
    staff_no = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
    )

    first_name = models.CharField(max_length=200)
    last_name = models.CharField(max_length=200)
    
    # Identity documents
    nssf_no = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name="NSSF Number"
    )
    tin_no = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name="TIN Number"
    )
    
    # Contact
    university_email = models.EmailField(
        blank=True,
        null=True,
        unique=True,
    )
    personal_email = models.EmailField(
        blank=True,
        null=True,
    )
    
    # Passport Photo for ID Cards
    passport_photo = models.ImageField(
        upload_to='staff_photos/%Y/',
        blank=True,
        null=True,
    )
    
    # Organization
    job_title = models.CharField(
        max_length=20,
        null=True,
        blank=True,
    )
    
    org_unit = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL, null=True, blank=True, 
        related_name='staff_members'
    )

    team = models.ForeignKey(
        DepartmentTeams,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='members'
    )
    
    position_level = models.ForeignKey(PositonLevel, on_delete=models.SET_NULL, null=True, blank=True)
    pay_scale = models.ForeignKey(
        PayScale,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="staff_profiles",
        help_text="Ugandan salary scale (U/P grade) per IPPS-style grading",
    )
    pay_step = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Salary step/notch on the scale (typically 1–35)",
    )
    
    system_login = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['staff_no']
    
    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.staff_no})"
    
    @property
    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"
    
    def save(self, *args, **kwargs):
        if not self.staff_no:
            number = generate_number()
            # ensure uniqueness (extra safety)
            while StaffProfile.objects.filter(staff_no=number).exists():
                number = generate_number()
            self.staff_no = number
        super().save(*args, **kwargs)
    
class SupervisionAssignment(models.Model):
    supervisor = models.ForeignKey(
        StaffProfile,
        on_delete=models.CASCADE,
        related_name='supervision_assignments'
    )

    team = models.ForeignKey(
        DepartmentTeams,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='asigned_teams'
    )

    staff_member = models.ForeignKey(
        StaffProfile,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='assigned_supervisors'
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(team__isnull=False, staff_member__isnull=True) |
                    models.Q(team__isnull=True, staff_member__isnull=False)
                ),
                name="one_supervision_target"
            )
        ]

    def __str__(self):
        return f"{self.supervisor.first_name} {self.supervisor.last_name}"

class StaffContract(models.Model):
    CONTRACT_TYPE_CHOICES = [
        ('PERMANENT', 'Permanent Contract'),
        ('FIXED_TERM', 'Fixed Term Contract'),
        ('TEMPORARY', 'Temporary Contract'),
        ('PROBATION', 'Probation Period'),
        ('CONSULTANT', 'Consultant Agreement'),
        ('PART_TIME', 'Part-Time Contract'),
    ]
    
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('EXPIRED', 'Expired'),
        ('TERMINATED', 'Terminated'),
        ('RENEWED', 'Renewed'),
    ]
    
    staff = models.ForeignKey(
        StaffProfile,
        on_delete=models.CASCADE,
        related_name='contracts',
        help_text="Staff member this contract belongs to"
    )
    contract_type = models.CharField(
        max_length=20,
        choices=CONTRACT_TYPE_CHOICES,
        help_text="Type of employment contract"
    )
    contract_number = models.CharField(
        max_length=50,
        unique=True,
        help_text="Unique contract reference number"
    )
    
    # Contract period
    start_date = models.DateField(help_text="Contract start date")
    end_date = models.DateField(
        null=True,
        blank=True,
        help_text="Contract end date (leave blank for permanent contracts)"
    )
    
    # Contract details
    position = models.CharField(
        max_length=200,
        help_text="Position/title as per contract"
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        help_text="Department as specified in contract"
    )
    salary = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Annual salary (optional, confidential)"
    )
    pay_scale = models.ForeignKey(
        PayScale,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contracts",
        help_text="Contracted Ugandan pay scale (U/P grade)",
    )
    pay_step = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Salary step/notch on the scale",
    )
    
    # Document
    contract_file = models.FileField(
        upload_to='contracts/%Y/%m/',
        validators=[FileExtensionValidator(allowed_extensions=['pdf', 'doc', 'docx'])],
        help_text="Upload signed contract document (PDF, DOC, DOCX)"
    )
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='ACTIVE'
    )
    
    # Renewal tracking
    renewal_of = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='renewals',
        help_text="If this is a renewal, link to previous contract"
    )
    
    # Notes
    notes = models.TextField(
        blank=True,
        help_text="Additional notes or special terms"
    )
    
    # Alert tracking
    alert_sent_30_days = models.BooleanField(
        default=False,
        help_text="Alert sent 30 days before expiry"
    )
    alert_sent_60_days = models.BooleanField(
        default=False,
        help_text="Alert sent 60 days before expiry"
    )
    alert_sent_90_days = models.BooleanField(
        default=False,
        help_text="Alert sent 90 days before expiry"
    )
    
    class Meta:
        ordering = ['-start_date']
        verbose_name = 'Staff Contract'
        verbose_name_plural = 'Staff Contracts'
    
    def __str__(self):
        return f"{self.contract_number} - {self.staff.full_name} - {self.get_contract_type_display()}"
    
    @property
    def days_until_expiry(self):
        """Calculate days until contract expires."""
        if not self.end_date or self.status != 'ACTIVE':
            return None
        delta = self.end_date - date.today()
        return delta.days
    
    @property
    def is_expiring_soon(self):
        """Check if contract is expiring within 90 days."""
        days = self.days_until_expiry
        return days is not None and 0 <= days <= 90
    
    @property
    def is_expired(self):
        """Check if contract has expired."""
        if not self.end_date:
            return False
        return date.today() > self.end_date and self.status == 'ACTIVE'
    
    @property
    def expiry_status_color(self):
        """Get color for expiry status badge."""
        days = self.days_until_expiry
        if days is None:
            return 'success'  # Permanent
        if days < 0:
            return 'danger'  # Expired
        if days <= 30:
            return 'danger'  # Critical
        if days <= 60:
            return 'warning'  # Warning
        if days <= 90:
            return 'info'  # Notice
        return 'success'  # Safe
    
    def clean(self):
        """Custom validation."""
        super().clean()
        # For fixed-term contracts, end_date is required
        if self.contract_type in ['FIXED_TERM', 'TEMPORARY', 'PROBATION', 'CONSULTANT'] and not self.end_date:
            raise ValidationError({
                'end_date': f'{self.get_contract_type_display()} contracts must have an end date.'
            })
        # End date must be after start date
        if self.end_date and self.start_date and self.end_date <= self.start_date:
            raise ValidationError({
                'end_date': 'End date must be after start date.'
            })

class SystemPermissions(models.Model):
    staff = models.ForeignKey(StaffProfile, on_delete=models.CASCADE)

    class Meta:
        permissions = [
            ("view_team_appraisals", "Can view team appraisals"),
            ("view_all_appraisals", "Can view all appraisals (HR)"),
            ("manage_staff", "Can manage staff"),
            ("view_pips", "Can view pips"),
            ("request_leave", "Can request leave"),
            ("view_supervisedstaff", 'Can view supervised staff')
        ]

class BulkUploadStaff(models.Model):
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