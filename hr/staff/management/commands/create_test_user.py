"""
Management command to create a test user for login.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

User = get_user_model()


class Command(BaseCommand):
    help = 'Create a test user for login'

    def handle(self, *args, **options):
        # Delete existing admin if exists
        User.objects.filter(username='admin').delete()
        
        # Create new admin user
        user = User.objects.create_superuser(
            username='admin',
            email='admin@nduhr.com',
            password='admin123',
            first_name='Admin',
            last_name='User'
        )
        
        self.stdout.write(self.style.SUCCESS('\n✅ Test user created successfully!\n'))
        self.stdout.write(self.style.SUCCESS('Username: admin'))
        self.stdout.write(self.style.SUCCESS('Password: admin123'))
        self.stdout.write(self.style.WARNING('\nYou can now login at: http://127.0.0.1:8000/accounts/login/\n'))
