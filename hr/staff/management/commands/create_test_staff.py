"""
Management command to create test staff quickly.
"""
from django.core.management.base import BaseCommand
from hr.staff.models import StaffProfile, OrgUnit
from accounts.models import Campus
from hr.staff.utils import generate_staff_number


class Command(BaseCommand):
    help = 'Create a test staff member quickly'

    def handle(self, *args, **options):
        # Get first campus and org unit
        campus = Campus.objects.first()
        org_unit = OrgUnit.objects.first()
        
        if not campus or not org_unit:
            self.stdout.write(self.style.ERROR('No campus or org unit found. Please create them first.'))
            return
        
        # Generate unique email
        import random
        random_num = random.randint(1000, 9999)
        
        # Create staff
        staff = StaffProfile.objects.create(
            campus=campus,
            full_name=f'Test Staff {random_num}',
            university_email=f'teststaff{random_num}@university.edu',
            org_unit=org_unit,
            designation_text='Test Position',
            is_active=True,
            is_manager=False
        )
        
        # Generate staff number
        staff.staff_no = generate_staff_number(campus)
        staff.save()
        
        self.stdout.write(self.style.SUCCESS(f'\n✅ Staff created successfully!'))
        self.stdout.write(self.style.SUCCESS(f'Staff No: {staff.staff_no}'))
        self.stdout.write(self.style.SUCCESS(f'Name: {staff.full_name}'))
        self.stdout.write(self.style.SUCCESS(f'Email: {staff.university_email}'))
        self.stdout.write(self.style.SUCCESS(f'Campus: {staff.campus.name}'))
        self.stdout.write(self.style.SUCCESS(f'Org Unit: {staff.org_unit.name}\n'))
