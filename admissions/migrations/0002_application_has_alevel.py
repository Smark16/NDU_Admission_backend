"""
Column `has_alevel` already exists in the database (added directly by another developer)
but was missing from the Django model. This migration:
  - Adds the field to Django's migration state (no ADD COLUMN — avoids duplicate column error)
  - Sets a DB-level DEFAULT false on the existing column so future inserts without the field
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
                    name='has_alevel',
                    field=models.BooleanField(default=False),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql='ALTER TABLE admissions_application ALTER COLUMN has_alevel SET DEFAULT false',
                    reverse_sql='ALTER TABLE admissions_application ALTER COLUMN has_alevel DROP DEFAULT',
                ),
            ],
        ),
    ]
