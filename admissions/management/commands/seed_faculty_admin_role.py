from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create or refresh the Faculty Admin Django group and permissions."

    def handle(self, *args, **options):
        from django.contrib.auth.models import Group, Permission

        from admissions.faculty_admin_role_setup import seed_faculty_admin_role

        seed_faculty_admin_role(Group, Permission, stdout=self.stdout)
        self.stdout.write(
            self.style.SUCCESS(
                "Faculty Admin role ready. Assign users in Admin > User Management "
                "with role Faculty Admin and one or more faculties."
            )
        )
