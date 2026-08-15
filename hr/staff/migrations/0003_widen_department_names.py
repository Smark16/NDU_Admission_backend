from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("staff", "0002_payscale"),
    ]

    operations = [
        migrations.AlterField(
            model_name="department",
            name="name",
            field=models.CharField(max_length=200, unique=True),
        ),
        migrations.AlterField(
            model_name="department",
            name="code",
            field=models.CharField(max_length=40, unique=True),
        ),
        migrations.AlterField(
            model_name="department",
            name="description",
            field=models.TextField(blank=True, max_length=500, null=True),
        ),
        migrations.AlterField(
            model_name="departmentteams",
            name="team_name",
            field=models.CharField(max_length=120),
        ),
        migrations.AlterField(
            model_name="departmentteams",
            name="description",
            field=models.TextField(blank=True, max_length=500, null=True),
        ),
        migrations.AlterModelOptions(
            name="department",
            options={"ordering": ["name"]},
        ),
    ]
