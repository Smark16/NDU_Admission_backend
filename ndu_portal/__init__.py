# This file makes Python treat the directory as a package
from .celery import app as celery_app

__all__ = ("celery_app",)














