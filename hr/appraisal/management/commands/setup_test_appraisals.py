"""
Create test appraisals and staff for demonstration.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime, timedelta
from hr.staff.models import StaffProfile, OrgUnit
from hr.appraisal.models import (
    AppraisalCycle, 
    Appraisal, 
    AppraisalObjective,
    BehavioralCompetency,
    PerformanceFactor,
    StrategicObjective
)
from accounts.models import Campus
from hr.staff.utils import generate_staff_number


class Command(BaseCommand):
    help = 'Setup test appraisals and staff members'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('\n=== Creating Test Data ===\n'))
        
        # Get campus and units
        try:
            campus = Campus.objects.first()
            if not campus:
                self.stdout.write(self.style.ERROR('No campus found. Please create a campus first.'))
                return
            
            dicts = OrgUnit.objects.filter(name__icontains='Directorate of ICT').first()
            ais_team = OrgUnit.objects.filter(name__icontains='AIS Team').first()
            network_team = OrgUnit.objects.filter(name__icontains='Network').first()
            sfmi_team = OrgUnit.objects.filter(name__icontains='SFMI').first()
            
            if not dicts:
                self.stdout.write(self.style.ERROR('Directorate of ICT not found'))
                return
            
            # Get Ikasan (director)
            ikasan = StaffProfile.objects.filter(full_name__icontains='Isaac').first()
            
            # 1. CREATE MORE STAFF IN TEAMS
            self.stdout.write('Creating staff members...')
            
            staff_data = [
                {'name': 'Alice Nakato', 'unit': ais_team, 'designation': 'Senior Developer'},
                {'name': 'Bob Mukasa', 'unit': ais_team, 'designation': 'Systems Analyst'},
                {'name': 'Carol Nambi', 'unit': ais_team, 'designation': 'Junior Developer'},
                {'name': 'David Okello', 'unit': network_team, 'designation': 'Network Administrator'},
                {'name': 'Emma Namusoke', 'unit': network_team, 'designation': 'Infrastructure Specialist'},
                {'name': 'Frank Ssali', 'unit': sfmi_team, 'designation': 'Database Administrator'},
                {'name': 'Grace Atim', 'unit': sfmi_team, 'designation': 'Software Engineer'},
                {'name': 'Henry Ouma', 'unit': dicts, 'designation': 'IT Officer'},
            ]
            
            created_staff = []
            for data in staff_data:
                if data['unit']:  # Only create if unit exists
                    # Check if staff already exists
                    email = f"{data['name'].lower().replace(' ', '.')}@university.edu"
                    existing = StaffProfile.objects.filter(university_email=email).first()
                    
                    if existing:
                        created_staff.append(existing)
                        self.stdout.write(f'  → Exists: {existing.staff_no} - {existing.full_name} ({data["unit"].name})')
                    else:
                        staff = StaffProfile.objects.create(
                            campus=campus,
                            full_name=data['name'],
                            designation_text=data['designation'],
                            org_unit=data['unit'],
                            is_active=True,
                            is_manager=False,
                            supervisor=ikasan,  # Ikasan is their supervisor
                            position_level='REGULAR',
                            university_email=email
                        )
                        staff.staff_no = generate_staff_number(campus)
                        staff.save()
                        created_staff.append(staff)
                        self.stdout.write(f'  ✓ Created: {staff.staff_no} - {staff.full_name} ({data["unit"].name})')
            
            # 2. CREATE STRATEGIC OBJECTIVES
            self.stdout.write('\nCreating strategic objectives...')
            strategic_objs = []
            
            obj_data = [
                {'code': 'SO1', 'title': 'Improve Student Experience', 'desc': 'Enhance digital services for students'},
                {'code': 'SO2', 'title': 'Digital Transformation', 'desc': 'Modernize IT infrastructure'},
                {'code': 'SO3', 'title': 'Staff Development', 'desc': 'Build technical capacity'},
            ]
            
            for obj in obj_data:
                strategic_obj, created = StrategicObjective.objects.get_or_create(
                    code=obj['code'],
                    defaults={
                        'title': obj['title'],
                        'description': obj['desc'],
                        'is_active': True
                    }
                )
                strategic_objs.append(strategic_obj)
                status = 'Created' if created else 'Exists'
                self.stdout.write(f'  ✓ {status}: {strategic_obj.code} - {strategic_obj.title}')
            
            # 3. CREATE APPRAISAL CYCLE
            self.stdout.write('\nCreating appraisal cycle...')
            
            current_year = datetime.now().year
            cycle, created = AppraisalCycle.objects.get_or_create(
                campus=campus,
                academic_year=f'{current_year}/{current_year + 1}',
                defaults={
                    'period_from': datetime(current_year, 1, 1).date(),
                    'period_to': datetime(current_year, 12, 31).date(),
                    'review_window_from': datetime(current_year, 11, 1).date(),
                    'review_window_to': datetime(current_year, 12, 31).date(),
                    'status': 'ACTIVE',
                    'is_active': True
                }
            )
            
            if created:
                self.stdout.write(f'  ✓ Created cycle: {cycle.academic_year}')
            else:
                cycle.is_active = True
                cycle.status = 'ACTIVE'
                cycle.save()
                self.stdout.write(f'  ✓ Activated existing cycle: {cycle.academic_year}')
            
            # 4. CREATE APPRAISALS FOR ALL STAFF
            self.stdout.write('\nCreating appraisals...')
            
            all_staff = StaffProfile.objects.filter(campus=campus, is_active=True)
            appraisals_created = 0
            
            for staff in all_staff:
                # Check if appraisal already exists
                appraisal, created = Appraisal.objects.get_or_create(
                    cycle=cycle,
                    staff=staff,
                    defaults={
                        'supervisor': staff.supervisor if staff.supervisor else ikasan,
                        'status': 'DRAFT',
                        'created_at': timezone.now()
                    }
                )
                
                if created:
                    appraisals_created += 1
                    
                    # Add 2-3 objectives for each appraisal
                    for i, strategic_obj in enumerate(strategic_objs[:2]):
                        AppraisalObjective.objects.create(
                            appraisal=appraisal,
                            strategic_objective=strategic_obj,
                            individual_objective=f'Contribute to {strategic_obj.title.lower()}',
                            indicative_tasks=f'Complete assigned tasks related to {strategic_obj.code}',
                            target_percentage=95,
                            baseline_percentage=80,
                            weight=50 if i == 0 else 50
                        )
                    
                    # Add behavioral competencies (NDU Core Values)
                    competencies = [
                        ('TEAMWORK', 'Works effectively with team members and contributes to group goals'),
                        ('INTEGRITY', 'Demonstrates honesty and ethical behavior in all activities'),
                        ('COMMITMENT', 'Shows dedication and reliability in fulfilling responsibilities'),
                        ('INNOVATIVENESS', 'Brings creative solutions and new ideas to work'),
                        ('EXCELLENCE', 'Strives for high quality and continuous improvement'),
                    ]
                    
                    for comp_code, comp_desc in competencies:
                        BehavioralCompetency.objects.create(
                            appraisal=appraisal,
                            competency=comp_code,
                            description=comp_desc
                        )
                    
                    # Add performance factors
                    factors = [
                        ('PROFESSIONAL_COMPETENCE', 'Technical knowledge and skills in area of work'),
                        ('QUALITY_OF_WORK', 'Standard, accuracy and thoroughness of work output'),
                        ('WORK_RELATIONSHIPS', 'Ability to work with colleagues and stakeholders'),
                    ]
                    
                    for factor_code, factor_desc in factors:
                        PerformanceFactor.objects.create(
                            appraisal=appraisal,
                            factor=factor_code,
                            description=factor_desc,
                            is_applicable=True
                        )
                    
                    self.stdout.write(f'  ✓ Created appraisal for: {staff.full_name}')
            
            # 5. SUMMARY
            self.stdout.write(self.style.SUCCESS('\n=== SUMMARY ==='))
            self.stdout.write(f'Staff created: {len(created_staff)}')
            self.stdout.write(f'Strategic objectives: {len(strategic_objs)}')
            self.stdout.write(f'Appraisal cycle: {cycle.academic_year}')
            self.stdout.write(f'Appraisals created: {appraisals_created}')
            self.stdout.write(f'Total appraisals in system: {Appraisal.objects.filter(cycle=cycle).count()}')
            
            self.stdout.write(self.style.SUCCESS('\n✓ Setup complete! Ikasan can now see team appraisals.'))
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'\nError: {str(e)}'))
            import traceback
            self.stdout.write(traceback.format_exc())
