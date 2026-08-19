"""
Ensure SystemSettings portal branding columns exist.

Production deploy may fake accounts.0032 without creating columns, which breaks
/api/accounts/portal_branding and other settings endpoints with 500 errors.
"""
from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Add portal branding columns to accounts_systemsettings if missing."

    def handle(self, *args, **options):
        SystemSettings = apps.get_model("accounts", "SystemSettings")
        table = SystemSettings._meta.db_table
        vendor = connection.vendor

        with connection.cursor() as cursor:
            existing = {
                col.name
                for col in connection.introspection.get_table_description(cursor, table)
            }

        added = []

        if "university_name" not in existing:
            sql = (
                f"ALTER TABLE {table} "
                "ADD COLUMN university_name varchar(255) NOT NULL DEFAULT ''"
            )
            with connection.cursor() as cursor:
                cursor.execute(sql)
            added.append("university_name")

        if "portal_logo" not in existing:
            sql = (
                f"ALTER TABLE {table} "
                "ADD COLUMN portal_logo varchar(100) NULL"
            )
            with connection.cursor() as cursor:
                cursor.execute(sql)
            added.append("portal_logo")

        if "login_cover_image" not in existing:
            sql = (
                f"ALTER TABLE {table} "
                "ADD COLUMN login_cover_image varchar(100) NULL"
            )
            with connection.cursor() as cursor:
                cursor.execute(sql)
            added.append("login_cover_image")

        if "active_staff_id_card_template" not in existing:
            sql = (
                f"ALTER TABLE {table} "
                "ADD COLUMN active_staff_id_card_template varchar(80) NOT NULL DEFAULT ''"
            )
            with connection.cursor() as cursor:
                cursor.execute(sql)
            added.append("active_staff_id_card_template")

        if added:
            self.stdout.write(self.style.SUCCESS(f"Added columns: {', '.join(added)}"))
        else:
            self.stdout.write(self.style.SUCCESS("Portal branding columns already present."))
