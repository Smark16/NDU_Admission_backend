from django.db import migrations


def forwards(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    def get_perm(app_label: str, codename: str):
        return Permission.objects.filter(
            content_type__app_label=app_label,
            codename=codename,
        ).first()

    matrix = {
        "Admissions Approver": [
            ("admissions", "approve_application"),
            ("admissions", "reject_application"),
            ("admissions", "admit_applicant"),
            ("admissions", "manage_admission_change_requests"),
        ],
        "Admissions Reviewer": [
            ("admissions", "approve_application"),
            ("admissions", "reject_application"),
        ],
        "Direct Admission Officer": [
            ("admissions", "approve_application"),
            ("admissions", "reject_application"),
            ("admissions", "admit_applicant"),
        ],
    }

    for group_name, pairs in matrix.items():
        group = Group.objects.filter(name=group_name).first()
        if not group:
            continue
        for app_label, codename in pairs:
            p = get_perm(app_label, codename)
            if p:
                group.permissions.add(p)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0016_application_workflow_permissions"),
    ]

    operations = [
        migrations.RunPython(forwards, noop_reverse),
    ]
