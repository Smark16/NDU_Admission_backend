from django.db import migrations, models


def clear_blank_staff_ids(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(staff_id="").update(staff_id=None)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0037_seed_super_admin_role"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.RunPython(clear_blank_staff_ids, migrations.RunPython.noop),
    ]
