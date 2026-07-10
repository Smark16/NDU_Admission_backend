"""
Management command to check manager setup and assigned units.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from hr.staff.models import StaffProfile

User = get_user_model()


class Command(BaseCommand):
    help = 'Check manager setup and assigned units'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('\n=== ALL USERS ==='))
        users = User.objects.all()
        for user in users:
            has_profile = hasattr(user, 'staff_profile')
            self.stdout.write(f'{user.id}: {user.username} - Type: {user.user_type}, Has staff_profile: {has_profile}')
            if has_profile:
                try:
                    profile = user.staff_profile
                    self.stdout.write(f'   → Staff: {profile.staff_no}, Is Manager: {profile.is_manager}')
                    if profile.is_manager:
                        units = profile.managed_org_units.all()
                        self.stdout.write(f'   → Managed Units: {units.count()}')
                        for unit in units:
                            self.stdout.write(f'      - {unit.name}')
                except Exception as e:
                    self.stdout.write(f'   → Error: {e}')
        
        self.stdout.write(self.style.SUCCESS('\n=== ALL STAFF PROFILES ==='))
        profiles = StaffProfile.objects.all()
        for profile in profiles:
            user_info = profile.user.username if profile.user else 'No User'
            self.stdout.write(f'{profile.staff_no}: {profile.full_name}')
            self.stdout.write(f'   → User: {user_info}, Is Manager: {profile.is_manager}')
            if profile.is_manager:
                units = profile.managed_org_units.all()
                self.stdout.write(f'   → Managed Units ({units.count()}):')
                for unit in units:
                    staff_count = unit.staff_members.count()
                    self.stdout.write(f'      - {unit.name} ({staff_count} staff)')
