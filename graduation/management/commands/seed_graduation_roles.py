from django.apps import apps as django_apps
from django.contrib.auth.management import create_permissions
from django.contrib.contenttypes.management import create_contenttypes
from django.core.management.base import BaseCommand

from graduation.role_setup import seed_all_graduation_roles


class Command(BaseCommand):
    help = "Create/update Graduation Officer and Graduation Viewer groups."

    def handle(self, *args, **options):
        for app_name in ("accounts", "graduation"):
            app_config = django_apps.get_app_config(app_name)
            create_contenttypes(app_config, verbosity=0, interactive=False)
            create_permissions(app_config, verbosity=0, interactive=False)

        from django.contrib.auth.models import Group, Permission

        seed_all_graduation_roles(Group, Permission, stdout=self.stdout)
        self.stdout.write(self.style.SUCCESS("Graduation roles ready."))
