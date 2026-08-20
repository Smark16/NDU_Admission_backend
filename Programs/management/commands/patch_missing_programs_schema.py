"""
Idempotent SQL patches for Programs columns that were marked migrated but
never applied on production (faked / DiskFull mid-migrate).

Fixes student timetable, course registration, and related 500s.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import connection


PATCHES = [
    (
        "Programs_program.department_id",
        '''
        ALTER TABLE "Programs_program"
        ADD COLUMN IF NOT EXISTS department_id bigint NULL
        REFERENCES admissions_academicdepartment(id) ON DELETE SET NULL;
        ''',
    ),
    (
        "Programs_teachingsection.is_shared",
        '''
        ALTER TABLE "Programs_teachingsection"
        ADD COLUMN IF NOT EXISTS is_shared boolean NOT NULL DEFAULT false;
        ''',
    ),
    (
        "Programs_teachingsection_linked_batches",
        '''
        CREATE TABLE IF NOT EXISTS "Programs_teachingsection_linked_batches" (
            id bigserial PRIMARY KEY,
            teachingsection_id bigint NOT NULL
                REFERENCES "Programs_teachingsection"(id) ON DELETE CASCADE,
            programbatch_id bigint NOT NULL
                REFERENCES "Programs_programbatch"(id) ON DELETE CASCADE,
            UNIQUE (teachingsection_id, programbatch_id)
        );
        ''',
    ),
    (
        "Programs_studentcourseunitenrollment.registration_kind",
        '''
        ALTER TABLE "Programs_studentcourseunitenrollment"
        ADD COLUMN IF NOT EXISTS registration_kind varchar(16) NOT NULL DEFAULT 'normal';
        ''',
    ),
    (
        "Programs_studentcourseunitenrollment.registration_kind_idx",
        '''
        CREATE INDEX IF NOT EXISTS programs_scue_registration_kind_idx
        ON "Programs_studentcourseunitenrollment" (registration_kind);
        ''',
    ),
    (
        "Programs_timetablesession.start_date",
        '''
        ALTER TABLE "Programs_timetablesession"
        ADD COLUMN IF NOT EXISTS start_date date NULL;
        ''',
    ),
    (
        "Programs_timetablesession.end_date",
        '''
        ALTER TABLE "Programs_timetablesession"
        ADD COLUMN IF NOT EXISTS end_date date NULL;
        ''',
    ),
]


class Command(BaseCommand):
    help = "Add missing Programs schema columns that cause timetable/registration 500s."

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            for label, sql in PATCHES:
                try:
                    cursor.execute(sql)
                    self.stdout.write(self.style.SUCCESS(f"OK  {label}"))
                except Exception as exc:
                    self.stderr.write(self.style.ERROR(f"FAIL {label}: {exc}"))
        self.stdout.write("Done. Restart gunicorn: sudo systemctl restart gunicorn")
