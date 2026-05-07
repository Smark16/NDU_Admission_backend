from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('admissions', '0002_application_has_alevel'),
    ]

    operations = [
        migrations.AddField(
            model_name='application',
            name='school_pay_reference',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]
