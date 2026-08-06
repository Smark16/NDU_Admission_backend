import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0059_temporary_access_pass"),
    ]

    operations = [
        migrations.AddField(
            model_name="temporaryaccesspass",
            name="verification_token",
            field=models.UUIDField(
                db_index=True,
                default=uuid.uuid4,
                editable=False,
                help_text="Public QR verification token for the printed temporary pass card.",
                unique=True,
            ),
        ),
    ]
