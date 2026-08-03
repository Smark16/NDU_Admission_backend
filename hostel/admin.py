from django.contrib import admin

from .models import Bed, Building, Floor, Hostel, HostelAllocation, Room


@admin.register(Hostel)
class HostelAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "campus", "gender", "is_active")
    list_filter = ("gender", "is_active", "campus")
    search_fields = ("name", "code")


@admin.register(Building)
class BuildingAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "hostel", "is_active")
    list_filter = ("hostel", "is_active")
    search_fields = ("name", "code")


@admin.register(Floor)
class FloorAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "building", "sort_order")
    list_filter = ("building__hostel",)


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("code", "display_name", "room_kind", "capacity", "floor", "is_active")
    list_filter = ("room_kind", "is_active", "floor__building")
    search_fields = ("code", "display_name")


@admin.register(Bed)
class BedAdmin(admin.ModelAdmin):
    list_display = ("label", "room", "status")
    list_filter = ("status",)
    search_fields = ("label", "room__code")


@admin.register(HostelAllocation)
class HostelAllocationAdmin(admin.ModelAdmin):
    list_display = (
        "student",
        "bed",
        "academic_year",
        "term_number",
        "status",
        "assigned_at",
    )
    list_filter = ("status", "academic_year", "term_number")
    search_fields = ("student__reg_no", "bed__room__code")
    raw_id_fields = ("student", "bed")
