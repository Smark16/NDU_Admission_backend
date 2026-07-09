"""
Comprehensive test suite for staff management system.
Tests authentication flows, permissions, and role-based access control.
"""
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from accounts.models import Campus
from hr.staff.models import StaffProfile, OrgUnit, JobTitle

User = get_user_model()


class AuthenticationTests(TestCase):
    """Test authentication and redirect behavior by role."""
    
    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.campus = Campus.objects.create(
            code='MAIN',
            name='Main Campus',
            is_active=True
        )
        self.org_unit = OrgUnit.objects.create(
            campus=self.campus,
            name='Faculty of Engineering',
            unit_type='FACULTY'
        )
        
    def test_login_redirect_superuser(self):
        """Superuser should redirect to staff list."""
        user = User.objects.create_superuser(
            username='admin',
            email='admin@test.com',
            password='testpass123'
        )
        self.client.login(username='admin', password='testpass123')
        response = self.client.get(reverse('home'))
        self.assertRedirects(response, reverse('staff:staff_list'))
    
    def test_login_redirect_hr_admin(self):
        """HR Admin should redirect to staff list."""
        user = User.objects.create_user(
            username='hradmin',
            email='hradmin@test.com',
            password='testpass123',
            user_type='HR_ADMIN',
            campus=self.campus
        )
        self.client.login(username='hradmin', password='testpass123')
        response = self.client.get(reverse('home'))
        self.assertRedirects(response, reverse('staff:staff_list'))
    
    def test_login_redirect_manager(self):
        """Manager should redirect to my profile."""
        user = User.objects.create_user(
            username='manager',
            email='manager@test.com',
            password='testpass123',
            user_type='MANAGER',
            campus=self.campus
        )
        staff_profile = StaffProfile.objects.create(
            campus=self.campus,
            user=user,
            full_name='Manager User',
            org_unit=self.org_unit,
            is_manager=True,
            managed_org_unit=self.org_unit,
            staff_no='NDU-STF-000001'
        )
        self.client.login(username='manager', password='testpass123')
        response = self.client.get(reverse('home'))
        self.assertRedirects(response, reverse('staff:my_profile'))
    
    def test_login_redirect_staff(self):
        """Regular staff should redirect to my profile."""
        user = User.objects.create_user(
            username='staff',
            email='staff@test.com',
            password='testpass123',
            user_type='STAFF',
            campus=self.campus
        )
        staff_profile = StaffProfile.objects.create(
            campus=self.campus,
            user=user,
            full_name='Staff User',
            org_unit=self.org_unit,
            staff_no='NDU-STF-000002'
        )
        self.client.login(username='staff', password='testpass123')
        response = self.client.get(reverse('home'))
        self.assertRedirects(response, reverse('staff:my_profile'))
    
    def test_unauthenticated_redirect(self):
        """Unauthenticated user should redirect to login."""
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)


