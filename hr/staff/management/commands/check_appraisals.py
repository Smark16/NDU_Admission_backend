"""Check appraisals for staff in managed units."""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from hr.staff.models import StaffProfile
from hr.appraisal.models import Appraisal

User = get_user_model()


class Command(BaseCommand):
    help = 'Check appraisals setup'

    def handle(self, *args, **options):
        # Check Ikasan's setup
        try:
            user = User.objects.get(username='ikasana')
            profile = user.staff_profile
            
            self.stdout.write(self.style.SUCCESS(f'\n=== IKASAN SETUP ==='))
            self.stdout.write(f'Username: {user.username}')
            self.stdout.write(f'User Type: {user.user_type}')
            self.stdout.write(f'Is Manager: {profile.is_manager}')
            
            self.stdout.write(f'\nManaged Units ({profile.managed_org_units.count()}):')
            all_units = []
            for unit in profile.managed_org_units.all():
                self.stdout.write(f'  → {unit.name}')
                all_units.append(unit)
                descendants = unit.get_all_descendants()
                if descendants:
                    for desc in descendants:
                        self.stdout.write(f'     - {desc.name}')
                        all_units.append(desc)
            
            # Check staff in those units
            self.stdout.write(self.style.SUCCESS(f'\n=== STAFF IN MANAGED UNITS ==='))
            staff_in_units = StaffProfile.objects.filter(org_unit__in=all_units)
            self.stdout.write(f'Total staff: {staff_in_units.count()}\n')
            
            for staff in staff_in_units:
                self.stdout.write(f'{staff.staff_no}: {staff.full_name}')
                self.stdout.write(f'   → Org Unit: {staff.org_unit.name}')
                self.stdout.write(f'   → Supervisor: {staff.supervisor.full_name if staff.supervisor else "None"}')
            
            # Check appraisals
            self.stdout.write(self.style.SUCCESS(f'\n=== APPRAISALS ==='))
            all_appraisals = Appraisal.objects.all()
            self.stdout.write(f'Total appraisals in system: {all_appraisals.count()}\n')
            
            if all_appraisals.count() > 0:
                for appraisal in all_appraisals:
                    self.stdout.write(f'{appraisal.staff.staff_no}: {appraisal.staff.full_name}')
                    self.stdout.write(f'   → Cycle: {appraisal.cycle.academic_year}')
                    self.stdout.write(f'   → Status: {appraisal.status}')
                    self.stdout.write(f'   → Supervisor: {appraisal.supervisor.full_name if appraisal.supervisor else "None"}')
                    self.stdout.write(f'   → Staff Org Unit: {appraisal.staff.org_unit.name}\n')
            else:
                self.stdout.write(self.style.WARNING('NO APPRAISALS EXIST! This is why the list is empty.'))
                self.stdout.write('\nTo create appraisals:')
                self.stdout.write('1. Go to Performance Appraisal → Cycles')
                self.stdout.write('2. Create an appraisal cycle')
                self.stdout.write('3. Activate the cycle')
                self.stdout.write('4. Appraisals will be auto-created for all staff')
            
            # Check what query would return
            self.stdout.write(self.style.SUCCESS(f'\n=== WHAT IKASAN SHOULD SEE ==='))
            from django.db.models import Q
            
            team_appraisals = Appraisal.objects.filter(
                Q(supervisor=profile) | Q(staff__org_unit__in=all_units)
            ).distinct()
            
            self.stdout.write(f'Query would return: {team_appraisals.count()} appraisals')
            
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR('User ikasana not found'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error: {e}'))
