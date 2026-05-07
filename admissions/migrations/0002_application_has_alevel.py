"""
Columns `has_olevel` and `has_alevel` already exist in the database (added directly by
another developer) but were missing from the Django model. This migration:
  - Adds both fields to Django's migration state (no ADD COLUMN — avoids duplicate-column error)
  - Sets DB-level DEFAULT false on both existing columns so future inserts without the fields
    never raise a NOT NULL IntegrityError
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('admissions', '0001_initial'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name='application',
                    name='has_olevel',
                    field=models.BooleanField(default=False),
                ),
                migrations.AddField(
                    model_name='application',
                    name='has_alevel',
                    field=models.BooleanField(default=False),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql='ALTER TABLE admissions_application ALTER COLUMN has_olevel SET DEFAULT false',
                    reverse_sql='ALTER TABLE admissions_application ALTER COLUMN has_olevel DROP DEFAULT',
                ),
                migrations.RunSQL(
                    sql='ALTER TABLE admissions_application ALTER COLUMN has_alevel SET DEFAULT false',
                    reverse_sql='ALTER TABLE admissions_application ALTER COLUMN has_alevel DROP DEFAULT',
                ),
            ],
        ),
    ]
