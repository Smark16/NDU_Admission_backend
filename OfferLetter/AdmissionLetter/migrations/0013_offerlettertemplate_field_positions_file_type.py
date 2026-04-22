from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('AdmissionLetter', '0012_offerlettertemplate_hall_of_residence_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='offerlettertemplate',
            name='file_type',
            field=models.CharField(default='docx', max_length=10),
        ),
        migrations.AddField(
            model_name='offerlettertemplate',
            name='field_positions',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
