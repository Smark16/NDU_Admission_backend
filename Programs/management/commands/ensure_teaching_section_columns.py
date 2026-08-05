"""
Ensure TeachingSection FK columns exist after Programs.0023 was faked.

Production often has Programs_teachingsection (table create succeeded) but
never got Programs_studentprogrammeenrollment.teaching_section_id because
migrate stopped / was faked. Moving students into groups then 500s.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import connection


def _pg_column_exists(cursor, table: str, column: str) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
        """,
        [table, column],
    )
    return cursor.fetchone() is not None


def _pg_table_exists(cursor, table: str) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_name = %s
        """,
        [table],
    )
    return cursor.fetchone() is not None


class Command(BaseCommand):
    help = "Add missing teaching_section FK columns (safe / idempotent)."

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            self.stdout.write(self.style.WARNING("Only PostgreSQL is supported."))
            return

        added: list[str] = []
        with connection.cursor() as cursor:
            if not _pg_table_exists(cursor, "Programs_teachingsection"):
                self.stdout.write(
                    self.style.ERROR(
                        "Programs_teachingsection does not exist. "
                        "Run: python manage.py migrate Programs 0023_teaching_section"
                    )
                )
                return

            spe = "Programs_studentprogrammeenrollment"
            if not _pg_column_exists(cursor, spe, "teaching_section_id"):
                cursor.execute(
                    f'ALTER TABLE "{spe}" '
                    'ADD COLUMN "teaching_section_id" bigint NULL '
                    'REFERENCES "Programs_teachingsection"(id) DEFERRABLE INITIALLY DEFERRED'
                )
                cursor.execute(
                    f'CREATE INDEX IF NOT EXISTS "{spe}_teaching_section_id_idx" '
                    f'ON "{spe}" ("teaching_section_id")'
                )
                added.append(f"{spe}.teaching_section_id")

            # Timetable / lecturer section FKs from later faked migrations.
            for table, column in (
                ("Programs_timetablesession", "teaching_section_id"),
                ("Programs_courseunitsectionlecturer", "teaching_section_id"),
            ):
                if not _pg_table_exists(cursor, table):
                    continue
                if _pg_column_exists(cursor, table, column):
                    continue
                cursor.execute(
                    f'ALTER TABLE "{table}" '
                    f'ADD COLUMN "{column}" bigint NULL '
                    'REFERENCES "Programs_teachingsection"(id) DEFERRABLE INITIALLY DEFERRED'
                )
                added.append(f"{table}.{column}")

        if added:
            self.stdout.write(self.style.SUCCESS(f"Added: {', '.join(added)}"))
        else:
            self.stdout.write(self.style.SUCCESS("Teaching section columns already present."))
