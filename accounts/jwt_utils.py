"""JWT claim helpers — keep login and refresh tokens in sync with live permissions."""

from accounts.role_assignment import (
    active_role_label,
    resolve_portal_mode,
    user_portal_modes,
)


def apply_user_token_claims(token, user) -> None:
    """Attach NDU portal claims used by the React admin/student frontends."""
    portal_mode = resolve_portal_mode(user)
    portal_modes = user_portal_modes(user)
    roles = list(user.groups.order_by("name").values_list("name", flat=True))

    token["first_name"] = user.first_name
    token["last_name"] = user.last_name
    token["is_staff"] = user.is_staff
    token["is_applicant"] = user.is_applicant
    token["is_student"] = user.is_student
    token["is_lecturer"] = user.is_lecturer
    token["must_change_password"] = user.must_change_password
    token["last_login"] = user.last_login.isoformat() if user.last_login else None
    token["roles"] = roles
    token["portal_modes"] = portal_modes
    token["portal_mode"] = portal_mode
    token["role"] = active_role_label(user, portal_mode)
    token["phone"] = user.phone
    token["email"] = user.email
    token["username"] = user.username
    # Permissions are served from GET /api/accounts/session/ (response body).
    # Embedding hundreds of perms in the JWT blows past nginx header limits (HTTP 431).


def _all_permission_strings() -> list[str]:
    from django.contrib.auth.models import Permission

    return [
        f"{p.content_type.app_label}.{p.codename}"
        for p in Permission.objects.select_related("content_type").iterator()
    ]


def session_payload(user) -> dict:
    """Live session snapshot for /api/accounts/session/ (no new JWT required)."""
    from accounts.super_admin import user_is_super_admin

    portal_mode = resolve_portal_mode(user)
    portal_modes = user_portal_modes(user)
    roles = list(user.groups.order_by("name").values_list("name", flat=True))
    is_super = user_is_super_admin(user)
    # Super Admin always gets every permission, even if the group was not
    # re-seeded after a new custom permission was added.
    permissions = _all_permission_strings() if is_super else list(user.get_all_permissions())

    return {
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "roles": roles,
        "portal_modes": portal_modes,
        "portal_mode": portal_mode,
        "role": active_role_label(user, portal_mode),
        "is_staff": user.is_staff,
        "is_applicant": user.is_applicant,
        "is_student": user.is_student,
        "is_lecturer": user.is_lecturer,
        "is_super_admin": is_super,
        "must_change_password": user.must_change_password,
        "permissions": permissions,
    }
