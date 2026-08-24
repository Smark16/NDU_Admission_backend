# Allow same catalog course on multiple subject combinations (tracks)
# at the same year/term. Unique key now includes specialization.

from django.db import migrations, models


def normalize_null_specialization(apps, schema_editor):
    Line = apps.get_model("Programs", "ProgramCurriculumLine")
    Line.objects.filter(specialization__isnull=True).update(specialization="")


# Prod may never have had name unique_curriculum_slot (or it was renamed).
# Drop by name IF EXISTS, and also any unique constraint on the old 4 columns.
_DROP_OLD_UNIQUE_PG = """
DO $$
DECLARE
  r RECORD;
BEGIN
  ALTER TABLE "Programs_programcurriculumline"
    DROP CONSTRAINT IF EXISTS unique_curriculum_slot;

  FOR r IN
    SELECT con.conname
    FROM pg_constraint con
    JOIN pg_class rel ON rel.oid = con.conrelid
    WHERE rel.relname = 'Programs_programcurriculumline'
      AND con.contype = 'u'
      AND (
        SELECT array_agg(att.attname::text ORDER BY u.ord)
        FROM unnest(con.conkey) WITH ORDINALITY AS u(attnum, ord)
        JOIN pg_attribute att
          ON att.attrelid = con.conrelid AND att.attnum = u.attnum
      ) = ARRAY[
        'curriculum_version_id',
        'catalog_course_id',
        'year_of_study',
        'term_number'
      ]
  LOOP
    EXECUTE format(
      'ALTER TABLE "Programs_programcurriculumline" DROP CONSTRAINT %I',
      r.conname
    );
  END LOOP;
END $$;
"""


def drop_old_unique_curriculum_slot(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor == "postgresql":
        schema_editor.execute(_DROP_OLD_UNIQUE_PG)
        return
    if vendor == "sqlite":
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type IN ('index', 'table') AND name='unique_curriculum_slot'"
            )
            if cursor.fetchone():
                schema_editor.execute('DROP INDEX IF EXISTS "unique_curriculum_slot"')


def restore_old_unique_curriculum_slot(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor == "postgresql":
        schema_editor.execute(_RESTORE_OLD_UNIQUE)
        return
    # SQLite rebuilds constraints via Django state on reverse; no-op here.

_RESTORE_OLD_UNIQUE = """
ALTER TABLE "Programs_programcurriculumline"
  DROP CONSTRAINT IF EXISTS unique_curriculum_slot;
ALTER TABLE "Programs_programcurriculumline"
  ADD CONSTRAINT unique_curriculum_slot UNIQUE (
    curriculum_version_id,
    catalog_course_id,
    year_of_study,
    term_number
  );
"""


class Migration(migrations.Migration):

    dependencies = [
        ("Programs", "0036_sharedteachingoffering_parent_course_unit"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="programcurriculumline",
                    name="unique_curriculum_slot",
                ),
            ],
            database_operations=[
                migrations.RunPython(
                    drop_old_unique_curriculum_slot,
                    restore_old_unique_curriculum_slot,
                ),
            ],
        ),
        migrations.RunPython(normalize_null_specialization, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="programcurriculumline",
            name="specialization",
            field=models.CharField(
                blank=True,
                default="",
                help_text=(
                    "Track / subject combination this line belongs to "
                    "(e.g. 'Mathematics and Physics'). Blank = shared by all tracks."
                ),
                max_length=100,
            ),
        ),
        migrations.AddConstraint(
            model_name="programcurriculumline",
            constraint=models.UniqueConstraint(
                fields=(
                    "curriculum_version",
                    "catalog_course",
                    "year_of_study",
                    "term_number",
                    "specialization",
                ),
                name="unique_curriculum_slot",
            ),
        ),
    ]
