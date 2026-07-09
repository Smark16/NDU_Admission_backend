"""Test what a manager can see."""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from hr.staff.models import StaffProfile

User = get_user_model()


class Command(BaseCommand):
    help = 'Test what a manager can see'

    def add_arguments(self, parser):
        parser.add_argument('username', type=str, help='Username of the manager')

    def handle(self, *args, **options):
        username = options['username']
        
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'User {username} not found'))
            return
        
        self.stdout.write(self.style.SUCCESS(f'\n=== Testing Manager View for {username} ==='))
        self.stdout.write(f'User Type: {user.user_type}')
        
        if not hasattr(user, 'staff_profile'):
            self.stdout.write(self.style.ERROR('User has no staff profile'))
            return
        
        profile = user.staff_profile
        self.stdout.write(f'Staff No: {profile.staff_no}')
        self.stdout.write(f'Is Manager: {profile.is_manager}')
        
        managed_units = profile.managed_org_units.all()
        self.stdout.write(f'\nManaged Units: {managed_units.count()}')
        
        all_units_to_view = []
        for unit in managed_units:
            self.stdout.write(f'  → {unit.name}')
            all_units_to_view.append(unit)
            
            # Get descendants
            descendants = unit.get_all_descendants()
            if descendants:
                self.stdout.write(f'     Sub-units:')
                for desc in descendants:
                    self.stdout.write(f'       - {desc.name}')
                    all_units_to_view.append(desc)
        
        # Now check staff in all these units
        self.stdout.write(self.style.SUCCESS(f'\n=== Staff Visible to {username} ==='))
        
        staff_list = StaffProfile.objects.filter(
            org_unit__in=all_units_to_view
        ).select_related('org_unit')
        
        self.stdout.write(f'Total Staff Count: {staff_list.count()}\n')
        
        for staff in staff_list:
            self.stdout.write(
                f'{staff.staff_no}: {staff.full_name}\n'
                f'   → Org Unit: {staff.org_unit.name}\n'
            )
        
        if staff_list.count() == 0:
            self.stdout.write(self.style.WARNING('\nNo staff found! This is why the manager sees an empty list.'))
