"""Shared password helpers for ERP staff accounts."""
from __future__ import annotations

import secrets


def generate_changeme_password() -> str:
    """e.g. Changeme0123 — four random digits."""
    return f"Changeme{secrets.randbelow(10000):04d}"
