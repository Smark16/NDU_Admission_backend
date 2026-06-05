"""
Print staff programme-change audit rows for today (server TZ), tab-separated — copy from terminal.

Run from backend root with Django loaded::

    cd /home/admissions/NDU_Admission_backend
    python manage.py shell < scripts/print_staff_programme_audit_today.py

Optional: edit CUSTOM_DAY below (uncomment and set a date).

If you see "0 event(s)" but expect data:
  - Pull latest backend (logging lives in admissions/views.py ChangeApplicationProgramme).
  - python manage.py migrate audit
  - restart gunicorn — then staff must use Change Programme again (old edits were not logged).
"""

from datetime import date, datetime, timedelta

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from audit.models import AuditLog
from admissions.models import Application
from admissions.utils.application_programs_display import ordered_programs_for_application

ACTION = "program_choice_admin_change"

# Uncomment to pin a calendar day instead of “today”:
# CUSTOM_DAY = date(2026, 5, 16)
CUSTOM_DAY = None


def names_from_audit(desc: str) -> list[str]:
    if not desc or "Programmes:" not in desc:
        return []
    segment = desc.split("Programmes:", 1)[1].strip().split(";", 1)[0].strip()
    return [x.strip() for x in segment.split(",") if x.strip()]


# --- diagnostics (helps when count is 0)
app_ct = ContentType.objects.get_for_model(Application)
all_time = AuditLog.objects.filter(action=ACTION, content_type=app_ct).count()
print(f"[diag] Audit rows action={ACTION!r} content=Application (all time): {all_time}")
recent = (
    AuditLog.objects.filter(content_type=app_ct)
    .order_by("-timestamp")[:12]
)
if recent:
    print("[diag] Latest 12 Application-linked audit actions (action, timestamp):")
    for r in recent:
        print(f"       {r.action!r}\t{r.timestamp.isoformat(timespec='seconds')}")
else:
    print("[diag] No Application-linked AuditLog rows at all.")
print()

day = CUSTOM_DAY if CUSTOM_DAY else timezone.localdate()
start = timezone.make_aware(
    datetime.combine(day, datetime.min.time()),
    timezone.get_current_timezone(),
)
end = start + timedelta(days=1)

logs = list(
    AuditLog.objects.filter(
        action=ACTION,
        content_type=app_ct,
        timestamp__gte=start,
        timestamp__lt=end,
    )
    .select_related("user")
    .order_by("timestamp", "id")
)

ids = sorted({log.object_id for log in logs if log.object_id})
apps_map = {
    a.pk: a
    for a in Application.objects.filter(pk__in=ids)
    .select_related("campus")
    .prefetch_related("program_choices__program", "program_choices__program__faculty")
}

print(f"DATE {day.isoformat()} ({timezone.get_current_timezone_name()}) — {len(logs)} event(s)")
print()

for log in logs:
    aid = log.object_id
    app = apps_map.get(aid) if aid else None
    prog_names = names_from_audit(log.description)
    if not prog_names and app:
        prog_names = [p.name for p in ordered_programs_for_application(app)]
    staff = (
        getattr(log.user, "email", None)
        or getattr(log.user, "username", None)
        or str(log.user_id or "")
    )
    if app:
        ln, fn, em, st = app.last_name or "", app.first_name or "", app.email or "", app.status or ""
        camp = app.campus.name if app.campus else ""
    else:
        ln = fn = em = st = camp = ""

    ts = log.timestamp.isoformat(timespec="seconds")
    choices = " | ".join(prog_names) if prog_names else ""
    print(f"{ts}\t{staff}\t{aid}\t{ln}\t{fn}\t{em}\t{st}\t{camp}\t{choices}")

print()
print("(Tab-separated header would be: time, staff, app_id, last, first, email, status, campus, programmes)")
