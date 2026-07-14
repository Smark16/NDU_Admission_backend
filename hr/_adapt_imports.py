"""One-off script to adapt copied HRM imports. Run: python hr/_adapt_imports.py"""
from pathlib import Path

root = Path(__file__).resolve().parent
replacements = [
    ("apps.staff", "hr.staff"),
    ("apps.hiring", "hr.hiring"),
    ("apps.leave", "hr.leave"),
    ("apps.appraisal", "hr.appraisal"),
    ("'tenancy.Campus'", "'accounts.Campus'"),
    ("from apps.tenancy.models import Campus", "from accounts.models import Campus"),
    (
        "from apps.tenancy.serializers import CampusSerializer",
        "from hr.staff.serializers import CampusSerializer",
    ),
    ("from apps.accounts.models import User", "from accounts.models import User"),
    ("apps.accounts", "accounts"),
]

for path in root.rglob("*.py"):
    if path.name == "_adapt_imports.py":
        continue
    text = path.read_text(encoding="utf-8")
    orig = text
    for old, new in replacements:
        text = text.replace(old, new)
    if text != orig:
        path.write_text(encoding="utf-8", data=text)
        print("updated", path.relative_to(root.parent))
