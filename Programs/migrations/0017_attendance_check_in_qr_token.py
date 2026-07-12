from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("Programs", "0016_attendance_check_in_window"),
    ]

    operations = [
        migrations.AddField(
            model_name="lectureattendancesession",
            name="check_in_token",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Rotating token encoded in the lecturer QR for student scan check-in.",
                max_length=64,
            ),
        ),
        migrations.AddField(
            model_name="lectureattendancesession",
            name="check_in_token_issued_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When the current check_in_token was issued (rotated periodically).",
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="lectureattendancerecord",
            name="marked_via",
            field=models.CharField(
                blank=True,
                choices=[
                    ("lecturer", "Lecturer"),
                    ("student", "Student self-check-in"),
                    ("admin", "Faculty / admin"),
                    ("paper", "Paper register"),
                    ("qr", "QR scan"),
                ],
                default="lecturer",
                max_length=20,
            ),
        ),
    ]