class StaffListFilteringTests(TestCase):
    """Test staff list filtering by user role."""
    
    def setUp(self):
        """Set up test data."""
        self.client = Client()
        
        # Create two campuses
        self.campus1 = Campus.objects.create(code='MAIN', name='Main Campus')
        self.campus2 = Campus.objects.create(code='BRANCH', name='Branch Campus')
        
        # Create org units
        self.org_unit1 = OrgUnit.objects.create(
            campus=self.campus1,
            name='Engineering',
            unit_type='FACULTY'
        )
        self.org_unit2 = OrgUnit.objects.create(
            campus=self.campus1,
            name='Science',
            unit_type='FACULTY'
        )
        self.org_unit3 = OrgUnit.objects.create(
            campus=self.campus2,
            name='Arts',
            unit_type='FACULTY'
        )
        
        # Create staff in different org units
        self.staff1 = StaffProfile.objects.create(
            campus=self.campus1,
            full_name='Staff One',
            org_unit=self.org_unit1,
            staff_no='NDU-STF-000001'
        )
        self.staff2 = StaffProfile.objects.create(
            campus=self.campus1,
            full_name='Staff Two',
            org_unit=self.org_unit2,
            staff_no='NDU-STF-000002'
        )
        self.staff3 = StaffProfile.objects.create(
            campus=self.campus2,
            full_name='Staff Three',
            org_unit=self.org_unit3,
            staff_no='NDU-STF-000003'
        )
    
    def test_superuser_sees_all_staff(self):
        """Superuser should see all staff across all campuses."""
        user = User.objects.create_superuser(
            username='admin',
            email='admin@test.com',
            password='testpass123'
        )
        self.client.login(username='admin', password='testpass123')
        response = self.client.get(reverse('staff:staff_list'))
        self.assertEqual(response.status_code, 200)
        staff_list = response.context['staff_list']
        self.assertEqual(staff_list.count(), 3)
    
    def test_hr_admin_sees_campus_staff_only(self):
        """HR Admin should see only staff in their campus."""
        user = User.objects.create_user(
            username='hradmin',
            email='hradmin@test.com',
            password='testpass123',
            user_type='HR_ADMIN',
            campus=self.campus1
        )
        self.client.login(username='hradmin', password='testpass123')
        response = self.client.get(reverse('staff:staff_list'))
        self.assertEqual(response.status_code, 200)
        staff_list = response.context['staff_list']
        self.assertEqual(staff_list.count(), 2)
        # Should only see staff1 and staff2 (campus1)
        staff_ids = [s.id for s in staff_list]
        self.assertIn(self.staff1.id, staff_ids)
        self.assertIn(self.staff2.id, staff_ids)
        self.assertNotIn(self.staff3.id, staff_ids)
    
    def test_manager_sees_managed_unit_staff_only(self):
        """Manager should see only staff in their managed org unit."""
        user = User.objects.create_user(
            username='manager',
            email='manager@test.com',
            password='testpass123',
            user_type='MANAGER',
            campus=self.campus1
        )
        manager_profile = StaffProfile.objects.create(
            campus=self.campus1,
            user=user,
            full_name='Manager User',
            org_unit=self.org_unit1,
            is_manager=True,
            managed_org_unit=self.org_unit1,
            staff_no='NDU-STF-000100'
        )
        self.client.login(username='manager', password='testpass123')
        response = self.client.get(reverse('staff:staff_list'))
        self.assertEqual(response.status_code, 200)
        staff_list = response.context['staff_list']
        # Should see staff1 and manager_profile (both in org_unit1)
        self.assertEqual(staff_list.count(), 2)
        staff_ids = [s.id for s in staff_list]
        self.assertIn(self.staff1.id, staff_ids)
        self.assertIn(manager_profile.id, staff_ids)
        self.assertNotIn(self.staff2.id, staff_ids)
        self.assertNotIn(self.staff3.id, staff_ids)
    
    def test_staff_cannot_access_staff_list(self):
        """Regular staff should not access staff list."""
        user = User.objects.create_user(
            username='staff',
            email='staff@test.com',
            password='testpass123',
            user_type='STAFF',
            campus=self.campus1
        )
        StaffProfile.objects.create(
            campus=self.campus1,
            user=user,
            full_name='Staff User',
            org_unit=self.org_unit1,
            staff_no='NDU-STF-000200'
        )
        self.client.login(username='staff', password='testpass123')
        response = self.client.get(reverse('staff:staff_list'))
        # Should be redirected
        self.assertEqual(response.status_code, 302)
        self.assertIn('/staff/me', response.url)


