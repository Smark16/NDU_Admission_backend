"""Live server resource snapshot for the Super Admin dashboard."""
from __future__ import annotations

import os
import shutil
import time

from django.conf import settings
from django.db import connection
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .super_admin import user_is_super_admin


def _bytes_to_mb(value: int) -> float:
    return round(value / (1024 * 1024), 1)


def _cpu_snapshot() -> dict:
    try:
        import psutil
    except ImportError:
        return {"available": False}

    load = None
    try:
        load1, load5, load15 = os.getloadavg()
        load = {"1m": round(load1, 2), "5m": round(load5, 2), "15m": round(load15, 2)}
    except (OSError, AttributeError):
        pass

    return {
        "available": True,
        "percent": psutil.cpu_percent(interval=0.3),
        "core_count": psutil.cpu_count(logical=True) or 1,
        "load_average": load,
    }


def _memory_snapshot() -> dict:
    try:
        import psutil
    except ImportError:
        return {"available": False}

    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()
    return {
        "available": True,
        "total_mb": _bytes_to_mb(vm.total),
        "used_mb": _bytes_to_mb(vm.total - vm.available),
        "percent": vm.percent,
        "swap_percent": swap.percent,
    }


def _disk_snapshot() -> dict:
    usage = shutil.disk_usage(str(settings.BASE_DIR))
    percent = round((usage.used / usage.total) * 100, 1) if usage.total else 0.0
    return {
        "total_mb": _bytes_to_mb(usage.total),
        "used_mb": _bytes_to_mb(usage.used),
        "free_mb": _bytes_to_mb(usage.free),
        "percent": percent,
    }


def _uptime_snapshot() -> dict:
    try:
        import psutil
    except ImportError:
        return {"available": False}

    seconds = int(time.time() - psutil.boot_time())
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return {"available": True, "seconds": seconds, "label": " ".join(parts)}


def _database_snapshot() -> dict:
    engine = connection.settings_dict.get("ENGINE", "")
    if "postgresql" not in engine:
        return {"engine": engine, "size_mb": None, "active_connections": None}
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_database_size(current_database())")
        size_bytes = cursor.fetchone()[0]
        cursor.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
        )
        active_connections = cursor.fetchone()[0]
    return {
        "engine": "postgresql",
        "size_mb": _bytes_to_mb(size_bytes),
        "active_connections": active_connections,
    }


class SystemHealthView(APIView):
    """Super-Admin-only snapshot of CPU / memory / disk / DB usage."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not user_is_super_admin(request.user):
            return Response({"detail": "Forbidden."}, status=403)

        return Response(
            {
                "cpu": _cpu_snapshot(),
                "memory": _memory_snapshot(),
                "disk": _disk_snapshot(),
                "uptime": _uptime_snapshot(),
                "database": _database_snapshot(),
                "checked_at": time.time(),
            }
        )
