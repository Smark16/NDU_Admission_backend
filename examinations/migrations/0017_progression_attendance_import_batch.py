from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("examinations", "0016_alter_courseunitresult_options_and_more"),
        ("Programs", "0021_retake_missed_paper_registration"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("admissions", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="StudentProgressionStanding",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("normal", "Normal progress"), ("probation_course", "Probation (course)"), ("probation_load", "Probation (below load)"), ("discontinued_gpa", "Discontinued (GPA)"), ("discontinued_course", "Discontinued (course)")], default="normal", max_length=32)),
                ("remark", models.CharField(blank=True, default="", max_length=500)),
                ("semester_gpa", models.DecimalField(blank=True, decimal_places=2, max_digits=4, null=True)),
                ("cgpa", models.DecimalField(blank=True, decimal_places=2, max_digits=4, null=True)),
                ("computed_at", models.DateTimeField(auto_now=True)),
                ("student", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="progression_standing", to="admissions.admittedstudent")),
            ],
        ),
        migrations.CreateModel(
            name="ExamAttendance",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("present", models.BooleanField(default=False)),
                ("marked_at", models.DateTimeField(auto_now=True)),
                ("enrollment", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="exam_attendance_marks", to="Programs.studentcourseunitenrollment")),
                ("exam_session", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="attendance_marks", to="examinations.examsession")),
                ("marked_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="exam_attendance_marked", to=settings.AUTH_USER_MODEL)),
            ],
            options={"unique_together": {("exam_session", "enrollment")}},
        ),
        migrations.CreateModel(
            name="MarksImportBatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("filename", models.CharField(blank=True, default="", max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("purged_at", models.DateTimeField(blank=True, null=True)),
                ("saved_count", models.PositiveIntegerField(default=0)),
                ("course_unit", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="marks_import_batches", to="Programs.courseunit")),
                ("uploaded_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="marks_import_batches", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="MarksImportChange",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_result", models.BooleanField(default=False)),
                ("previous_ca_mark", models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ("previous_exam_mark", models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ("previous_final_mark", models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ("previous_grade_letter", models.CharField(blank=True, default="", max_length=5)),
                ("previous_grade_point", models.DecimalField(blank=True, decimal_places=1, max_digits=4, null=True)),
                ("previous_is_pass", models.BooleanField(blank=True, null=True)),
                ("previous_paper_outcome", models.CharField(blank=True, default="", max_length=16)),
                ("previous_status", models.CharField(blank=True, default="", max_length=20)),
                ("previous_edit_unlocked", models.BooleanField(default=False)),
                ("batch", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="changes", to="examinations.marksimportbatch")),
                ("result", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="import_changes", to="examinations.courseunitresult")),
            ],
        ),
    ]
