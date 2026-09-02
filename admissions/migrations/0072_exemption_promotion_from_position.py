from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0071_exemption_deferred_effects"),
    ]

    operations = [
        migrations.AddField(
            model_name="admissionchangerequest",
            name="exemption_promotion_from_year",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="admissionchangerequest",
            name="exemption_promotion_from_term",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="admissionchangerequest",
            name="exemption_promotion_year",
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text="Target year/semester after HOD-confirmed promotion.",
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="admissionchangerequest",
            name="exemption_promotion_term",
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text="Target semester after HOD-confirmed promotion.",
                null=True,
            ),
        ),
    ]
