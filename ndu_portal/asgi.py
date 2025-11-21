from django.core.wsgi import get_wsgi_application

import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ndu_portal.settings')

application = get_wsgi_application()







