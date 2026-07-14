from django.apps import AppConfig
from django.db.models.signals import post_migrate

class StaffConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'hr.staff'
    label = 'staff'
    verbose_name = 'HR Staff'
    
    def ready(self):
        from .utils.roles import setup_roles 
        post_migrate.connect(setup_roles)
