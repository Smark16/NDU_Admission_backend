"""List all staff and their org units."""
from django.core.management.base import BaseCommand
from hr.staff.models import StaffProfile


class Command(BaseCommand):
    help = 'List all staff and their organizational units'

    def handle(self, *args, **options):
        profiles = StaffProfile.objects.select_related('org_unit', 'campus').all()
        
        self.stdout.write(self.style.SUCCESS(f'\n=== ALL STAFF ({profiles.count()}) ===\n'))
        
        for profile in profiles:
            org_unit = profile.org_unit.name if profile.org_unit else 'No Unit'
            campus = profile.campus.name if profile.campus else 'No Campus'
            manager_status = ' [MANAGER]' if profile.is_manager else ''
            
            self.stdout.write(
                f'{profile.staff_no}: {profile.full_name}{manager_status}\n'
                f'   → Org Unit: {org_unit}\n'
                f'   → Campus: {campus}\n'
            )
