"""
Management command to verify system implementation against documentation.
Checks for required apps, models, URLs, templates, and commands.
"""
from django.core.management.base import BaseCommand
from django.conf import settings
from django.apps import apps
import os
import sys


class Command(BaseCommand):
    help = 'Verify HRMS implementation against documentation requirements'

    def __init__(self):
        super().__init__()
        self.errors = []
        self.warnings = []
        self.checks_passed = 0
        self.checks_total = 0

    def handle(self, *args, **options):
        self.stdout.write('='*70)
        self.stdout.write(self.style.HTTP_INFO('NDEJJE HRMS Implementation Verification'))
        self.stdout.write('='*70 + '\n')

        # Run all verification checks
        self.check_installed_apps()
        self.check_models()
        self.check_model_fields()
        self.check_urls()
        self.check_templates()
        self.check_management_commands()
        self.check_permission_helpers()
        
        # Display summary
        self.display_summary()
        
        # Exit with appropriate code
        if self.errors:
            sys.exit(1)
        sys.exit(0)

    def verify_check(self, description, condition, critical=True):
        """Helper to check a condition and track results."""
        self.checks_total += 1
        if condition:
            self.checks_passed += 1
            self.stdout.write(f'  {self.style.SUCCESS("✓")} {description}')
            return True
        else:
            if critical:
                self.errors.append(description)
                self.stdout.write(f'  {self.style.ERROR("✗")} {description}')
            else:
                self.warnings.append(description)
                self.stdout.write(f'  {self.style.WARNING("⚠")} {description}')
            return False

    def check_installed_apps(self):
        """Verify all required Django apps are installed."""
        self.stdout.write(self.style.HTTP_INFO('\n1. Checking Installed Apps'))
        self.stdout.write('-'*70)
        
        required_apps = [
            'accounts',
            'apps.tenancy',
            'apps.common',
            'hr.staff',
        ]
        
        installed = settings.INSTALLED_APPS
        for app in required_apps:
            self.verify_check(f'App installed: {app}', app in installed)

    def check_models(self):
        """Verify all required models exist."""
        self.stdout.write(self.style.HTTP_INFO('\n2. Checking Models'))
        self.stdout.write('-'*70)
        
        models_to_check = [
            ('accounts', 'CustomUser'),
            ('tenancy', 'Campus'),
            ('staff', 'OrgUnit'),
            ('staff', 'JobTitle'),
            ('staff', 'StaffProfile'),
        ]
        
        for app_label, model_name in models_to_check:
            try:
                model = apps.get_model(app_label, model_name)
                self.verify_check(f'Model exists: {app_label}.{model_name}', True)
            except LookupError:
                self.verify_check(f'Model exists: {app_label}.{model_name}', False)

    def check_model_fields(self):
        """Verify critical model fields exist."""
        self.stdout.write(self.style.HTTP_INFO('\n3. Checking Model Fields'))
        self.stdout.write('-'*70)
        
        try:
            # CustomUser fields
            CustomUser = apps.get_model('accounts', 'CustomUser')
            self.verify_check('CustomUser has user_type field', 
                      hasattr(CustomUser, 'user_type'))
            self.verify_check('CustomUser has campus field', 
                      hasattr(CustomUser, 'campus'))
            
            # Campus fields
            Campus = apps.get_model('tenancy', 'Campus')
            self.verify_check('Campus has code field', 
                      hasattr(Campus, 'code'))
            self.verify_check('Campus has name field', 
                      hasattr(Campus, 'name'))
            self.verify_check('Campus has is_active field', 
                      hasattr(Campus, 'is_active'))
            
            # OrgUnit fields
            OrgUnit = apps.get_model('staff', 'OrgUnit')
            self.verify_check('OrgUnit has campus field', 
                      hasattr(OrgUnit, 'campus'))
            self.verify_check('OrgUnit has parent field', 
                      hasattr(OrgUnit, 'parent'))
            self.verify_check('OrgUnit has unit_type field', 
                      hasattr(OrgUnit, 'unit_type'))
            self.verify_check('OrgUnit has get_all_descendants method', 
                      hasattr(OrgUnit, 'get_all_descendants'), critical=False)
            
            # StaffProfile fields
            StaffProfile = apps.get_model('staff', 'StaffProfile')
            required_fields = [
                'user', 'campus', 'org_unit', 'job_title', 'staff_no',
                'full_name', 'nssf_no', 'tin_no', 'university_email',
                'personal_email', 'designation_text', 'date_joined',
                'is_active', 'is_manager', 'managed_org_unit'
            ]
            for field in required_fields:
                self.verify_check(f'StaffProfile has {field} field', 
                          hasattr(StaffProfile, field))
            
        except LookupError as e:
            self.verify_check(f'Model lookup failed: {e}', False)

    def check_urls(self):
        """Verify required URL patterns exist."""
        self.stdout.write(self.style.HTTP_INFO('\n4. Checking URL Patterns'))
        self.stdout.write('-'*70)
        
        from django.urls import reverse, NoReverseMatch
        import uuid
        
        # Test URLs that don't require arguments
        simple_urls = [
            ('accounts:login', 'Login URL'),
            ('accounts:logout', 'Logout URL'),
            ('staff:staff_list', 'Staff list URL'),
            ('staff:staff_create', 'Staff create URL'),
            ('staff:my_profile', 'My profile URL'),
            ('staff:upload_csv', 'CSV upload URL'),
        ]
        
        for url_name, description in simple_urls:
            try:
                reverse(url_name)
                self.verify_check(f'{description}: {url_name}', True)
            except NoReverseMatch:
                self.verify_check(f'{description}: {url_name}', False)
        
        # Test URLs that require UUID argument
        uuid_urls = [
            ('staff:staff_detail', 'Staff detail URL'),
            ('staff:staff_update', 'Staff update URL'),
            ('staff:create_account', 'Create account URL'),
        ]
        
        test_uuid = uuid.uuid4()
        for url_name, description in uuid_urls:
            try:
                reverse(url_name, kwargs={'pk': test_uuid})
                self.verify_check(f'{description}: {url_name}', True)
            except NoReverseMatch:
                self.verify_check(f'{description}: {url_name}', False)

    def check_templates(self):
        """Verify required templates exist."""
        self.stdout.write(self.style.HTTP_INFO('\n5. Checking Templates'))
        self.stdout.write('-'*70)
        
        from django.template.loader import get_template
        from django.template import TemplateDoesNotExist
        
        required_templates = [
            'base.html',
            'registration/login.html',
            'staff/staff_list.html',
            'staff/staff_detail.html',
            'staff/staff_form.html',
            'staff/my_profile.html',
            'staff/upload_csv.html',
            'staff/create_user_account.html',
        ]
        
        for template_name in required_templates:
            try:
                get_template(template_name)
                self.verify_check(f'Template exists: {template_name}', True)
            except TemplateDoesNotExist:
                self.verify_check(f'Template exists: {template_name}', False)

    def check_management_commands(self):
        """Verify required management commands exist."""
        self.stdout.write(self.style.HTTP_INFO('\n6. Checking Management Commands'))
        self.stdout.write('-'*70)
        
        from django.core.management import get_commands
        
        commands = get_commands()
        required_commands = [
            'seed_demo',
            'import_staff_csv',
            'demo_hierarchy',
            'verify_implementation',
        ]
        
        for cmd in required_commands:
            self.verify_check(f'Command exists: {cmd}', cmd in commands)

    def check_permission_helpers(self):
        """Verify permission helper functions exist."""
        self.stdout.write(self.style.HTTP_INFO('\n7. Checking Permission Helpers'))
        self.stdout.write('-'*70)
        
        try:
            from hr.staff import views
            
            self.verify_check('is_hr_admin function exists', 
                      hasattr(views, 'is_hr_admin'))
            self.verify_check('is_manager function exists', 
                      hasattr(views, 'is_manager'))
            self.verify_check('get_managed_org_units function exists', 
                      hasattr(views, 'get_managed_org_units'))
            self.verify_check('HRAdminRequiredMixin class exists', 
                      hasattr(views, 'HRAdminRequiredMixin'))
            
        except ImportError as e:
            self.verify_check(f'Import views module: {e}', False)

    def display_summary(self):
        """Display verification summary."""
        self.stdout.write('\n' + '='*70)
        self.stdout.write(self.style.HTTP_INFO('Verification Summary'))
        self.stdout.write('='*70 + '\n')
        
        # Calculate pass rate
        pass_rate = (self.checks_passed / self.checks_total * 100) if self.checks_total > 0 else 0
        
        self.stdout.write(f'Total Checks: {self.checks_total}')
        self.stdout.write(self.style.SUCCESS(f'Passed: {self.checks_passed}'))
        
        if self.warnings:
            self.stdout.write(self.style.WARNING(f'Warnings: {len(self.warnings)}'))
        
        if self.errors:
            self.stdout.write(self.style.ERROR(f'Failed: {len(self.errors)}'))
        
        self.stdout.write(f'Pass Rate: {pass_rate:.1f}%\n')
        
        # Display errors if any
        if self.errors:
            self.stdout.write(self.style.ERROR('\nCritical Issues:'))
            for error in self.errors:
                self.stdout.write(f'  • {error}')
        
        # Display warnings if any
        if self.warnings:
            self.stdout.write(self.style.WARNING('\nWarnings:'))
            for warning in self.warnings:
                self.stdout.write(f'  • {warning}')
        
        # Final status
        self.stdout.write('\n' + '='*70)
        if self.errors:
            self.stdout.write(self.style.ERROR('❌ VERIFICATION FAILED'))
            self.stdout.write(self.style.ERROR(f'   {len(self.errors)} critical issue(s) found'))
        else:
            self.stdout.write(self.style.SUCCESS('✅ VERIFICATION PASSED'))
            self.stdout.write('   All critical checks passed successfully')
        self.stdout.write('='*70 + '\n')
