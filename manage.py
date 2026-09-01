#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys

DEFAULT_RUNSERVER_PORT = "8001"


def _ensure_runserver_port(default_port: str) -> None:
    if len(sys.argv) < 2 or sys.argv[1] != "runserver":
        return
    has_addr = any(
        (not arg.startswith("-")) and (":" in arg or arg.isdigit())
        for arg in sys.argv[2:]
    )
    if not has_addr:
        sys.argv.append(default_port)


def main():
    """Run administrative tasks."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ndu_portal.settings")
    _ensure_runserver_port(os.environ.get("DJANGO_RUNSERVER_PORT", DEFAULT_RUNSERVER_PORT))
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
