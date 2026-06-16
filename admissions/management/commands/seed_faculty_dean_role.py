from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create or refresh the Faculty Dean Django group and permissions."

    def handle(self, *args, **options):
        from django.contrib.auth.models import Group, Permission

        from admissions.faculty_dean_role_setup import seed_faculty_dean_role

        seed_faculty_dean_role(Group, Permission, stdout=self.stdout)
        self.stdout.write(
            self.style.SUCCESS(
                "Faculty Dean role ready. Assign users in Admin > User Management "
                "with role Faculty Dean and one or more faculties."
            )
        )
