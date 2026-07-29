from django.apps import AppConfig


class ProgramsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "Programs"

    def ready(self):
        from . import signals  # noqa: F401
