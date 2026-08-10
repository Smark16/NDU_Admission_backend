from accounts.super_admin import user_is_super_admin
from rest_framework.permissions import BasePermission

ACCESS_HOSTEL = "accounts.access_hostel"


def _has(user, perm: str) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user_is_super_admin(user) or getattr(user, "is_superuser", False):
        return True
    return user.has_perm(perm)


def user_has_hostel_perm(user, *codenames: str) -> bool:
    """True if user has any of the given hostel.* codenames (or is Super Admin).

    ``accounts.access_hostel`` alone does NOT grant every hostel action — Role
    Management ticks for assign / inventory / reports must be checked explicitly.
    """
    if not user or not user.is_authenticated:
        return False
    if user_is_super_admin(user) or getattr(user, "is_superuser", False):
        return True
    return any(_has(user, f"hostel.{c}") for c in codenames)


def user_can_access_hostel_module(user) -> bool:
    """Module entry: Hostel module access OR any hostel service permission."""
    if not user or not user.is_authenticated:
        return False
    if user_is_super_admin(user) or getattr(user, "is_superuser", False):
        return True
    if _has(user, ACCESS_HOSTEL):
        return True
    return user_has_hostel_perm(
        user,
        "manage_hostel_inventory",
        "assign_hostel",
        "end_hostel_allocation",
        "view_hostel_reports",
        "view_hostel",
        "view_building",
        "view_floor",
        "view_room",
        "view_bed",
        "view_hostelallocation",
    )


class CanAccessHostel(BasePermission):
    message = "You do not have permission to access the hostel module."

    def has_permission(self, request, view):
        return user_can_access_hostel_module(request.user)


class CanManageInventory(BasePermission):
    def has_permission(self, request, view):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return user_has_hostel_perm(
                request.user,
                "manage_hostel_inventory",
                "view_hostel",
                "view_building",
                "view_room",
                "view_bed",
                "assign_hostel",
                "view_hostel_reports",
            )
        return user_has_hostel_perm(request.user, "manage_hostel_inventory")


class CanAssignHostel(BasePermission):
    def has_permission(self, request, view):
        return user_has_hostel_perm(request.user, "assign_hostel")


class CanEndAllocation(BasePermission):
    def has_permission(self, request, view):
        return user_has_hostel_perm(
            request.user,
            "end_hostel_allocation",
            "assign_hostel",
        )


class CanViewHostelReports(BasePermission):
    def has_permission(self, request, view):
        return user_has_hostel_perm(
            request.user,
            "view_hostel_reports",
            "assign_hostel",
            "manage_hostel_inventory",
        )
