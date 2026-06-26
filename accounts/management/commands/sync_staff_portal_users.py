"""Re-sync is_staff / portal_mode for users with staff Django groups (fixes student-portal logins)."""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from accounts.role_assignment import (
    _promote_staff_portal_identity,
    sync_user_role_flags,
    user_has_non_lecturer_staff_group,
)

User = get_user_model()


class Command(BaseCommand):
    help = (
        "Recalculate staff portal flags for users assigned ERP roles. "
        "Use after fixing role logic or when staff land in the student portal."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            help="Limit to one user email (optional).",
        )

    def handle(self, *args, **options):
        qs = User.objects.prefetch_related("groups").filter(groups__isnull=False).distinct()
        email = (options.get("email") or "").strip()
        if email:
            qs = qs.filter(email__iexact=email)

        fixed = 0
        for user in qs:
            if not user_has_non_lecturer_staff_group(user):
                continue
            before = (
                user.is_staff,
                user.is_student,
                user.is_applicant,
                user.portal_mode,
            )
            sync_user_role_flags(user, save=False)
            fields = _promote_staff_portal_identity(user)
            save_fields = list(
                dict.fromkeys(
                    ["is_staff", "is_lecturer", "role", "is_student", "is_applicant", "portal_mode"]
                    + fields
                )
            )
            user.save(update_fields=save_fields)
            after = (
                user.is_staff,
                user.is_student,
                user.is_applicant,
                user.portal_mode,
            )
            if after != before:
                fixed += 1
                self.stdout.write(
                    f"  {user.email}: staff={after[0]} student={after[1]} "
                    f"applicant={after[2]} portal={after[3]!r}"
                )

        self.stdout.write(self.style.SUCCESS(f"Updated {fixed} user(s). Users must log out and back in."))
