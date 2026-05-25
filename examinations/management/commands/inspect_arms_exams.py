"""
Read-only discovery of exam/marks-related tables in legacy ARMS v2 MySQL.

Uses the same connection env vars as curriculum audit:
  ARMS_MYSQL_HOST, ARMS_MYSQL_PORT, ARMS_MYSQL_USER, ARMS_MYSQL_PASSWORD, ARMS_MYSQL_DATABASE

Examples:
  python manage.py inspect_arms_exams --password '***'
  python manage.py inspect_arms_exams --password '***' --json-out arms_exam_tables.json
"""
from __future__ import annotations

import json
import re

from django.core.management.base import BaseCommand, CommandError

from Programs.legacy_arms.connection import connect_arms_mysql, fetch_all

TABLE_KEYWORDS = re.compile(
    r"exam|mark|grade|result|assess|score|gpa|transcript|ca_|coursework|test",
    re.I,
)
COLUMN_KEYWORDS = re.compile(
    r"exam|mark|grade|result|assess|score|gpa|coursework|test|ca|cw|final",
    re.I,
)

TABLES_SQL = """
SELECT TABLE_NAME AS table_name, TABLE_ROWS AS approx_rows
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
ORDER BY TABLE_NAME
"""

COLUMNS_SQL = """
SELECT COLUMN_NAME AS column_name, DATA_TYPE AS data_type, COLUMN_TYPE AS column_type
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
ORDER BY ORDINAL_POSITION
"""


class Command(BaseCommand):
    help = "List ARMS v2 tables/columns that look exam or marks related (read-only)."

    def add_arguments(self, parser):
        parser.add_argument("--host", default=None)
        parser.add_argument("--port", type=int, default=None)
        parser.add_argument("--user", default=None)
        parser.add_argument("--password", default=None)
        parser.add_argument("--database", default=None)
        parser.add_argument("--json-out", default=None, help="Write full report to JSON.")
        parser.add_argument(
            "--all-tables",
            action="store_true",
            help="Also print every table name (can be long).",
        )

    def handle(self, *args, **options):
        with connect_arms_mysql(
            host=options["host"],
            port=options["port"],
            user=options["user"],
            password=options["password"],
            database=options["database"],
        ) as connection:
            with connection.cursor() as cursor:
                tables = fetch_all(cursor, TABLES_SQL)
                if not tables:
                    raise CommandError("No tables returned — check database name and permissions.")

                matched = []
                for row in tables:
                    name = row["table_name"]
                    if TABLE_KEYWORDS.search(name):
                        cols = fetch_all(cursor, COLUMNS_SQL, (name,))
                        interesting_cols = [
                            c for c in cols if COLUMN_KEYWORDS.search(c["column_name"])
                        ]
                        matched.append(
                            {
                                "table": name,
                                "approx_rows": row.get("approx_rows"),
                                "columns": cols,
                                "highlight_columns": interesting_cols,
                            }
                        )

                db_name = options["database"]
                if not db_name:
                    raw_db = getattr(connection, "db", None) or getattr(connection, "database", None)
                    db_name = raw_db.decode() if isinstance(raw_db, bytes) else (raw_db or "arms_v2")

                report = {
                    "database": db_name,
                    "table_count": len(tables),
                    "exam_related_tables": matched,
                }

                self.stdout.write(
                    self.style.NOTICE(
                        f"ARMS database: {report['database']} — {report['table_count']} tables"
                    )
                )
                if not matched:
                    self.stdout.write(
                        self.style.WARNING(
                            "No table names matched exam/mark keywords. "
                            "Run with --all-tables or extend TABLE_KEYWORDS after manual review."
                        )
                    )
                for entry in matched:
                    self.stdout.write("")
                    self.stdout.write(self.style.HTTP_INFO(f"  {entry['table']} (~{entry['approx_rows']} rows)"))
                    for col in entry["highlight_columns"] or entry["columns"][:12]:
                        self.stdout.write(f"    - {col['column_name']} ({col['column_type']})")
                    if len(entry["columns"]) > 12 and not entry["highlight_columns"]:
                        self.stdout.write(f"    ... +{len(entry['columns']) - 12} more columns")

                if options["all_tables"]:
                    self.stdout.write("")
                    self.stdout.write("All tables:")
                    for row in tables:
                        self.stdout.write(f"  {row['table_name']}")

                if options["json_out"]:
                    path = options["json_out"]
                    with open(path, "w", encoding="utf-8") as fh:
                        json.dump(report, fh, indent=2, default=str)
                    self.stdout.write(self.style.SUCCESS(f"Wrote {path}"))
