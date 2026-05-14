# Generated manually for IdCardPdfTemplate

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0020_admittedstudent_physical_documents_verified"),
    ]

    operations = [
        migrations.CreateModel(
            name="IdCardPdfTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "key",
                    models.SlugField(
                        db_index=True,
                        help_text="Stable key; must match SystemSettings.active_id_card_template when this layout is active.",
                        max_length=80,
                        unique=True,
                    ),
                ),
                ("name", models.CharField(max_length=120)),
                (
                    "template_pdf",
                    models.FileField(
                        help_text="PDF artwork (e.g. card front)",
                        upload_to="id_card_templates/",
                    ),
                ),
                ("field_positions", models.JSONField(blank=True, default=dict)),
                ("front_title", models.CharField(blank=True, default="", max_length=200)),
                ("institution", models.CharField(blank=True, default="", max_length=200)),
                ("issuer_title", models.CharField(blank=True, default="", max_length=120)),
                ("issuer_signatory", models.CharField(blank=True, default="", max_length=120)),
                ("return_to", models.TextField(blank=True, default="")),
                ("tel", models.CharField(blank=True, default="", max_length=80)),
                ("email", models.EmailField(blank=True, default="", max_length=254)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "ID card PDF template",
                "verbose_name_plural": "ID card PDF templates",
                "ordering": ["name"],
            },
        ),
    ]
