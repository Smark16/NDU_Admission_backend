from django.db import migrations

DEFAULT_NAME = "NDEJJE UNIVERSITY STEWARD"


def seed_university_name(apps, schema_editor):
    SystemSettings = apps.get_model("accounts", "SystemSettings")
    obj, _ = SystemSettings.objects.get_or_create(pk=1)
    if not (obj.university_name or "").strip():
        obj.university_name = DEFAULT_NAME
        obj.save(update_fields=["university_name"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0038_user_role_length_and_staff_id"),
    ]

    operations = [
        migrations.RunPython(seed_university_name, migrations.RunPython.noop),
    ]
