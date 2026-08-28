"""
Ensure Programs columns that are often missing after faked migrations.

Covers:
  - Programs.0021 registration_kind on StudentCourseUnitEnrollment
  - Programs.0023+ teaching_section_id FKs
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import connection


def _pg_column_exists(cursor, table: str, column: str) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = %s
          AND column_name = %s
        """,
        [table, column],
    )
    return cursor.fetchone() is not None


def _pg_table_exists(cursor, table: str) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = current_schema()
          AND table_name = %s
        """,
        [table],
    )
    return cursor.fetchone() is not None


class Command(BaseCommand):
    help = "Add missing Programs schema columns after faked migrations (idempotent)."

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            self.stdout.write(self.style.WARNING("Only PostgreSQL is supported."))
            return

        added: list[str] = []
        with connection.cursor() as cursor:
            # Programs.0021 — often faked after a false DuplicateColumn, leaving no column.
            scue = "Programs_studentcourseunitenrollment"
            if _pg_table_exists(cursor, scue):
                # IF NOT EXISTS: safe when migrate was faked / prior ensure lied.
                cursor.execute(
                    f'ALTER TABLE "{scue}" '
                    "ADD COLUMN IF NOT EXISTS \"registration_kind\" "
                    "varchar(16) NOT NULL DEFAULT 'normal'"
                )
                cursor.execute(
                    f'CREATE INDEX IF NOT EXISTS "{scue}_registration_kind_idx" '
                    f'ON "{scue}" ("registration_kind")'
                )
                if _pg_column_exists(cursor, scue, "registration_kind"):
                    added.append(f"{scue}.registration_kind")
                else:
                    self.stdout.write(
                        self.style.ERROR(
                            f"Failed to create {scue}.registration_kind — "
                            "check DB permissions / connection target."
                        )
                    )

            if not _pg_table_exists(cursor, "Programs_teachingsection"):
                if added:
                    self.stdout.write(self.style.SUCCESS(f"Added: {', '.join(added)}"))
                self.stdout.write(
                    self.style.WARNING(
                        "Programs_teachingsection does not exist yet — "
                        "skipping teaching_section_id columns."
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
            self.stdout.write(
                self.style.SUCCESS("Programs schema columns already present.")
            )
