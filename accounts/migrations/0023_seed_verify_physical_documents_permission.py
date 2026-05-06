from django.db import migrations


def grant_verify_physical_documents(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    ct = ContentType.objects.get(app_label="admissions", model="admittedstudent")
    perm = Permission.objects.filter(
        content_type=ct, codename="verify_physical_documents"
    ).first()
    if not perm:
        return

    group_names = (
        "ERP System Administrator",
        "Academic Registrar",
        "Admissions Officer",
        "Registry / Academic Officer",
    )
    for name in group_names:
        group = Group.objects.filter(name=name).first()
        if group:
            group.permissions.add(perm)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0054_physical_document_verification"),
        ("accounts", "0022_alter_erpaccesspolicy_options_alter_profile_phone_and_more"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(grant_verify_physical_documents, noop_reverse),
    ]
