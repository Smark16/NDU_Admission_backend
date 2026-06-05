from django.db import migrations

class Migration(migrations.Migration):

    dependencies = [
        ('admissions', '0035_merge_20260606_0009'),
    ]

    operations = [
        migrations.RunSQL(
            """
            ALTER TABLE admissions_applicationprogramchoice
            RENAME COLUMN preference TO choice_order;
            """,
            reverse_sql="""
            ALTER TABLE admissions_applicationprogramchoice
            RENAME COLUMN choice_order TO preference;
            """
        )
    ]