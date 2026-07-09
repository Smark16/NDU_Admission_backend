"""
Management command to set up Directorate of ICT (DICTS) organizational structure.
Example of team-based structure within a directorate.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from accounts.models import Campus
from hr.staff.models import OrgUnit, StaffProfile

User = get_user_model()


class Command(BaseCommand):
    help = 'Set up DICTS (Directorate of ICT) structure with teams'

    def handle(self, *args, **options):
        self.stdout.write('='*70)
        self.stdout.write(self.style.HTTP_INFO('Setting up DICTS Organizational Structure'))
        self.stdout.write('='*70 + '\n')
        
        # Get or create campus
        campus, created = Campus.objects.get_or_create(
            code='MAIN',
            defaults={'name': 'Main Campus', 'is_active': True}
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'✓ Created campus: {campus.name}'))
        else:
            self.stdout.write(f'  Using existing campus: {campus.name}')
        
        # Create Directorate of ICT (DICTS)
        dicts, created = OrgUnit.objects.get_or_create(
            campus=campus,
            name='Directorate of ICT (DICTS)',
            defaults={
                'unit_type': 'DEPARTMENT',
                'parent': None  # Top-level directorate
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(
                f'✓ Created: {dicts.name}'
            ))
        
        # Create Teams under DICTS
        teams_data = [
            {
                'name': 'SFMI Team',
                'description': 'Systems, Finance and Management Information Team'
            },
            {
                'name': 'AIS Team',
                'description': 'Academic Information Systems Team'
            },
            {
                'name': 'Network & Infrastructure Team',
                'description': 'Network and Infrastructure Management Team'
            }
        ]
        
        teams = {}
        for team_data in teams_data:
            team, created = OrgUnit.objects.get_or_create(
                campus=campus,
                name=team_data['name'],
                defaults={
                    'unit_type': 'UNIT',
                    'parent': dicts  # Teams are children of DICTS
                }
            )
            teams[team_data['name']] = team
            if created:
                self.stdout.write(self.style.SUCCESS(
                    f'  ✓ Created team: {team.name}'
                ))
        
        self.stdout.write('\n' + '='*70)
        self.stdout.write('DICTS Organizational Structure:')
        self.stdout.write('='*70 + '\n')
        
        self.display_hierarchy(dicts, 0)
        
        self.stdout.write('\n' + '='*70)
        self.stdout.write('Creating Director and Team Leaders:')
        self.stdout.write('='*70 + '\n')
        
        # Create Director Isaac Kasana
        isaac_user, created = User.objects.get_or_create(
            username='isaac.kasana',
            defaults={
                'email': 'isaac.kasana@university.edu',
                'user_type': 'MANAGER',
                'campus': campus
            }
        )
        if created:
            isaac_user.set_password('password123')
            isaac_user.save()
        
        isaac_profile, created = StaffProfile.objects.get_or_create(
            user=isaac_user,
            defaults={
                'campus': campus,
                'full_name': 'Isaac Kasana',
                'org_unit': dicts,  # Works in DICTS directorate
                'is_manager': True,
                'managed_org_unit': dicts,  # Manages entire DICTS
                'staff_no': 'MAIN-STF-DIR01',
                'university_email': 'isaac.kasana@university.edu',
                'designation_text': 'Director of ICT'
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(
                f'✓ Created Director: {isaac_profile.full_name}'
            ))
            self.stdout.write(f'  → Manages: {dicts.name}')
            descendants = dicts.get_all_descendants()
            self.stdout.write(f'  → Can view staff in {len(descendants) + 1} units:')
            self.stdout.write(f'     - {dicts.name}')
            for desc in descendants:
                self.stdout.write(f'     - {desc.name}')
        
        # Create Team Leaders
        team_leaders = [
            {
                'username': 'sfmi.leader',
                'full_name': 'John Doe',
                'team': teams['SFMI Team'],
                'designation': 'Team Leader - SFMI'
            },
            {
                'username': 'ais.leader',
                'full_name': 'Jane Smith',
                'team': teams['AIS Team'],
                'designation': 'Team Leader - AIS'
            },
            {
                'username': 'network.leader',
                'full_name': 'Bob Johnson',
                'team': teams['Network & Infrastructure Team'],
                'designation': 'Team Leader - Network & Infrastructure'
            }
        ]
        
        for leader_data in team_leaders:
            user, created = User.objects.get_or_create(
                username=leader_data['username'],
                defaults={
                    'email': f"{leader_data['username']}@university.edu",
                    'user_type': 'MANAGER',
                    'campus': campus
                }
            )
            if created:
                user.set_password('password123')
                user.save()
            
            profile, created = StaffProfile.objects.get_or_create(
                user=user,
                defaults={
                    'campus': campus,
                    'full_name': leader_data['full_name'],
                    'org_unit': leader_data['team'],
                    'is_manager': True,
                    'managed_org_unit': leader_data['team'],
                    'staff_no': f"MAIN-STF-{leader_data['username'].upper()}",
                    'university_email': f"{leader_data['username']}@university.edu",
                    'designation_text': leader_data['designation']
                }
            )
            if created:
                self.stdout.write(self.style.SUCCESS(
                    f'\n✓ Created Team Leader: {profile.full_name}'
                ))
                self.stdout.write(f'  → Team: {leader_data["team"].name}')
                self.stdout.write(f'  → Can view staff in this team only')
        
        # Create some team members
        team_members = [
            {
                'full_name': 'Alice Developer',
                'team': teams['SFMI Team'],
                'email': 'alice.dev@university.edu',
                'designation': 'Software Developer'
            },
            {
                'full_name': 'Charlie Analyst',
                'team': teams['AIS Team'],
                'email': 'charlie.analyst@university.edu',
                'designation': 'Systems Analyst'
            },
            {
                'full_name': 'David Engineer',
                'team': teams['Network & Infrastructure Team'],
                'email': 'david.eng@university.edu',
                'designation': 'Network Engineer'
            }
        ]
        
        self.stdout.write('\n' + '='*70)
        self.stdout.write('Creating Team Members:')
        self.stdout.write('='*70 + '\n')
        
        for member_data in team_members:
            member, created = StaffProfile.objects.get_or_create(
                university_email=member_data['email'],
                defaults={
                    'campus': campus,
                    'full_name': member_data['full_name'],
                    'org_unit': member_data['team'],
                    'staff_no': f"MAIN-STF-{member_data['full_name'].replace(' ', '-').upper()}",
                    'designation_text': member_data['designation']
                }
            )
            if created:
                self.stdout.write(f'  ✓ Created: {member.full_name} in {member_data["team"].name}')
        
        self.stdout.write('\n' + '='*70)
        self.stdout.write('Access Control Summary:')
        self.stdout.write('='*70 + '\n')
        
        self.stdout.write(f'\n1. Director Isaac Kasana:')
        self.stdout.write(f'   Manages: {dicts.name}')
        self.stdout.write(f'   Can view: ALL staff in DICTS + all teams')
        self.stdout.write(f'   Total units accessible: {len(dicts.get_all_descendants()) + 1}')
        
        self.stdout.write(f'\n2. Team Leaders:')
        for leader_data in team_leaders:
            self.stdout.write(f'   {leader_data["full_name"]}:')
            self.stdout.write(f'     - Manages: {leader_data["team"].name}')
            self.stdout.write(f'     - Can view: Only staff in their team')
        
        self.stdout.write('\n' + '='*70)
        self.stdout.write(self.style.SUCCESS('\n✓ DICTS structure setup complete!\n'))
        self.stdout.write('Login credentials (all use password: password123):')
        self.stdout.write('  Director: username=isaac.kasana')
        self.stdout.write('  SFMI Leader: username=sfmi.leader')
        self.stdout.write('  AIS Leader: username=ais.leader')
        self.stdout.write('  Network Leader: username=network.leader')
        self.stdout.write('\nTest by logging in and viewing Staff Management.')
        self.stdout.write('Each user will see only the staff they manage.')
    
    def display_hierarchy(self, org_unit, level):
        """Recursively display org unit hierarchy."""
        indent = '  ' * level
        
        if level == 0:
            icon = '🏢'  # Directorate
        elif level == 1:
            icon = '👥'  # Team
        else:
            icon = '📄'
        
        self.stdout.write(f'{indent}{icon} {org_unit.name}')
        
        # Show children
        children = org_unit.children.all()
        for child in children:
            self.display_hierarchy(child, level + 1)
