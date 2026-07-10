"""
Management command to demonstrate hierarchical organizational structure.
Creates a sample hierarchy with Faculty > Departments > Units and assigns managers.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from accounts.models import Campus
from hr.staff.models import OrgUnit, StaffProfile

User = get_user_model()


class Command(BaseCommand):
    help = 'Create sample hierarchical org structure with managers at each level'

    def handle(self, *args, **options):
        self.stdout.write('Creating hierarchical organizational structure...\n')
        
        # Get or create campus
        campus, created = Campus.objects.get_or_create(
            code='MAIN',
            defaults={'name': 'Main Campus', 'is_active': True}
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'✓ Created campus: {campus.name}'))
        else:
            self.stdout.write(f'  Using existing campus: {campus.name}')
        
        # Create Faculty of Engineering (Level 0 - Root)
        faculty_eng, created = OrgUnit.objects.get_or_create(
            campus=campus,
            name='Faculty of Engineering',
            defaults={'unit_type': 'FACULTY', 'parent': None}
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'✓ Created: {faculty_eng.name} (Level {faculty_eng.get_level()})'))
        
        # Create Departments under Engineering (Level 1)
        dept_cs, created = OrgUnit.objects.get_or_create(
            campus=campus,
            name='Department of Computer Science',
            defaults={'unit_type': 'DEPARTMENT', 'parent': faculty_eng}
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'  ✓ Created: {dept_cs.name} (Level {dept_cs.get_level()})'))
        
        dept_ee, created = OrgUnit.objects.get_or_create(
            campus=campus,
            name='Department of Electrical Engineering',
            defaults={'unit_type': 'DEPARTMENT', 'parent': faculty_eng}
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'  ✓ Created: {dept_ee.name} (Level {dept_ee.get_level()})'))
        
        # Create Units under CS Department (Level 2)
        unit_ai, created = OrgUnit.objects.get_or_create(
            campus=campus,
            name='AI Research Lab',
            defaults={'unit_type': 'UNIT', 'parent': dept_cs}
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'    ✓ Created: {unit_ai.name} (Level {unit_ai.get_level()})'))
        
        unit_software, created = OrgUnit.objects.get_or_create(
            campus=campus,
            name='Software Engineering Unit',
            defaults={'unit_type': 'UNIT', 'parent': dept_cs}
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'    ✓ Created: {unit_software.name} (Level {unit_software.get_level()})'))
        
        # Create Units under EE Department (Level 2)
        unit_power, created = OrgUnit.objects.get_or_create(
            campus=campus,
            name='Power Systems Unit',
            defaults={'unit_type': 'UNIT', 'parent': dept_ee}
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'    ✓ Created: {unit_power.name} (Level {unit_power.get_level()})'))
        
        self.stdout.write('\n' + '='*70)
        self.stdout.write('Organizational Hierarchy:')
        self.stdout.write('='*70 + '\n')
        
        # Display hierarchy
        self.display_hierarchy(faculty_eng, 0)
        
        self.stdout.write('\n' + '='*70)
        self.stdout.write('Creating Sample Staff and Managers:')
        self.stdout.write('='*70 + '\n')
        
        # Create Dean of Engineering (manages entire faculty)
        dean_user, created = User.objects.get_or_create(
            username='dean.engineering',
            defaults={
                'email': 'dean.eng@university.edu',
                'user_type': 'MANAGER',
                'campus': campus
            }
        )
        if created:
            dean_user.set_password('password123')
            dean_user.save()
        
        dean_profile, created = StaffProfile.objects.get_or_create(
            user=dean_user,
            defaults={
                'campus': campus,
                'full_name': 'Dr. John Dean',
                'org_unit': faculty_eng,
                'is_manager': True,
                'managed_org_unit': faculty_eng,
                'staff_no': 'NDU-STF-DEAN01',
                'university_email': 'dean.eng@university.edu'
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(
                f'✓ Created Dean: {dean_profile.full_name} (manages {faculty_eng.name})'
            ))
            descendants = faculty_eng.get_all_descendants()
            self.stdout.write(f'  → Can view staff in {len(descendants) + 1} units:')
            self.stdout.write(f'     - {faculty_eng.name}')
            for desc in descendants:
                self.stdout.write(f'     - {desc.name}')
        
        # Create HOD Computer Science (manages CS department and its units)
        hod_cs_user, created = User.objects.get_or_create(
            username='hod.cs',
            defaults={
                'email': 'hod.cs@university.edu',
                'user_type': 'MANAGER',
                'campus': campus
            }
        )
        if created:
            hod_cs_user.set_password('password123')
            hod_cs_user.save()
        
        hod_cs_profile, created = StaffProfile.objects.get_or_create(
            user=hod_cs_user,
            defaults={
                'campus': campus,
                'full_name': 'Dr. Jane Smith',
                'org_unit': dept_cs,
                'is_manager': True,
                'managed_org_unit': dept_cs,
                'staff_no': 'NDU-STF-HOD01',
                'university_email': 'hod.cs@university.edu'
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(
                f'✓ Created HOD: {hod_cs_profile.full_name} (manages {dept_cs.name})'
            ))
            descendants = dept_cs.get_all_descendants()
            self.stdout.write(f'  → Can view staff in {len(descendants) + 1} units:')
            self.stdout.write(f'     - {dept_cs.name}')
            for desc in descendants:
                self.stdout.write(f'     - {desc.name}')
        
        # Create some regular staff in different units
        staff_data = [
            ('AI Lab Researcher', unit_ai, 'ai.researcher@university.edu'),
            ('Software Engineer', unit_software, 'sw.engineer@university.edu'),
            ('Power Systems Specialist', unit_power, 'power.spec@university.edu'),
        ]
        
        for idx, (name, org_unit, email) in enumerate(staff_data, start=1):
            staff, created = StaffProfile.objects.get_or_create(
                university_email=email,
                defaults={
                    'campus': campus,
                    'full_name': name,
                    'org_unit': org_unit,
                    'staff_no': f'NDU-STF-{idx:06d}',
                }
            )
            if created:
                self.stdout.write(f'  ✓ Created staff: {name} in {org_unit.name}')
        
        self.stdout.write('\n' + '='*70)
        self.stdout.write('Manager Access Summary:')
        self.stdout.write('='*70 + '\n')
        
        self.stdout.write(f'\n1. Dean ({dean_profile.full_name}):')
        self.stdout.write(f'   Manages: {faculty_eng.name}')
        self.stdout.write(f'   Can view ALL staff in Faculty of Engineering')
        self.stdout.write(f'   Total units accessible: {len(faculty_eng.get_all_descendants()) + 1}')
        
        self.stdout.write(f'\n2. HOD Computer Science ({hod_cs_profile.full_name}):')
        self.stdout.write(f'   Manages: {dept_cs.name}')
        self.stdout.write(f'   Can view staff in CS Department and all its sub-units')
        self.stdout.write(f'   Total units accessible: {len(dept_cs.get_all_descendants()) + 1}')
        
        self.stdout.write('\n' + '='*70)
        self.stdout.write(self.style.SUCCESS('\n✓ Hierarchy setup complete!\n'))
        self.stdout.write('Login credentials:')
        self.stdout.write('  Dean: username=dean.engineering, password=password123')
        self.stdout.write('  HOD CS: username=hod.cs, password=password123')
        self.stdout.write('\nTest by logging in and viewing Staff Management.')
    
    def display_hierarchy(self, org_unit, level):
        """Recursively display org unit hierarchy."""
        indent = '  ' * level
        icon = '📁' if org_unit.unit_type == 'FACULTY' else '📂' if org_unit.unit_type == 'DEPARTMENT' else '📄'
        self.stdout.write(f'{indent}{icon} {org_unit.name} ({org_unit.get_unit_type_display()})')
        self.stdout.write(f'{indent}   Path: {org_unit.get_hierarchy_path()}')
        
        # Show children
        children = org_unit.children.all()
        for child in children:
            self.display_hierarchy(child, level + 1)
