from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("Drafts", "0023_draft_other_documents"),
    ]

    operations = [
        migrations.AddField(
            model_name="draftapplication",
            name="is_refugee",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="draftapplication",
            name="refugee_status_proof",
            field=models.FileField(
                blank=True,
                null=True,
                upload_to="draft_documents/refugee/",
            ),
        ),
    ]
