from django.db import migrations, models
import django.db.models.deletion


def seed_weekly_digest(apps, schema_editor):
    EmailTemplate = apps.get_model("admissions", "EmailTemplate")
    WeeklyReportSettings = apps.get_model("admissions", "WeeklyReportSettings")

    EmailTemplate.objects.update_or_create(
        key="weekly_admissions_digest",
        defaults={
            "name": "Weekly Admissions Digest",
            "description": "Project-health style summary emailed weekly to configured staff recipients.",
            "subject_template": "NDU Admissions Weekly — {{week_start}} to {{week_end}}",
            "body_template_html": (
                "<p>Hello,</p>"
                "<p>Here is your <strong>weekly admissions health report</strong> "
                "for <strong>{{week_start}}</strong> to <strong>{{week_end}}</strong>.</p>"
                "<table cellpadding=\"8\" cellspacing=\"0\" border=\"1\" "
                "style=\"border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px;\">"
                "<tr style=\"background:#000080;color:#fff;\"><th align=\"left\">Metric</th><th align=\"right\">This week</th></tr>"
                "<tr><td>Applications received</td><td align=\"right\"><strong>{{applications_received}}</strong> ({{applications_received_delta}} vs prior week)</td></tr>"
                "<tr><td>Submitted</td><td align=\"right\">{{submitted}}</td></tr>"
                "<tr><td>Under review</td><td align=\"right\">{{under_review}}</td></tr>"
                "<tr><td>Admitted / accepted</td><td align=\"right\">{{admitted}}</td></tr>"
                "<tr><td>Rejected</td><td align=\"right\">{{rejected}}</td></tr>"
                "<tr><td>Direct entry</td><td align=\"right\">{{direct_entry}}</td></tr>"
                "<tr><td>Online</td><td align=\"right\">{{online}}</td></tr>"
                "</table>"
                "<p style=\"margin-top:16px;\"><strong>All-time pipeline (non-draft)</strong></p>"
                "<ul>"
                "<li>Total applications: {{total_pipeline}}</li>"
                "<li>Pending / in review: {{total_pending}}</li>"
                "<li>Admitted / accepted: {{total_admitted}}</li>"
                "<li>Rejected: {{total_rejected}}</li>"
                "</ul>"
                "<p><a href=\"{{report_url}}\">Open All Applicants report in Horizon</a></p>"
                "<p style=\"color:#666;font-size:12px;\">Generated {{generated_at}}</p>"
            ),
            "is_active": True,
        },
    )
    WeeklyReportSettings.objects.get_or_create(pk=1, defaults={"is_enabled": False})


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0042_admittedstudent_admitted_specialization"),
    ]

    operations = [
        migrations.CreateModel(
            name="WeeklyReportSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_enabled", models.BooleanField(default=False)),
                ("schedule_day", models.PositiveSmallIntegerField(
                    choices=[
                        (0, "Monday"),
                        (1, "Tuesday"),
                        (2, "Wednesday"),
                        (3, "Thursday"),
                        (4, "Friday"),
                        (5, "Saturday"),
                        (6, "Sunday"),
                    ],
                    default=0,
                )),
                ("schedule_hour", models.PositiveSmallIntegerField(default=8)),
                ("schedule_minute", models.PositiveSmallIntegerField(default=0)),
                ("last_sent_at", models.DateTimeField(blank=True, null=True)),
                ("last_sent_summary", models.CharField(blank=True, default="", max_length=255)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("updated_by", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="updated_weekly_report_settings",
                    to="accounts.user",
                )),
            ],
            options={
                "verbose_name": "Weekly report settings",
                "verbose_name_plural": "Weekly report settings",
            },
        ),
        migrations.CreateModel(
            name="WeeklyReportRecipient",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("email", models.EmailField(max_length=254, unique=True)),
                ("name", models.CharField(blank=True, default="", max_length=120)),
                ("is_active", models.BooleanField(default=True)),
                ("notes", models.CharField(blank=True, default="", max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="weekly_report_recipients_created",
                    to="accounts.user",
                )),
            ],
            options={
                "verbose_name": "Weekly report recipient",
                "verbose_name_plural": "Weekly report recipients",
                "ordering": ["email"],
            },
        ),
        migrations.AlterField(
            model_name="emailtemplate",
            name="key",
            field=models.CharField(
                choices=[
                    ("application_submitted", "Application Submitted"),
                    ("admission_accepted", "Admission Accepted"),
                    ("admission_updated", "Admission Updated"),
                    ("offer_letter_sent", "Offer Letter Sent"),
                    ("weekly_admissions_digest", "Weekly Admissions Digest"),
                ],
                max_length=80,
                unique=True,
            ),
        ),
        migrations.RunPython(seed_weekly_digest, migrations.RunPython.noop),
    ]
