"""
Management command to safely clear all data from the database.
This removes all records but preserves the database schema.
"""
from django.core.management.base import BaseCommand
from django.db import connection
from django.apps import apps


class Command(BaseCommand):
    help = 'Clear all data from the database (preserves schema)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--yes',
            action='store_true',
            help='Confirm deletion without prompting',
        )

    def handle(self, *args, **options):
        if not options['yes']:
            confirm = input(
                "\n⚠️  WARNING: This will delete ALL data from the database!\n"
                "This action cannot be undone.\n"
                "Type 'DELETE ALL DATA' to confirm: "
            )
            if confirm != 'DELETE ALL DATA':
                self.stdout.write(self.style.WARNING('Operation cancelled.'))
                return

        self.stdout.write(self.style.WARNING('\n🗑️  Starting data deletion...'))
        
        # Get all models in dependency order (reverse)
        models_to_clear = [
            # Leave module
            'leave.LeaveAccrual',
            'leave.LeaveApproval',
            'leave.LeaveRequest',
            'leave.LeaveBalance',
            'leave.LeavePolicy',
            'leave.LeaveType',
            
            # Onboarding module
            'onboarding.OnboardingTaskCompletion',
            'onboarding.OnboardingChecklistItem',
            'onboarding.OnboardingChecklist',
            'onboarding.OnboardingSession',
            'onboarding.OnboardingTemplate',
            
            # Hiring module
            'hiring.InterviewFeedback',
            'hiring.Interview',
            'hiring.JobOffer',
            'hiring.JobApplication',
            'hiring.JobPosting',
            
            # Appraisal module
            'appraisal.AppraisalComment',
            'appraisal.GoalProgress',
            'appraisal.AppraisalRating',
            'appraisal.AppraisalReview',
            'appraisal.PerformanceGoal',
            'appraisal.AppraisalCycle',
            'appraisal.CompetencyCategory',
            'appraisal.Competency',
            
            # Staff module
            'staff.StaffProfile',
            
            # Common module
            'common.OrganizationalUnit',
            'common.Campus',
            
            # Accounts module
            'accounts.CustomUser',
            
            # Auth/Session data
            'auth.Permission',
            'contenttypes.ContentType',
            'sessions.Session',
            'admin.LogEntry',
        ]
        
        deleted_counts = {}
        total_deleted = 0
        
        # Disable foreign key checks temporarily (SQLite)
        if connection.vendor == 'sqlite':
            with connection.cursor() as cursor:
                cursor.execute('PRAGMA foreign_keys = OFF;')
        elif connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute('SET CONSTRAINTS ALL DEFERRED;')
        
        for model_path in models_to_clear:
            try:
                app_label, model_name = model_path.split('.')
                model = apps.get_model(app_label, model_name)
                count = model.objects.count()
                
                if count > 0:
                    model.objects.all().delete()
                    deleted_counts[model_path] = count
                    total_deleted += count
                    self.stdout.write(
                        self.style.SUCCESS(f'  ✓ Deleted {count} records from {model_path}')
                    )
                    
            except LookupError:
                # Model doesn't exist, skip
                pass
            except Exception as e:
                self.stdout.write(
                    self.style.WARNING(f'  ⚠ Error deleting {model_path}: {str(e)}')
                )
        
        # Reset sequences
        if connection.vendor == 'postgresql':
            self.stdout.write(self.style.WARNING('\n🔄 Resetting database sequences...'))
            with connection.cursor() as cursor:
                # Get all sequences
                cursor.execute("""
                    SELECT sequence_name 
                    FROM information_schema.sequences 
                    WHERE sequence_schema = 'public';
                """)
                sequences = cursor.fetchall()
                
                for (sequence_name,) in sequences:
                    try:
                        cursor.execute(f"ALTER SEQUENCE {sequence_name} RESTART WITH 1;")
                        self.stdout.write(f'  ✓ Reset sequence: {sequence_name}')
                    except Exception as e:
                        self.stdout.write(
                            self.style.WARNING(f'  ⚠ Could not reset {sequence_name}: {str(e)}')
                        )
        elif connection.vendor == 'sqlite':
            # Re-enable foreign keys for SQLite
            with connection.cursor() as cursor:
                cursor.execute('PRAGMA foreign_keys = ON;')
        
        # Summary
        self.stdout.write(self.style.SUCCESS(f'\n✅ Data deletion complete!'))
        self.stdout.write(self.style.SUCCESS(f'Total records deleted: {total_deleted}'))
        self.stdout.write(self.style.WARNING('\n📝 Database schema preserved - all tables still exist.'))
        self.stdout.write(self.style.WARNING('You can now test with fresh data.\n'))
