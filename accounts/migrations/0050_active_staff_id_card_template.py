from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0049_verify_student_cards_permission"),
    ]

    operations = [
        migrations.AddField(
            model_name="systemsettings",
            name="active_staff_id_card_template",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Active PDF template key for staff ID cards.",
                max_length=80,
            ),
        ),
    ]
