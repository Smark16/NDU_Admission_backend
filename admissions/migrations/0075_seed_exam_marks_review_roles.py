from django.db import migrations


def sync_roles(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    from admissions.hod_role_setup import seed_hod_role
    from admissions.faculty_dean_role_setup import seed_faculty_dean_role
    from admissions.exam_coordinator_role_setup import seed_exam_coordinator_role

    # Reseed HOD/Dean (permission set changed: HOD no longer publishes
    # directly, Dean gained the review/publish stage) and seed the new
    # Exam Coordinator group.
    seed_hod_role(Group, Permission)
    seed_faculty_dean_role(Group, Permission)
    seed_exam_coordinator_role(Group, Permission)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0074_academicdepartment_exam_coordinator"),
        ("examinations", "0016_alter_courseunitresult_options_and_more"),
    ]

    operations = [
        migrations.RunPython(sync_roles, noop_reverse),
    ]
