from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0016_merge_20260420_1747'),
    ]

    operations = [
        migrations.CreateModel(
            name='SystemSettings',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('student_session_timeout', models.PositiveIntegerField(default=30, help_text='Minutes before a student session expires due to inactivity')),
                ('admin_session_timeout', models.PositiveIntegerField(default=60, help_text='Minutes before an admin session expires due to inactivity')),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='settings_updates', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'System Settings',
            },
        ),
    ]
