from __future__ import annotations

import os
from typing import Any

from django.core.management.base import CommandError


def connect_arms_mysql(
    *,
    host: str | None = None,
    port: int | None = None,
    user: str | None = None,
    password: str | None = None,
    database: str | None = None,
):
    try:
        import pymysql
    except ImportError as exc:
        raise CommandError(
            "PyMySQL is required for ARMS legacy database access. "
            "Install it with: pip install pymysql"
        ) from exc

    resolved = {
        "host": host or os.environ.get("ARMS_MYSQL_HOST", "localhost"),
        "port": int(port or os.environ.get("ARMS_MYSQL_PORT", "3306")),
        "user": user or os.environ.get("ARMS_MYSQL_USER", "admin"),
        "password": password or os.environ.get("ARMS_MYSQL_PASSWORD", ""),
        "database": database or os.environ.get("ARMS_MYSQL_DATABASE", "arms_v2"),
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
        "connect_timeout": 10,
        "read_timeout": 120,
        "write_timeout": 120,
    }
    if not resolved["password"]:
        raise CommandError(
            "Set ARMS_MYSQL_PASSWORD or pass --password for the legacy ARMS database."
        )
    try:
        return pymysql.connect(**resolved)
    except Exception as exc:
        raise CommandError(f"Could not connect to ARMS MySQL ({resolved['host']}): {exc}") from exc


def fetch_all(cursor, sql: str, params: tuple[Any, ...] | None = None) -> list[dict]:
    cursor.execute(sql, params or ())
    rows = cursor.fetchall()
    return list(rows or [])
