"""
Ensure program_choices_confirmed_at / program_choices_verification_sent_at exist.

Use on production if migration 0027 was faked without creating columns.
"""
from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Add programme choice confirmation columns to admissions_application if missing."

    def handle(self, *args, **options):
        Application = apps.get_model("admissions", "Application")
        table = Application._meta.db_table
        with connection.cursor() as cursor:
            existing = {
                col.name
                for col in connection.introspection.get_table_description(cursor, table)
            }
        vendor = connection.vendor
        added = []

        if "program_choices_verification_sent_at" not in existing:
            sql = (
                "ALTER TABLE admissions_application "
                "ADD COLUMN program_choices_verification_sent_at timestamp with time zone NULL"
                if vendor == "postgresql"
                else "ALTER TABLE admissions_application "
                "ADD COLUMN program_choices_verification_sent_at datetime NULL"
            )
            with connection.cursor() as cursor:
                cursor.execute(sql)
            added.append("program_choices_verification_sent_at")

        if "program_choices_confirmed_at" not in existing:
            sql = (
                "ALTER TABLE admissions_application "
                "ADD COLUMN program_choices_confirmed_at timestamp with time zone NULL"
                if vendor == "postgresql"
                else "ALTER TABLE admissions_application "
                "ADD COLUMN program_choices_confirmed_at datetime NULL"
            )
            with connection.cursor() as cursor:
                cursor.execute(sql)
            added.append("program_choices_confirmed_at")

        if added:
            self.stdout.write(self.style.SUCCESS(f"Added columns: {', '.join(added)}"))
        else:
            self.stdout.write(self.style.SUCCESS("Columns already present — no changes."))
