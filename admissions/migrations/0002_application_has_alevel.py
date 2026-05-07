from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="application",
            name="has_olevel",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="application",
            name="has_alevel",
            field=models.BooleanField(default=False),
        ),
    ]

