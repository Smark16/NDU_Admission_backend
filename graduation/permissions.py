from rest_framework.permissions import BasePermission

ACCESS_GRADUATION = "accounts.access_graduation"


def _has(user, perm: str) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.has_perm(perm)


def user_has_graduation_perm(user, *codenames: str) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if _has(user, ACCESS_GRADUATION):
        return True
    return any(_has(user, f"graduation.{c}") for c in codenames)


class CanAccessGraduation(BasePermission):
    message = "You do not have permission to access graduation."

    def has_permission(self, request, view):
        return user_has_graduation_perm(
            request.user,
            "view_qualified_lists",
            "manage_ceremonies",
            "assign_students",
            "view_graduation_lists",
        )


class CanViewQualifiedLists(BasePermission):
    def has_permission(self, request, view):
        return user_has_graduation_perm(request.user, "view_qualified_lists")


class CanManageCeremonies(BasePermission):
    def has_permission(self, request, view):
        return user_has_graduation_perm(request.user, "manage_ceremonies")


class CanAssignStudents(BasePermission):
    def has_permission(self, request, view):
        return user_has_graduation_perm(request.user, "assign_students")


class CanViewGraduationLists(BasePermission):
    def has_permission(self, request, view):
        return user_has_graduation_perm(request.user, "view_graduation_lists")
