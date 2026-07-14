# Generated manually for expanded application field lengths (Applicant_UI / ERP hiring).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("hiring", "0002_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="jobapplication",
            name="title",
            field=models.CharField(max_length=20),
        ),
        migrations.AlterField(
            model_name="jobapplication",
            name="current_address",
            field=models.TextField(max_length=255),
        ),
        migrations.AlterField(
            model_name="jobapplication",
            name="religious_affiliation",
            field=models.CharField(max_length=100),
        ),
        migrations.AlterField(
            model_name="jobapplication",
            name="marital_status",
            field=models.CharField(max_length=50),
        ),
        migrations.AlterField(
            model_name="jobapplication",
            name="brief_description",
            field=models.TextField(max_length=2000),
        ),
        migrations.AlterField(
            model_name="jobapplication",
            name="skills",
            field=models.TextField(max_length=2000),
        ),
        migrations.AlterField(
            model_name="educationhistory",
            name="institution",
            field=models.CharField(max_length=200),
        ),
        migrations.AlterField(
            model_name="educationhistory",
            name="award",
            field=models.CharField(max_length=200),
        ),
        migrations.AlterField(
            model_name="employment",
            name="duties",
            field=models.TextField(max_length=1000),
        ),
        migrations.AlterField(
            model_name="certificates_and_training",
            name="certificate_name",
            field=models.CharField(max_length=200),
        ),
        migrations.AlterField(
            model_name="certificates_and_training",
            name="institution",
            field=models.CharField(max_length=200),
        ),
        migrations.AlterField(
            model_name="projects",
            name="name",
            field=models.CharField(max_length=100),
        ),
        migrations.AlterField(
            model_name="projects",
            name="description",
            field=models.CharField(max_length=500),
        ),
        migrations.AlterField(
            model_name="references",
            name="name",
            field=models.CharField(max_length=100),
        ),
        migrations.AlterField(
            model_name="references",
            name="phone",
            field=models.CharField(max_length=30),
        ),
        migrations.AlterField(
            model_name="references",
            name="email",
            field=models.EmailField(max_length=100),
        ),
        migrations.AlterField(
            model_name="references",
            name="job_position",
            field=models.CharField(max_length=100),
        ),
    ]
