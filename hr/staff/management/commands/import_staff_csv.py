"""
Management command to import staff profiles from a CSV file.
"""
import csv
from datetime import datetime
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from accounts.models import Campus
from hr.staff.models import OrgUnit, JobTitle, StaffProfile
from hr.staff.utils import generate_staff_number


class Command(BaseCommand):
    help = 'Import staff profiles from a CSV file'

    def add_arguments(self, parser):
        parser.add_argument('csv_file', type=str, help='Path to the CSV file')
        parser.add_argument('--campus-code', type=str, required=True, 
                          help='Campus code to associate with imported staff')

    def handle(self, *args, **options):
        csv_file_path = options['csv_file']
        campus_code = options['campus_code']

        try:
            campus = Campus.objects.get(code=campus_code)
        except Campus.DoesNotExist:
            raise CommandError(f'Campus with code "{campus_code}" does not exist.')

        try:
            with open(csv_file_path, 'r', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                created_count = 0
                updated_count = 0
                
                for row_num, row in enumerate(reader, start=2):  # Start at 2 to account for header
                    try:
                        with transaction.atomic():
                            # Extract data from CSV row using university-specific column names
                            # Support both the original and university-specific column names
                            full_name = row.get('Name', '').strip() or row.get('full_name', '').strip()
                            university_email = row.get('University Email', '').strip() or row.get('university_email', '').strip()
                            personal_email = row.get('Personal Email', '').strip() or row.get('personal_email', '').strip()
                            nssf_no = row.get('NSSF No', '').strip() or row.get('nssf_no', '').strip() or None
                            tin_no = row.get('TIN No', '').strip() or row.get('tin_no', '').strip() or None
                            org_unit_name = row.get('Faculty/Department/Unit', '').strip() or row.get('org_unit', '').strip()
                            job_title_name = row.get('Designation', '').strip() or row.get('job_title', '').strip()
                            designation_text = row.get('Designation', '').strip() or row.get('designation_text', '').strip()
                            date_joined_str = row.get('date_joined', '').strip()
                            is_active = row.get('is_active', 'true').lower() in ['true', '1', 'yes', 'on']
                            
                            # Validate required fields
                            if not full_name:
                                self.stdout.write(
                                    self.style.WARNING(f'Row {row_num}: Missing required field "full_name", skipping.')
                                )
                                continue
                            
                            # Process date_joined if provided
                            date_joined = None
                            if date_joined_str:
                                try:
                                    date_joined = datetime.strptime(date_joined_str, '%Y-%m-%d').date()
                                except ValueError:
                                    try:
                                        date_joined = datetime.strptime(date_joined_str, '%m/%d/%Y').date()
                                    except ValueError:
                                        self.stdout.write(
                                            self.style.WARNING(f'Row {row_num}: Invalid date format for "date_joined", using None.')
                                        )
                            
                            # Get or create OrgUnit
                            org_unit = None
                            if org_unit_name:
                                org_unit, _ = OrgUnit.objects.get_or_create(
                                    name=org_unit_name,
                                    campus=campus,
                                    defaults={'unit_type': 'UNIT'}  # Default to UNIT if not specified
                                )
                            
                            # Get or create JobTitle
                            job_title = None
                            if job_title_name:
                                job_title, _ = JobTitle.objects.get_or_create(
                                    title=job_title_name,
                                    campus=campus
                                )
                            
                            # Check if staff profile already exists (by email)
                            staff_profile = None
                            if university_email:
                                staff_profile, created = StaffProfile.objects.get_or_create(
                                    university_email=university_email,
                                    defaults={
                                        'campus': campus,
                                        'full_name': full_name,
                                        'nssf_no': nssf_no,
                                        'tin_no': tin_no,
                                        'personal_email': personal_email,
                                        'job_title': job_title,
                                        'designation_text': designation_text,
                                        'org_unit': org_unit,
                                        'date_joined': date_joined,
                                        'is_active': is_active,
                                    }
                                )
                                if created:
                                    # Generate staff number for new profiles
                                    staff_profile.staff_no = generate_staff_number(campus)
                                    staff_profile.save()
                                    created_count += 1
                                else:
                                    # Update existing profile
                                    staff_profile.full_name = full_name
                                    staff_profile.nssf_no = nssf_no
                                    staff_profile.tin_no = tin_no
                                    staff_profile.personal_email = personal_email
                                    staff_profile.job_title = job_title
                                    staff_profile.designation_text = designation_text
                                    staff_profile.org_unit = org_unit
                                    staff_profile.date_joined = date_joined
                                    staff_profile.is_active = is_active
                                    staff_profile.save()
                                    updated_count += 1
                            else:
                                # Create new profile without email
                                staff_profile = StaffProfile.objects.create(
                                    campus=campus,
                                    full_name=full_name,
                                    nssf_no=nssf_no,
                                    tin_no=tin_no,
                                    university_email=university_email or None,
                                    personal_email=personal_email or None,
                                    job_title=job_title,
                                    designation_text=designation_text,
                                    org_unit=org_unit,
                                    date_joined=date_joined,
                                    is_active=is_active,
                                )
                                # Generate staff number
                                staff_profile.staff_no = generate_staff_number(campus)
                                staff_profile.save()
                                created_count += 1
                                
                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(f'Row {row_num}: Error processing row - {str(e)}')
                        )
                        continue
                
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Successfully imported staff profiles: {created_count} created, {updated_count} updated.'
                    )
                )
                
        except FileNotFoundError:
            raise CommandError(f'File "{csv_file_path}" does not exist.')
        except Exception as e:
            raise CommandError(f'Error importing CSV: {str(e)}')