from django.conf import settings
from django.db import models


class Hostel(models.Model):
    """Gender-scoped hostel group on a campus (e.g. Gents Hostel, Female Hostel)."""

    GENDER_MALE = "male"
    GENDER_FEMALE = "female"
    GENDER_MIXED = "mixed"
    GENDER_CHOICES = [
        (GENDER_MALE, "Male"),
        (GENDER_FEMALE, "Female"),
        (GENDER_MIXED, "Mixed"),
    ]

    campus = models.ForeignKey(
        "accounts.Campus",
        on_delete=models.PROTECT,
        related_name="hostels",
    )
    code = models.CharField(max_length=64, db_index=True)
    name = models.CharField(max_length=200)
    gender = models.CharField(max_length=16, choices=GENDER_CHOICES, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    # Soft assignment guidance — counts of floors from each building's extreme.
    # "Upper" / "lower" are relative to that hall (e.g. a 2-level hall: top=L1, bottom=GF).
    fresher_min_sort_order = models.PositiveSmallIntegerField(
        default=1,
        help_text=(
            "How many of the highest floors in each hall to suggest for freshers "
            "(1 = only the top level of that building)."
        ),
    )
    continuing_max_sort_order = models.PositiveSmallIntegerField(
        default=1,
        help_text=(
            "How many of the lowest floors in each hall to suggest for continuing students "
            "(1 = only the ground/lowest level of that building)."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["campus__name", "name"]
        unique_together = [("campus", "code")]
        permissions = [
            ("manage_hostel_inventory", "Can manage hostel inventory (halls, rooms, beds)"),
            ("assign_hostel", "Can assign students to hostel beds"),
            ("end_hostel_allocation", "Can end or cancel hostel allocations"),
            ("view_hostel_reports", "Can view hostel occupancy and finance-ops reports"),
        ]

    def __str__(self):
        return f"{self.name} ({self.campus})"


class Building(models.Model):
    """Hall / block within a hostel (e.g. Bishop Yokana, Akiibua)."""

    hostel = models.ForeignKey(Hostel, on_delete=models.CASCADE, related_name="buildings")
    code = models.CharField(max_length=64, db_index=True)
    name = models.CharField(max_length=200)
    external_block_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Original Excel BuildingID (e.g. Block-I)",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["hostel__name", "name"]
        unique_together = [("hostel", "code")]

    def __str__(self):
        return self.name


class Floor(models.Model):
    building = models.ForeignKey(Building, on_delete=models.CASCADE, related_name="floors")
    code = models.CharField(max_length=64, db_index=True)
    name = models.CharField(max_length=100)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["building__name", "sort_order", "name"]
        unique_together = [("building", "code")]

    def __str__(self):
        return f"{self.building.name} / {self.name}"


class Room(models.Model):
    KIND_BEDROOM = "bedroom"
    KIND_STORE = "store"
    KIND_COMMON = "common"
    KIND_OTHER = "other"
    KIND_CHOICES = [
        (KIND_BEDROOM, "Bedroom"),
        (KIND_STORE, "Store"),
        (KIND_COMMON, "Common room"),
        (KIND_OTHER, "Other"),
    ]

    floor = models.ForeignKey(Floor, on_delete=models.CASCADE, related_name="rooms")
    code = models.CharField(max_length=64, unique=True, db_index=True)
    display_name = models.CharField(max_length=64, blank=True, default="")
    room_kind = models.CharField(
        max_length=16,
        choices=KIND_CHOICES,
        default=KIND_BEDROOM,
        db_index=True,
    )
    capacity = models.PositiveSmallIntegerField(
        default=0,
        help_text="Bed count for bedrooms; 0 for non-bedroom spaces.",
    )
    notes = models.CharField(max_length=200, blank=True, default="")
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["floor__building__name", "floor__sort_order", "code"]

    def __str__(self):
        return self.code


class Bed(models.Model):
    STATUS_AVAILABLE = "available"
    STATUS_OCCUPIED = "occupied"
    STATUS_BLOCKED = "blocked"
    STATUS_MAINTENANCE = "maintenance"
    STATUS_CHOICES = [
        (STATUS_AVAILABLE, "Available"),
        (STATUS_OCCUPIED, "Occupied"),
        (STATUS_BLOCKED, "Blocked"),
        (STATUS_MAINTENANCE, "Maintenance"),
    ]

    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="beds")
    label = models.CharField(max_length=32)
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_AVAILABLE,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["room__code", "label"]
        unique_together = [("room", "label")]

    def __str__(self):
        return f"{self.room.code} / {self.label}"


class HostelAllocation(models.Model):
    """
    Student occupancy of a bed for an academic year + term.

    Policy: continuing students are re-assigned each academic year/term.
    Ending an allocation (or starting a new one) frees the prior bed.
    """

    STATUS_ACTIVE = "active"
    STATUS_ENDED = "ended"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_ENDED, "Ended"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    student = models.ForeignKey(
        "admissions.AdmittedStudent",
        on_delete=models.CASCADE,
        related_name="hostel_allocations",
    )
    bed = models.ForeignKey(Bed, on_delete=models.PROTECT, related_name="allocations")
    academic_year = models.CharField(
        max_length=32,
        db_index=True,
        help_text="e.g. 2025/2026",
    )
    term_number = models.PositiveSmallIntegerField(db_index=True)
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
        db_index=True,
    )
    check_in = models.DateField(null=True, blank=True)
    check_out = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hostel_allocations_made",
    )
    ended_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hostel_allocations_ended",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-assigned_at"]
        indexes = [
            models.Index(fields=["status", "academic_year", "term_number"]),
            models.Index(fields=["student", "status"]),
            models.Index(fields=["bed", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["student"],
                condition=models.Q(status="active"),
                name="hostel_one_active_allocation_per_student",
            ),
            models.UniqueConstraint(
                fields=["bed"],
                condition=models.Q(status="active"),
                name="hostel_one_active_allocation_per_bed",
            ),
        ]

    def __str__(self):
        return f"{self.student_id} → {self.bed} ({self.status})"
