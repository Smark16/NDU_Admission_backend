from django.core.management.base import BaseCommand

from hr.staff.utils.roles import setup_roles


class Command(BaseCommand):
    help = "Seed HR Django groups (Staff, Supervisor, HR) with permissions."

    def handle(self, *args, **options):
        setup_roles(sender=None)
        self.stdout.write(self.style.SUCCESS("HR roles seeded successfully."))
