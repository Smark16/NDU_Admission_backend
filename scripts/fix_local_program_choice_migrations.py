"""
One-off fix for local SQLite DBs that applied the old 0025_application_program_choice
(preference column) but not the new 0022_applicationprogramchoice chain (choice_order).

Run from NDU_Admission_backend:
    python scripts/fix_local_program_choice_migrations.py
"""
import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ndu_portal.settings")
django.setup()

from django.core.management import call_command
from django.db import connection


def column_names(table: str) -> set[str]:
    with connection.cursor() as c:
        c.execute(f"PRAGMA table_info({table})")
        return {row[1] for row in c.fetchall()}


def main() -> None:
    choice_cols = column_names("admissions_applicationprogramchoice")
    print("ApplicationProgramChoice columns:", sorted(choice_cols))

    with connection.cursor() as c:
        if "preference" in choice_cols and "choice_order" not in choice_cols:
            print("Renaming preference -> choice_order …")
            c.execute(
                "ALTER TABLE admissions_applicationprogramchoice "
                "RENAME COLUMN preference TO choice_order"
            )
            choice_cols = column_names("admissions_applicationprogramchoice")

        if "created_at" not in choice_cols:
            print("Adding created_at …")
            c.execute(
                "ALTER TABLE admissions_applicationprogramchoice "
                "ADD COLUMN created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP"
            )

        stale = [
            "0025_application_program_choice",
            "0026_application_program_choice_confirmation",
        ]
        for name in stale:
            c.execute(
                "DELETE FROM django_migrations WHERE app = %s AND name = %s",
                ["admissions", name],
            )
            print(f"Removed stale migration record: {name}")

    to_fake = [
        "0022_applicationprogramchoice",
        "0023_remove_application_programs",
        "0024_application_programs",
        "0025_remove_application_programs",
        "0026_merge_20260515_0209",
    ]
    for name in to_fake:
        print(f"Faking {name} …")
        call_command("migrate", "admissions", name, "--fake", verbosity=1)

    app_cols = column_names("admissions_application")
    if "program_choices_confirmed_at" in app_cols:
        print("Faking 0027_application_program_choice_confirmation (columns already exist) …")
        call_command(
            "migrate",
            "admissions",
            "0027_application_program_choice_confirmation",
            "--fake",
            verbosity=1,
        )
    else:
        print("Applying 0027_application_program_choice_confirmation …")
        call_command(
            "migrate",
            "admissions",
            "0027_application_program_choice_confirmation",
            verbosity=1,
        )

    print("Applying remaining migrations …")
    call_command("migrate", verbosity=1)
    print("Done.")


if __name__ == "__main__":
    main()
