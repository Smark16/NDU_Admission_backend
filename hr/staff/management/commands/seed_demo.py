"""
Management command to seed the database with demo data.
Creates campuses, org units, job titles, and sample staff profiles.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from accounts.models import Campus
from hr.staff.models import OrgUnit, JobTitle, StaffProfile
from hr.staff.utils import generate_staff_number

User = get_user_model()


class Command(BaseCommand):
    help = 'Seeds the database with demo data for testing'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting database seeding...'))
        
        # Create campuses
        self.stdout.write('Creating campuses...')
        main_campus, _ = Campus.objects.get_or_create(
            code='MAIN',
            defaults={
                'name': 'Main Campus',
                'is_active': True
            }
        )
        
        kampus_b, _ = Campus.objects.get_or_create(
            code='KLA',
            defaults={
                'name': 'Kampala Campus',
                'is_active': True
            }
        )
        
        self.stdout.write(self.style.SUCCESS(f'  ✓ Created campuses: {main_campus.code}, {kampus_b.code}'))
        
        # Create organizational units for Main Campus
        self.stdout.write('Creating organizational units...')
        
        org_units_main = [
            ('Sports Department', 'DEPARTMENT'),
            ('Faculty of Law', 'FACULTY'),
            ('Directorate of Students (DOS)', 'UNIT'),
            ('Library', 'UNIT'),
            ('Accounts Department', 'DEPARTMENT'),
            ('Faculty of Engineering Sciences (FoES)', 'FACULTY'),
        ]
        
        created_units_main = {}
        for unit_name, unit_type in org_units_main:
            unit, _ = OrgUnit.objects.get_or_create(
                campus=main_campus,
                name=unit_name,
                defaults={'unit_type': unit_type}
            )
            created_units_main[unit_name] = unit
            self.stdout.write(f'  ✓ {unit_name}')
        
        # Create org units for Kampala Campus
        org_units_kla = [
            ('Business School', 'FACULTY'),
            ('Administration', 'UNIT'),
            ('ICT Department', 'DEPARTMENT'),
        ]
        
        created_units_kla = {}
        for unit_name, unit_type in org_units_kla:
            unit, _ = OrgUnit.objects.get_or_create(
                campus=kampus_b,
                name=unit_name,
                defaults={'unit_type': unit_type}
            )
            created_units_kla[unit_name] = unit
            self.stdout.write(f'  ✓ {unit_name}')
        
        # Create job titles for Main Campus
        self.stdout.write('Creating job titles...')
        
        job_titles_main = [
            'Assistant Lecturer',
            'Administrative Assistant',
            'Records Management Officer',
            'Librarian',
            'Accountant',
            'Sports Coordinator',
            'Senior Lecturer',
            'Professor',
        ]
        
        created_titles_main = {}
        for title_name in job_titles_main:
            title, _ = JobTitle.objects.get_or_create(
                campus=main_campus,
                title=title_name
            )
            created_titles_main[title_name] = title
            self.stdout.write(f'  ✓ {title_name}')
        
        # Create job titles for Kampala Campus
        job_titles_kla = [
            'Lecturer',
            'IT Officer',
            'Administrative Officer',
        ]
        
        created_titles_kla = {}
        for title_name in job_titles_kla:
            title, _ = JobTitle.objects.get_or_create(
                campus=kampus_b,
                title=title_name
            )
            created_titles_kla[title_name] = title
            self.stdout.write(f'  ✓ {title_name}')
        
        # Create sample staff profiles
        self.stdout.write('Creating sample staff profiles...')
        
        sample_staff = [
            {
                'campus': main_campus,
                'full_name': 'John Mukasa',
                'nssf_no': 'NSSF001234',
                'tin_no': 'TIN123456',
                'university_email': 'j.mukasa@university.ac.ug',
                'personal_email': 'jmukasa@gmail.com',
                'job_title': created_titles_main['Assistant Lecturer'],
                'org_unit': created_units_main['Faculty of Law'],
                'date_joined': '2020-01-15',
            },
            {
                'campus': main_campus,
                'full_name': 'Sarah Namubiru',
                'nssf_no': 'NSSF005678',
                'tin_no': 'TIN789012',
                'university_email': 's.namubiru@university.ac.ug',
                'personal_email': 'snamubiru@gmail.com',
                'job_title': created_titles_main['Records Management Officer'],
                'org_unit': created_units_main['Directorate of Students (DOS)'],
                'date_joined': '2019-08-01',
            },
            {
                'campus': main_campus,
                'full_name': 'David Okello',
                'nssf_no': 'NSSF009876',
                'tin_no': 'TIN345678',
                'university_email': 'd.okello@university.ac.ug',
                'personal_email': 'dokello@yahoo.com',
                'job_title': created_titles_main['Librarian'],
                'org_unit': created_units_main['Library'],
                'date_joined': '2018-05-20',
            },
            {
                'campus': main_campus,
                'full_name': 'Grace Atim',
                'nssf_no': 'NSSF012345',
                'tin_no': 'TIN567890',
                'university_email': 'g.atim@university.ac.ug',
                'personal_email': 'gatim@gmail.com',
                'job_title': created_titles_main['Accountant'],
                'org_unit': created_units_main['Accounts Department'],
                'date_joined': '2021-03-10',
            },
            {
                'campus': main_campus,
                'full_name': 'Peter Wasswa',
                'nssf_no': 'NSSF067890',
                'tin_no': 'TIN901234',
                'university_email': 'p.wasswa@university.ac.ug',
                'personal_email': 'pwasswa@gmail.com',
                'job_title': created_titles_main['Sports Coordinator'],
                'org_unit': created_units_main['Sports Department'],
                'date_joined': '2017-09-01',
            },
            {
                'campus': kampus_b,
                'full_name': 'Alice Nansubuga',
                'nssf_no': 'NSSF054321',
                'tin_no': 'TIN654321',
                'university_email': 'a.nansubuga@university.ac.ug',
                'personal_email': 'anansubuga@gmail.com',
                'job_title': created_titles_kla['Lecturer'],
                'org_unit': created_units_kla['Business School'],
                'date_joined': '2020-06-15',
            },
        ]
        
        for staff_data in sample_staff:
            staff_no = generate_staff_number(staff_data['campus'])
            staff, created = StaffProfile.objects.get_or_create(
                university_email=staff_data['university_email'],
                defaults={
                    **staff_data,
                    'staff_no': staff_no,
                    'is_active': True
                }
            )
            if created:
                self.stdout.write(self.style.SUCCESS(
                    f'  ✓ Created: {staff.full_name} ({staff.staff_no})'
                ))
            else:
                self.stdout.write(self.style.WARNING(
                    f'  • Already exists: {staff.full_name}'
                ))
        
        # Create HR Admin user
        self.stdout.write('Creating HR Admin user...')
        hr_admin, created = User.objects.get_or_create(
            username='hradmin',
            defaults={
                'email': 'hradmin@university.ac.ug',
                'user_type': 'HR_ADMIN',
                'campus': main_campus,
                'is_staff': True,
                'first_name': 'HR',
                'last_name': 'Administrator'
            }
        )
        if created:
            hr_admin.set_password('admin123')
            hr_admin.save()
            self.stdout.write(self.style.SUCCESS(
                f'  ✓ HR Admin created - Username: hradmin, Password: admin123'
            ))
        else:
            self.stdout.write(self.style.WARNING('  • HR Admin already exists'))
        
        # Create a staff user with profile
        self.stdout.write('Creating staff user with profile...')
        staff_user, created = User.objects.get_or_create(
            username='jmukasa',
            defaults={
                'email': 'j.mukasa@university.ac.ug',
                'user_type': 'STAFF',
                'campus': main_campus,
                'first_name': 'John',
                'last_name': 'Mukasa'
            }
        )
        if created:
            staff_user.set_password('staff123')
            staff_user.save()
            
            # Link to existing staff profile
            try:
                staff_profile = StaffProfile.objects.get(
                    university_email='j.mukasa@university.ac.ug'
                )
                staff_profile.user = staff_user
                staff_profile.save()
                self.stdout.write(self.style.SUCCESS(
                    f'  ✓ Staff user created and linked - Username: jmukasa, Password: staff123'
                ))
            except StaffProfile.DoesNotExist:
                self.stdout.write(self.style.WARNING(
                    '  • Staff user created but no profile found to link'
                ))
        else:
            self.stdout.write(self.style.WARNING('  • Staff user already exists'))
        
        # Create superuser if doesn't exist
        self.stdout.write('Checking for superuser...')
        if not User.objects.filter(is_superuser=True).exists():
            superuser = User.objects.create_superuser(
                username='admin',
                email='admin@university.ac.ug',
                password='admin123',
                user_type='HR_ADMIN',
                campus=main_campus
            )
            self.stdout.write(self.style.SUCCESS(
                '  ✓ Superuser created - Username: admin, Password: admin123'
            ))
        else:
            self.stdout.write(self.style.WARNING('  • Superuser already exists'))
        
        # Print summary
        self.stdout.write('\n' + '='*60)
        self.stdout.write(self.style.SUCCESS('DATABASE SEEDING COMPLETED!'))
        self.stdout.write('='*60)
        self.stdout.write('\nLOGIN CREDENTIALS:')
        self.stdout.write('-'*60)
        self.stdout.write(self.style.SUCCESS('Superuser:'))
        self.stdout.write('  Username: admin')
        self.stdout.write('  Password: admin123')
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('HR Admin:'))
        self.stdout.write('  Username: hradmin')
        self.stdout.write('  Password: admin123')
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Staff User (with profile):'))
        self.stdout.write('  Username: jmukasa')
        self.stdout.write('  Password: staff123')
        self.stdout.write('-'*60)
        self.stdout.write(f'\nTotal Staff Profiles: {StaffProfile.objects.count()}')
        self.stdout.write(f'Total Campuses: {Campus.objects.count()}')
        self.stdout.write(f'Total Org Units: {OrgUnit.objects.count()}')
        self.stdout.write(f'Total Job Titles: {JobTitle.objects.count()}')
        self.stdout.write('='*60 + '\n')

