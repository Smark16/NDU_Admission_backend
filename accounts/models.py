from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from django.db.models.signals import post_save
from rest_framework.exceptions import ValidationError


class Campus(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=50, unique=True)
    address = models.TextField(max_length=100, blank=True, default="")
    email = models.EmailField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Campuses"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def delete(self, *args, **kwargs):
        raise ValidationError({"detail": "Deletion of Campus is not allowed."})


class User(AbstractUser):
    role = models.CharField(max_length=64, blank=True, null=True)
    campuses = models.ManyToManyField(Campus, blank=True, related_name="users")
    phone = models.CharField(max_length=20, blank=True, null=True)
    staff_id = models.CharField(max_length=50, blank=True, null=True, unique=True, db_index=True)
    is_staff = models.BooleanField(default=False)
    is_applicant = models.BooleanField(default=False, db_index=True)
    is_student = models.BooleanField(default=False, db_index=True)
    is_lecturer = models.BooleanField(default=False, db_index=True)
    portal_mode = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        choices=(
            ("admin", "Admin portal"),
            ("lecturer", "Lecturer portal"),
            ("student", "Student portal"),
        ),
        help_text="Active portal view when the user can access more than one ERP portal.",
    )
    primary_campus = models.ForeignKey(
        Campus,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="primary_staff",
        help_text="Main teaching campus (used for timetable campus rules).",
    )
    allow_multi_campus_per_day = models.BooleanField(
        default=False,
        help_text="If false, timetable blocks same lecturer on two campuses in one day.",
    )
    must_change_password = models.BooleanField(default=False)
    faculties = models.ManyToManyField(
        "admissions.Faculty",
        blank=True,
        related_name="assigned_staff",
        help_text="Faculties this staff member may access (Faculty Dean and similar roles).",
    )

    @property
    def full_name(self):
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}".strip()
        elif self.first_name:
            return self.first_name
        elif self.last_name:
            return self.last_name
        else:
            return self.username

    def __str__(self):
        return f"{self.get_full_name()}"


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    email = models.EmailField(max_length=100)
    phone = models.CharField(max_length=32, blank=True, null=True)
    profile_photo = models.ImageField(upload_to="passport_photos/", blank=True, null=True)
    is_staff = models.BooleanField(default=False)
    is_applicant = models.BooleanField(default=False)
    date_joined = models.DateTimeField(null=True, blank=True)


def create_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(
            user=instance,
            first_name=instance.first_name or "",
            last_name=instance.last_name or "",
            date_joined=instance.date_joined or timezone.now(),
            is_staff=instance.is_staff,
            is_applicant=instance.is_applicant,
            email=instance.email or "",
            phone=(instance.phone or None),
        )


def save_profile(sender, instance, **kwargs):
    if not hasattr(instance, "profile"):
        return
    profile = instance.profile
    profile.first_name = instance.first_name or ""
    profile.last_name = instance.last_name or ""
    profile.email = instance.email or ""
    profile.phone = instance.phone or ""
    profile.is_staff = instance.is_staff
    profile.is_applicant = instance.is_applicant
    profile.save(
        update_fields=[
            "first_name",
            "last_name",
            "email",
            "phone",
            "is_staff",
            "is_applicant",
        ]
    )


post_save.connect(create_profile, sender=User)
post_save.connect(save_profile, sender=User)


class SystemSettings(models.Model):
    student_session_timeout = models.PositiveIntegerField(
        default=30,
        help_text="Minutes before a student session expires due to inactivity",
    )
    admin_session_timeout = models.PositiveIntegerField(
        default=60,
        help_text="Minutes before an admin session expires due to inactivity",
    )
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="settings_updates",
    )
    updated_at = models.DateTimeField(auto_now=True)
    id_card_templates = models.JSONField(
        default=list,
        blank=True,
        help_text="List of {key, name, front_title, back_text, institution, issuer_title, issuer_signatory, return_to, tel, email} for ID card preview.",
    )
    active_id_card_template = models.CharField(
        max_length=80,
        blank=True,
        default="",
        help_text="Template key matching id_card_templates[].key",
    )
    university_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Display name on login and portal headers (e.g. NDEJJE UNIVERSITY STEWARD ERP).",
    )
    portal_logo = models.ImageField(
        upload_to="portal_branding/",
        blank=True,
        null=True,
        help_text="Logo shown on the login page and optionally elsewhere in the portal.",
    )
    login_cover_image = models.ImageField(
        upload_to="portal_branding/",
        blank=True,
        null=True,
        help_text="Hero / background image on the login page left panel.",
    )

    class Meta:
        verbose_name = "System Settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_settings(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class ErpAccessPolicy(models.Model):
    label = models.CharField(max_length=64, default="default", unique=True, editable=False)

    class Meta:
        verbose_name = "ERP access policy"
        verbose_name_plural = "ERP access policies"
        default_permissions = ()
        permissions = [
            ("access_admissions", "Access Admissions module"),
            ("access_academics", "Access Academics (programmes, curriculum, enrollment)"),
            ("access_finance", "Access Finance and payments"),
            ("access_reports", "Access Reports and analytics"),
            ("access_user_management", "Access user administration"),
            ("access_audit", "Access audit logs"),
            ("access_system_settings", "Access academic and admission setup"),
            ("access_lecturer_portal", "Access lecturer workspace"),
            ("manage_direct_applications", "Manage direct-entry applications"),
            ("approve_admissions", "Approve or reject applications and admissions"),
            ("manage_batches", "Manage admission intakes and batches"),
            ("assign_roles", "Assign Django groups to staff users"),
            ("manage_payment_reconciliation", "Manage payment reconciliation tools"),
            ("manage_curriculum", "Manage programme curriculum (versions, mappings, inheritance)"),
            (
                "manage_program_scheduling",
                "Manage cohort batches, semesters, and scheduled course offerings",
            ),
            ("manage_course_catalog", "Manage shared course catalog entries"),
            (
                "manage_academic_enrollment",
                "Manage student programme enrollment and curriculum overrides",
            ),
            (
                "configure_fee_plans",
                "Configure fee plans, tuition matrices, and billing schedules",
            ),
            (
                "manage_scholarships",
                "Manage scholarship programmes, student awards, and fee waivers",
            ),
            ("manage_communication_templates", "Manage system email templates and communications"),
            (
                "access_examinations",
                "Access Examinations module (marks, timetable, publish, reports)",
            ),
            (
                "access_graduation",
                "Access Graduation module (qualified lists, ceremonies)",
            ),
        ]

    def __str__(self):
        return self.label
