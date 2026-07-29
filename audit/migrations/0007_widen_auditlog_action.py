# Generated manually — widen AuditLog.action for finance / bank payment events

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("audit", "0006_alter_auditlog_action"),
    ]

    operations = [
        migrations.AlterField(
            model_name="auditlog",
            name="action",
            field=models.CharField(max_length=64),
        ),
    ]
