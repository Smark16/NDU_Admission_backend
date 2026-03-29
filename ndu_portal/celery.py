import os
from celery import Celery

# Set default Django settings
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ndu_portal.settings")

app = Celery("ndu_portal")

# Load config from Django settings, using a CELERY_ prefix
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks inside all apps
app.autodiscover_tasks()