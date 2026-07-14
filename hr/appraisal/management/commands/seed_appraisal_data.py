"""
Management command to seed appraisal data using existing staff records.
Populates Strategic Objectives, Cycles, and Appraisals with NDU-specific data.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime, timedelta
from hr.appraisal.models import (
    StrategicObjective,
    DepartmentalObjective,
    AppraisalCycle,
    Appraisal,
    AppraisalObjective,
    BehavioralCompetency,
    PerformanceFactor,
)
from hr.staff.models import Department, StaffProfile
from accounts.models import Campus


class Command(BaseCommand):
    help = 'Seeds appraisal data using existing staff records'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing appraisal data before seeding',
        )
        parser.add_argument(
            '--strategic-only',
            action='store_true',
            help='Only seed strategic objectives (for supervisor objective dropdown)',
        )

        parser.add_argument(
            '--year',
            type=str,
            default='2024/2025',
            help='Academic year (e.g., 2024/2025)',
        )

    def handle(self, *args, **options):
        clear_data = options['clear']
        academic_year = options['year']
        strategic_only = options['strategic_only']

        self.stdout.write(self.style.SUCCESS(
            f'\n=== Seeding Appraisal Data for {academic_year} ==='
        ))

        if clear_data and not strategic_only:
            self.stdout.write('Clearing existing appraisal data...')
            Appraisal.objects.all().delete()
            AppraisalCycle.objects.all().delete()
            DepartmentalObjective.objects.all().delete()
            StrategicObjective.objects.all().delete()
            self.stdout.write(self.style.WARNING('Existing appraisal data cleared'))

        # Step 1: Create Strategic Objectives (NDU-specific)
        self.create_strategic_objectives()

        if strategic_only:
            self.stdout.write(self.style.SUCCESS(
                '\nStrategic objectives seeded. Run without --strategic-only to seed full demo data.'
            ))
            return

        # Step 2: Create Departmental Objectives
        self.create_departmental_objectives()

        # Step 3: Create Appraisal Cycles for each campus
        cycles = self.create_appraisal_cycles(academic_year)

        # Step 4: Create Appraisals for all staff
        self.create_appraisals(cycles)

        self.stdout.write(self.style.SUCCESS(
            '\nAppraisal data seeding completed successfully!'
        ))

    def create_strategic_objectives(self):
        """Create NDU Strategic Objectives (SO1-SO6)."""
        self.stdout.write('\n1. Creating Strategic Objectives...')

        objectives = [
            {
                'code': 'SO1',
                'title': 'To enhance teaching and learning',
                'description': 'Improve the quality of academic programs and student learning outcomes.'
            },
            {
                'code': 'SO2',
                'title': 'To promote research and innovation',
                'description': 'Foster a culture of research excellence and innovation across the university.'
            },
            {
                'code': 'SO3',
                'title': 'To strengthen community engagement',
                'description': 'Build strong partnerships with communities and stakeholders.'
            },
            {
                'code': 'SO4',
                'title': 'To improve infrastructure and facilities',
                'description': 'Develop and maintain world-class facilities and infrastructure.'
            },
            {
                'code': 'SO5',
                'title': 'To strengthen human resource capacity',
                'description': 'Develop competent and motivated staff through training, recruitment, and retention.'
            },
            {
                'code': 'SO6',
                'title': 'To enhance financial sustainability',
                'description': 'Ensure sound financial management and resource mobilization.'
            },
        ]

        for obj_data in objectives:
            obj, created = StrategicObjective.objects.get_or_create(
                code=obj_data['code'],
                defaults={
                    'title': obj_data['title'],
                    'description': obj_data['description'],
                    'is_active': True
                }
            )
            if created:
                self.stdout.write(f'  Created {obj.code}: {obj.title}')
            else:
                self.stdout.write(f'  - {obj.code} already exists')

    def create_departmental_objectives(self):
        """Create sample departmental objectives linked to strategic objectives."""
        self.stdout.write('\n2. Creating Departmental Objectives...')

        # Get SO5 (Human Resource) - most relevant for all departments
        so5 = StrategicObjective.objects.get(code='SO5')

        # Get all departments
        departments = Department.objects.all()[:10]

        sample_objectives = [
            'Achieve 95% effective recruitment & staffing',
            'Achieve 95% staff training and development participation',
            'Implement fair and transparent reward system',
            'Enhance staff welfare through various schemes',
            'Ensure compliance with performance management procedures',
        ]

        count = 0
        for dept in departments:
            for objective_text in sample_objectives[:2]:  # 2 objectives per department
                obj, created = DepartmentalObjective.objects.get_or_create(
                    strategic_objective=so5,
                    org_unit=dept,
                    objective=objective_text,
                    defaults={'is_active': True}
                )
                if created:
                    count += 1

        self.stdout.write(f'  Created {count} departmental objectives')

    def create_appraisal_cycles(self, academic_year):
        """Create appraisal cycles for each campus."""
        self.stdout.write('\n3. Creating Appraisal Cycles...')

        campuses = Campus.objects.all().order_by("name")
        cycles = []

        # Calculate dates
        current_year = datetime.now().year
        period_from = datetime(current_year, 1, 1).date()
        period_to = datetime(current_year, 12, 31).date()
        review_window_from = datetime(current_year + 1, 1, 1).date()
        review_window_to = datetime(current_year + 1, 1, 31).date()

        for campus in campuses:
            cycle, created = AppraisalCycle.objects.get_or_create(
                campus=campus,
                academic_year=academic_year,
                defaults={
                    'period_from': period_from,
                    'period_to': period_to,
                    'review_window_from': review_window_from,
                    'review_window_to': review_window_to,
                    'status': 'ACTIVE',
                    'is_active': True
                }
            )

            if created:
                self.stdout.write(f'  Created cycle for {campus.name}')
            else:
                self.stdout.write(f'  - Cycle for {campus.name} already exists')

            cycles.append(cycle)

        return cycles

    def create_appraisals(self, cycles):
        """Create appraisals for all staff with objectives and competencies."""
        self.stdout.write('\n4. Creating Appraisals for Staff...')

        # NDU Core Values (Behavioral Competencies)
        core_values = [
            ('GOD_FEARING', 'Consider how staff is devoutly religious and lives according to a moral code inspired by their belief in and reverence for God.'),
            ('RESPECT', 'How staff practices active listening, speaks and acts with kindness and courtesy, and is mindful of feelings, boundaries and personal space.'),
            ('INTEGRITY', 'Measures how staff consistently acts according to strong ethical principles, values and a moral code even when unobserved demonstrating traits like honesty, accountability and reliability.'),
            ('TEAMWORK', 'How well this individual gets along with fellow staff, respects their rights and demonstrates a cooperative spirit.'),
            ('COMMITMENT', 'Consider staff deep personal and professional dedication to achieving specific goals, whether as an individual employee or a team member.'),
            ('INNOVATIVENESS', 'Look at staff successful implementation of new ideas or approaches that improve the performance of a team/services/processes at the University.'),
            ('EQUITY', 'Consider how staff provides fair and impartial evaluations to colleagues, taking into account their unique circumstances and individual needs.'),
            ('EXCELLENCE', 'How staff is consistent in achieving high-quality outcomes through continuous improvement, dedication and superior skills, going beyond basic job requirements to deliver exceptional results and foster a culture of excellence within the university.'),
            ('ACCOUNTABILITY', 'Look at how staff takes responsibility for their actions, decisions, performance and outcomes, including both successes and failures. Additionally accountability takes into consideration how staff is answerable to the supervisor, fosters open communication & provides regular feedback.'),
        ]

        # Performance Factors
        performance_factors = [
            ('PROFESSIONAL_COMPETENCE', 'Understanding and creativity in applying technical and professional knowledge, skills and expertise required for the job.'),
            ('QUALITY_OF_WORK', 'Productivity in terms of accuracy, attention to detail, efficiency, effectiveness.'),
            ('WORK_RELATIONSHIPS', 'Effectiveness in working in/with teams, communicating appropriately, whilst maintaining a good working attitude.'),
            ('LEADERSHIP_SKILLS', 'Only for Managers/Supervisors; ability to plan, organize and delegate work, to lead, motivate, guide and develop staff, communicate, build a team, and maintain a harmonious working environment.'),
        ]

        # Get strategic objective SO5 for objectives
        so5 = StrategicObjective.objects.get(code='SO5')

        total_created = 0
        total_skipped = 0

        for cycle in cycles:
            # Get all staff for this campus
            staff_members = StaffProfile.objects.filter(campus=cycle.campus).distinct()

            self.stdout.write(f'\n  Processing {staff_members.count()} staff for {cycle.campus.name}...')

            for staff in staff_members:
                # Get supervisor (manager of their org unit)
                supervisor = staff.org_unit.managed_by.first() if staff.org_unit else None

                # Check if appraisal already exists
                if Appraisal.objects.filter(cycle=cycle, staff=staff).exists():
                    total_skipped += 1
                    continue

                # Create appraisal
                appraisal = Appraisal.objects.create(
                    cycle=cycle,
                    staff=staff,
                    supervisor=supervisor,
                    status='OBJECTIVES_SET',
                    highest_qualification='',
                    courses_in_progress='',
                )

                # Create 3 sample objectives
                sample_objectives = [
                    {
                        'objective': 'Achieve 95% NDU effective recruitment & Staffing',
                        'tasks': 'Ensure timely notification of vacancies to HR, Work with Department heads to develop & update JDs, Advertise vacancies through appropriate channels.',
                        'target': 95.0,
                        'baseline': 80.0,
                        'weight': 5.0
                    },
                    {
                        'objective': 'Achieve 95% NDU enhancement of staff capabilities through training',
                        'tasks': 'Conduct Orientation & Refresher trainings, Conduct Training needs assessment, Develop/implement training programs.',
                        'target': 95.0,
                        'baseline': 80.0,
                        'weight': 5.0
                    },
                    {
                        'objective': 'Establish a performance management system',
                        'tasks': 'Design and develop a comprehensive performance management system, Provide training to managers and staff, facilitate goal setting.',
                        'target': 95.0,
                        'baseline': 80.0,
                        'weight': 5.0
                    },
                ]

                for obj_data in sample_objectives:
                    AppraisalObjective.objects.create(
                        appraisal=appraisal,
                        strategic_objective=so5,
                        individual_objective=obj_data['objective'],
                        indicative_tasks=obj_data['tasks'],
                        target_percentage=obj_data['target'],
                        baseline_percentage=obj_data['baseline'],
                        weight=obj_data['weight'],
                    )

                # Create behavioral competencies
                for comp_code, comp_desc in core_values:
                    BehavioralCompetency.objects.create(
                        appraisal=appraisal,
                        competency=comp_code,
                        description=comp_desc,
                    )

                # Create performance factors
                for factor_code, factor_desc in performance_factors:
                    # Leadership skills only for managers
                    is_applicable = True
                    is_manager = staff.is_supervisor or staff.is_director
                    if factor_code == 'LEADERSHIP_SKILLS' and not is_manager:
                        is_applicable = False

                    PerformanceFactor.objects.create(
                        appraisal=appraisal,
                        factor=factor_code,
                        description=factor_desc,
                        is_applicable=is_applicable,
                    )

                total_created += 1

                if total_created % 20 == 0:
                    self.stdout.write(f'    ... {total_created} appraisals created')

        self.stdout.write(self.style.SUCCESS(
            f'\n  Created {total_created} appraisals'
        ))
        if total_skipped > 0:
            self.stdout.write(self.style.WARNING(
                f'  - Skipped {total_skipped} existing appraisals'
            ))
