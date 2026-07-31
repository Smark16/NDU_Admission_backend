from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create or refresh the HOD Django group and permissions."

    def handle(self, *args, **options):
        from django.contrib.auth.models import Group, Permission

        from admissions.hod_role_setup import seed_hod_role

        seed_hod_role(Group, Permission, stdout=self.stdout)
        self.stdout.write(
            self.style.SUCCESS(
                "HOD role ready. Assign users in Admin > User Management "
                "with role HOD and one or more faculties."
            )
        )
