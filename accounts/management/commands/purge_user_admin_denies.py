"""
Remove Deny rows that block User Management (change_user / add_user / delete_user / view_user).

Safe to re-run. Use when staff can open Find users but cannot save role edits
because a role like Admissions Team previously Denied change_user.
"""
from django.core.management.base import BaseCommand

from accounts.models import RoleCapability


BLOCKING_CODES = (
    "change_user",
    "add_user",
    "delete_user",
    "view_user",
    "access_user_management",
    "view_group",
    "change_group",
    "add_group",
    "delete_group",
)


class Command(BaseCommand):
    help = "Purge RoleCapability Deny rows that block editing users / listing roles."

    def handle(self, *args, **options):
        qs = RoleCapability.objects.filter(
            state=RoleCapability.STATE_DENY,
            permission__codename__in=BLOCKING_CODES,
        )
        count = qs.count()
        details = list(
            qs.values_list(
                "group__name",
                "permission__content_type__app_label",
                "permission__codename",
            )
        )
        qs.delete()
        for group_name, app, code in details:
            self.stdout.write(f"  removed Deny {app}.{code} from '{group_name}'")
        self.stdout.write(self.style.SUCCESS(f"Purged {count} Deny row(s)."))
        self.stdout.write("Ask affected users to log out and log back in.")