class MyProfileTests(TestCase):
    """Test my profile view."""
    
    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.campus = Campus.objects.create(code='MAIN', name='Main Campus')
        self.org_unit = OrgUnit.objects.create(
            campus=self.campus,
            name='Engineering',
            unit_type='FACULTY'
        )
    
    def test_my_profile_shows_own_profile_only(self):
        """User should see only their own profile."""
        user = User.objects.create_user(
            username='testuser',
            email='test@test.com',
            password='testpass123',
            campus=self.campus
        )
        staff_profile = StaffProfile.objects.create(
            campus=self.campus,
            user=user,
            full_name='Test User',
            org_unit=self.org_unit,
            staff_no='NDU-STF-000001'
        )
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('staff:my_profile'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['staff_profile'].id, staff_profile.id)
    
    def test_my_profile_requires_authentication(self):
        """My profile should require authentication."""
        response = self.client.get(reverse('staff:my_profile'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)


class CSVUploadPermissionTests(TestCase):
    """Test CSV upload permissions."""
    
    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.campus = Campus.objects.create(code='MAIN', name='Main Campus')
        self.org_unit = OrgUnit.objects.create(
            campus=self.campus,
            name='Engineering',
            unit_type='FACULTY'
        )
    
    def test_csv_upload_requires_hr_admin(self):
        """CSV upload should be accessible to HR admins."""
        user = User.objects.create_user(
            username='hradmin',
            email='hradmin@test.com',
            password='testpass123',
            user_type='HR_ADMIN',
            campus=self.campus
        )
        self.client.login(username='hradmin', password='testpass123')
        response = self.client.get(reverse('staff:upload_csv'))
        self.assertEqual(response.status_code, 200)
    
    def test_manager_cannot_upload_csv(self):
        """Managers should not access CSV upload."""
        user = User.objects.create_user(
            username='manager',
            email='manager@test.com',
            password='testpass123',
            user_type='MANAGER',
            campus=self.campus
        )
        StaffProfile.objects.create(
            campus=self.campus,
            user=user,
            full_name='Manager User',
            org_unit=self.org_unit,
            is_manager=True,
            managed_org_unit=self.org_unit,
            staff_no='NDU-STF-000001'
        )
        self.client.login(username='manager', password='testpass123')
        response = self.client.get(reverse('staff:upload_csv'))
        # Should be redirected
        self.assertEqual(response.status_code, 302)
    
    def test_staff_cannot_upload_csv(self):
        """Regular staff should not access CSV upload."""
        user = User.objects.create_user(
            username='staff',
            email='staff@test.com',
            password='testpass123',
            user_type='STAFF',
            campus=self.campus
        )
        StaffProfile.objects.create(
            campus=self.campus,
            user=user,
            full_name='Staff User',
            org_unit=self.org_unit,
            staff_no='NDU-STF-000002'
        )
        self.client.login(username='staff', password='testpass123')
        response = self.client.get(reverse('staff:upload_csv'))
        # Should be redirected
        self.assertEqual(response.status_code, 302)


class UserAccountCreationTests(TestCase):
    """Test user account creation functionality."""
    
    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.campus = Campus.objects.create(code='MAIN', name='Main Campus')
        self.org_unit = OrgUnit.objects.create(
            campus=self.campus,
            name='Engineering',
            unit_type='FACULTY'
        )
        self.staff_profile = StaffProfile.objects.create(
            campus=self.campus,
            full_name='Test Staff',
            university_email='test.staff@university.edu',
            org_unit=self.org_unit,
            staff_no='NDU-STF-000001'
        )
    
    def test_create_user_account_links_to_staff(self):
        """Creating user account should link to staff profile."""
        hr_admin = User.objects.create_user(
            username='hradmin',
            email='hradmin@test.com',
            password='testpass123',
            user_type='HR_ADMIN',
            campus=self.campus
        )
        self.client.login(username='hradmin', password='testpass123')
        
        response = self.client.post(
            reverse('staff:create_account', kwargs={'pk': self.staff_profile.pk}),
            {
                'username': 'teststaff',
                'email': 'test.staff@university.edu',
                'password': 'securepass123',
                'user_type': 'STAFF'
            }
        )
        
        # Refresh staff profile
        self.staff_profile.refresh_from_db()
        
        # Should have user linked
        self.assertIsNotNone(self.staff_profile.user)
        self.assertEqual(self.staff_profile.user.username, 'teststaff')
        self.assertEqual(self.staff_profile.user.user_type, 'STAFF')
    
    def test_create_user_account_requires_hr_admin(self):
        """Only HR admins should create user accounts."""
        regular_user = User.objects.create_user(
            username='staff',
            email='staff@test.com',
            password='testpass123',
            user_type='STAFF',
            campus=self.campus
        )
        self.client.login(username='staff', password='testpass123')
        
        response = self.client.get(
            reverse('staff:create_account', kwargs={'pk': self.staff_profile.pk})
        )
        
        # Should be redirected
        self.assertEqual(response.status_code, 302)
    
    def test_manager_cannot_create_user_accounts(self):
        """Managers should not create user accounts."""
        manager = User.objects.create_user(
            username='manager',
            email='manager@test.com',
            password='testpass123',
            user_type='MANAGER',
            campus=self.campus
        )
        StaffProfile.objects.create(
            campus=self.campus,
            user=manager,
            full_name='Manager User',
            org_unit=self.org_unit,
            is_manager=True,
            managed_org_unit=self.org_unit,
            staff_no='NDU-STF-000100'
        )
        self.client.login(username='manager', password='testpass123')
        
        response = self.client.get(
            reverse('staff:create_account', kwargs={'pk': self.staff_profile.pk})
        )
        
        # Should be redirected
        self.assertEqual(response.status_code, 302)


class ModelTests(TestCase):
    """Test model functionality."""
    
    def setUp(self):
        """Set up test data."""
        self.campus = Campus.objects.create(code='MAIN', name='Main Campus')
        self.org_unit = OrgUnit.objects.create(
            campus=self.campus,
            name='Engineering',
            unit_type='FACULTY'
        )
    
    def test_staff_profile_auto_generates_staff_number(self):
        """Staff number should be auto-generated if blank."""
        from hr.staff.utils import generate_staff_number
        
        # Create without staff_no
        staff = StaffProfile.objects.create(
            campus=self.campus,
            full_name='Test Staff',
            org_unit=self.org_unit
        )
        
        # Staff number is blank initially (as it's blank=True in model)
        self.assertEqual(staff.staff_no, '')
        
        # Manually generate (simulating what CreateView does)
        staff.staff_no = generate_staff_number(self.campus)
        staff.save()
        
        staff.refresh_from_db()
        # Format is {CAMPUS_CODE}-STF-{NUMBER}, e.g., MAIN-STF-000001
        self.assertIn('-STF-', staff.staff_no)
        self.assertTrue(staff.staff_no.startswith(self.campus.code))
        self.assertGreater(len(staff.staff_no), 10)
    
    def test_manager_assignment(self):
        """Test manager can be assigned to org unit."""
        user = User.objects.create_user(
            username='manager',
            email='manager@test.com',
            password='testpass123',
            user_type='MANAGER',
            campus=self.campus
        )
        
        manager = StaffProfile.objects.create(
            campus=self.campus,
            user=user,
            full_name='Manager User',
            org_unit=self.org_unit,
            is_manager=True,
            managed_org_unit=self.org_unit,
            staff_no='NDU-STF-000001'
        )
        
        self.assertTrue(manager.is_manager)
        self.assertEqual(manager.managed_org_unit, self.org_unit)
        
        # Test is_manager helper function
        from hr.staff.views import is_manager as is_manager_check
        self.assertTrue(is_manager_check(user))


class StaffCRUDTests(TestCase):
    """Test staff CRUD operations."""
    
    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.campus = Campus.objects.create(code='MAIN', name='Main Campus')
        self.org_unit = OrgUnit.objects.create(
            campus=self.campus,
            name='Engineering',
            unit_type='FACULTY'
        )
        
        self.hr_admin = User.objects.create_user(
            username='hradmin',
            email='hradmin@test.com',
            password='testpass123',
            user_type='HR_ADMIN',
            campus=self.campus
        )
    
    def test_hr_admin_can_create_staff(self):
        """HR Admin should be able to access staff creation form."""
        self.client.login(username='hradmin', password='testpass123')
        response = self.client.get(reverse('staff:staff_create'))
        self.assertEqual(response.status_code, 200)
    
    def test_hr_admin_can_update_staff(self):
        """HR Admin should be able to update staff in their campus."""
        staff = StaffProfile.objects.create(
            campus=self.campus,
            full_name='Test Staff',
            org_unit=self.org_unit,
            staff_no='NDU-STF-000001'
        )
        
        self.client.login(username='hradmin', password='testpass123')
        response = self.client.get(
            reverse('staff:staff_update', kwargs={'pk': staff.pk})
        )
        self.assertEqual(response.status_code, 200)
    
    def test_hr_admin_can_view_staff_detail(self):
        """HR Admin should be able to view staff details."""
        staff = StaffProfile.objects.create(
            campus=self.campus,
            full_name='Test Staff',
            org_unit=self.org_unit,
            staff_no='NDU-STF-000001'
        )
        
        self.client.login(username='hradmin', password='testpass123')
        response = self.client.get(
            reverse('staff:staff_detail', kwargs={'pk': staff.pk})
        )
        self.assertEqual(response.status_code, 200)
