from django.apps import apps as django_apps
from django.contrib.auth.management import create_permissions
from django.contrib.contenttypes.management import create_contenttypes
from django.core.management.base import BaseCommand

from hostel.role_setup import seed_all_hostel_roles


class Command(BaseCommand):
    help = (
        "Create/sync Dean of Students, Hostel Manager, and Hostel Viewer groups "
        "to hostel-module permissions only."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-sync",
            action="store_true",
            help="Only add missing permissions; do not remove extras from the groups.",
        )

    def handle(self, *args, **options):
        for app_name in ("accounts", "hostel"):
            app_config = django_apps.get_app_config(app_name)
            create_contenttypes(app_config, verbosity=0, interactive=False)
            create_permissions(app_config, verbosity=0, interactive=False)

        from django.contrib.auth.models import Group, Permission

        seed_all_hostel_roles(
            Group,
            Permission,
            stdout=self.stdout,
            sync=not options["no_sync"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Hostel roles ready (hostel module only — Students module locked out)."
            )
        )
