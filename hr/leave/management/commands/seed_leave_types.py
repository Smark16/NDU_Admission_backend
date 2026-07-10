from django.core.management.base import BaseCommand

from hr.leave.models import LeaveType


class Command(BaseCommand):
    help = "Seed default leave types for local HR testing."

    def handle(self, *args, **options):
        defaults = [
            ("Annual Leave", "ANN", 21),
            ("Sick Leave", "SCK", 14),
            ("Maternity Leave", "MAT", 60),
            ("Paternity Leave", "PAT", 7),
            ("Study Leave", "STD", 30),
        ]
        for name, code, days in defaults:
            obj, created = LeaveType.objects.get_or_create(
                code=code,
                defaults={"name": name, "max_days_per_year": days, "is_active": True},
            )
            verb = "Created" if created else "Found"
            self.stdout.write(f"{verb}: {obj.name}")

        self.stdout.write(self.style.SUCCESS("Leave types ready."))
