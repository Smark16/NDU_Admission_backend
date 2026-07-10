from django.core.management.base import BaseCommand

from accounts.models import Campus
from hr.staff.models import Department, StaffProfile, StaffType


class Command(BaseCommand):
    help = "Seed minimal HR demo data (department + staff) for local ERP testing."

    def handle(self, *args, **options):
        campus, _ = Campus.objects.get_or_create(
            code="MAIN",
            defaults={"name": "Main Campus", "is_active": True},
        )

        dept, created_dept = Department.objects.get_or_create(
            code="HR",
            defaults={
                "name": "Human Resources",
                "description": "HR department (demo seed)",
            },
        )

        staff_type, _ = StaffType.objects.get_or_create(
            name="Administrative",
            defaults={"description": "Administrative staff"},
        )

        staff, created_staff = StaffProfile.objects.get_or_create(
            university_email="hr.demo@ndu.ac.ug",
            defaults={
                "first_name": "Demo",
                "last_name": "Staff",
                "job_title": "HR Officer",
                "org_unit": dept,
                "staff_type": staff_type,
                "system_login": False,
            },
        )
        if campus not in staff.campus.all():
            staff.campus.add(campus)

        verb_dept = "Created" if created_dept else "Found"
        verb_staff = "Created" if created_staff else "Found"
        self.stdout.write(self.style.SUCCESS(f"{verb_dept} department: {dept.name}"))
        self.stdout.write(self.style.SUCCESS(f"{verb_staff} staff: {staff.get_full_name} ({staff.staff_no})"))
        self.stdout.write("Refresh HR pages in the ERP to see demo data.")
