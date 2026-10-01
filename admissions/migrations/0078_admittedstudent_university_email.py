# Generated manually for Zimbra university_email on AdmittedStudent

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0077_alter_admissionchangerequest_change_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="admittedstudent",
            name="university_email",
            field=models.EmailField(
                blank=True,
                default="",
                help_text="Institutional mailbox on educ.ndu.ac.ug (Zimbra), provisioned or imported.",
                max_length=254,
            ),
        ),
        migrations.AddConstraint(
            model_name="admittedstudent",
            constraint=models.UniqueConstraint(
                condition=~models.Q(university_email=""),
                fields=("university_email",),
                name="unique_admittedstudent_university_email",
            ),
        ),
    ]
