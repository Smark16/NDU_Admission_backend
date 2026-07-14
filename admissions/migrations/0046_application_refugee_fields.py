from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0045_improve_offer_letter_email_template"),
    ]

    operations = [
        migrations.AddField(
            model_name="application",
            name="is_refugee",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="application",
            name="refugee_status_proof",
            field=models.FileField(blank=True, null=True, upload_to="refugee_proofs/"),
        ),
    ]
