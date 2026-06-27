import os
from pathlib import Path
from decouple import config
from datetime import timedelta
from .env import BASE_DIR, env
from celery.schedules import crontab

# Build paths inside the project like this: BASE_DIR / 'subdir'.
env.read_env(os.path.join(BASE_DIR, '.env'))

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env('SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env.bool('DEBUG')

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[
    '127.0.0.1',
    'localhost',
    'applications.ndu.ac.ug',
    'applications-admin.ndu.ac.ug',
    'https://www.schoolpaytest.servicecops.com',
    '.ndu.ac.ug',           
    '794e-41-75-173-12.ngrok-free.app'
])
# Application definition
DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
]

THIRD_PARTY_APPS = [
    'crispy_forms',
    'crispy_bootstrap5',
    'django_extensions',
    "rest_framework",
    "corsheaders",
    'easyaudit',
]

LOCAL_APPS = [
    'accounts',
    'admissions',
    'audit',
    'payments',
    'Programs',
    'examinations',
    'graduation',
    'Drafts',
    'OfferLetter.AdmissionLetter',
    'OfferLetter.AdmissionReports'
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    "corsheaders.middleware.CorsMiddleware",
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    # 'django.middleware.csrf.CsrfViewMiddleware',
    'easyaudit.middleware.easyaudit.EasyAuditMiddleware',
    # 'django.contrib.auth.middleware.AuthenticationMiddleware',
    'audit.middleware.PatchedAuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

if DEBUG:
    THIRD_PARTY_APPS += ["debug_toolbar"]
    MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")

    INTERNAL_IPS = [
        "127.0.0.1",
    ]

    # Run Celery tasks synchronously in development — no worker/broker needed
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = True

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

ROOT_URLCONF = 'ndu_portal.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'ndu_portal.wsgi.application'

# caching
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# Database
if DEBUG:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
            'OPTIONS': {
                'timeout': 20,
            }
        }
    }
else:
 DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        "NAME": env("DB_NAME"),
        "USER": env("DB_USER"),
        "PASSWORD": env("DB_PASSWORD"),
        "HOST": env("DB_HOST"),
        "PORT": 6432,
        "CONN_MAX_AGE": 0, 
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Kampala'
USE_I18N = True
USE_TZ = True

# Security settings
SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=False)
SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=False)
SECURE_HSTS_PRELOAD = env.bool('SECURE_HSTS_PRELOAD', default=False)
SECURE_BROWSER_XSS_FILTER = env.bool('SECURE_BROWSER_XSS_FILTER', default=False)
SECURE_CONTENT_TYPE_NOSNIFF = env.bool('SECURE_CONTENT_TYPE_NOSNIFF', default=False)
SECURE_REFERRER_POLICY = env.str('SECURE_REFERRER_POLICY', default='unsafe-url')

# Session security
SESSION_COOKIE_SECURE = env.bool('SESSION_COOKIE_SECURE', default=False)

# Static files (CSS, JavaScript, Images)
STATIC_URL = "/static/"
STATIC_ROOT = env.str("STATIC_ROOT", default=BASE_DIR / "staticfiles")

STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = env.str("MEDIA_ROOT", default=os.path.join(BASE_DIR, 'media'))

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

SITE_ID=1

# Custom User Model
AUTH_USER_MODEL = 'accounts.User'

AUTHENTICATION_BACKENDS = [
    'accounts.backends.StudentIdBackend',
    'django.contrib.auth.backends.ModelBackend',
]

# Crispy Forms g
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

# File Upload Settings
FILE_UPLOAD_MAX_MEMORY_SIZE = 100 * 1024 * 1024  # 100MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 100 * 1024 * 1024  # 100MB
FILE_UPLOAD_PERMISSIONS = 0o644

# Celery Configuration
CELERY_BROKER_URL = "redis://127.0.0.1:6379/0"   
CELERY_RESULT_BACKEND = "redis://127.0.0.1:6379/0" 
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "Africa/Kampala"

CELERY_BEAT_SCHEDULE = {
    "process-delayed-payments-every-fiveminutes": {
        "task": "payments.tasks.auto_process_delayed_payments",
        "schedule": crontab(minute="*/5"),
    },
    "process-removing-of-drafts" : {
        "task": "Drafts.tasks.auto_process_drafts_deletion",
        "schedule": crontab(minute="*/5"),
    },
    "sync-schoolpay-transactions-everyday": {
        "task": "payments.tasks.celery_sync_schoolpay_transactions",
        "schedule": crontab(minute="*/1")
    },
    "check-weekly-admissions-digest": {
        "task": "admissions.tasks.celery_maybe_send_weekly_admissions_digest",
        "schedule": crontab(minute="*/15"),
    },
}

# school pay configuration
SCHOOL_PAY_CODE = env('SCHOOL_PAY_CODE')
SCHOOL_PAY_PASSWORD = env('SCHOOL_PAY_PASSWORD')

# send grid
SENDGRID_API_KEY=env('SENDGRID_API_KEY')

# login url
LOGIN_URL=env('LOGIN_URL')

# erp frontend url
ERP_FRONTEND_URL=env('ERP_FRONTEND_URL')

# backend url
BACKEND_URL=env('BACKEND_URL')

CSRF_TRUSTED_ORIGINS = [
    'http://localhost:5173',
    'http://localhost:3000',
    'http://localhost:3001',
    'http://127.0.0.1:3000',
    'http://127.0.0.1:3001',
    'https://applications.ndu.ac.ug',
    'https://applications-admin.ndu.ac.ug',
    'http://172.17.31.147',
    "https://admissions.ndu.ac.ug",
    "https://erp.ndejje.ndu.ac.ug",
    "http://test.ndu.ac.ug",
    "https://test.ndu.ac.ug",
    "http://137.63.139.78"
]

# CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True

CORS_ALLOWED_ORIGINS = [
    "https://applications.ndu.ac.ug",
    "https://applications-admin.ndu.ac.ug",
    "http://137.63.139.78",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://admissions.ndu.ac.ug",
    "http://localhost:3001",
    "https://erp.ndejje.ndu.ac.ug",
    "https://www.schoolpay.co.ug",
    "https://schoolpaytest.servicecops.com",
    "http://test.ndu.ac.ug",
    "https://test.ndu.ac.ug",
]

# More flexible option - Recommended for your case
CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^https?://([a-z0-9-]+\.)*ndu\.ac\.ug$",
    r"^http://137\.63\.139\.78$",
]

# Important for debugging
CORS_EXPOSE_HEADERS = ['Content-Type', 'Authorization', 'X-CSRFToken']
CORS_ALLOW_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS']
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        # JWT only — BasicAuthentication adds WWW-Authenticate on 401 and triggers the browser login dialog in SPAs.
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ]
}

SIMPLE_JWT = {
    # Longer access lifetime reduces refresh churn during slow operations (e.g. offer-letter PDF + polling).
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=4),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,

    "ALGORITHM": "HS256",  # Google uses RS256, not HS256
    "SIGNING_KEY": SECRET_KEY,

    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",

    "JTI_CLAIM": "jti",
    "LEEWAY": timedelta(minutes=5),  # Allow a small time difference
}

# production logs
LOGS_DIR = BASE_DIR / 'logs'
LOGS_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{asctime} {levelname} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'ERROR',
            'class': 'logging.FileHandler',
            'filename': str(LOGS_DIR / 'django_errors.log'),
            'formatter': 'verbose',
        },
        'console': {
            'level': 'ERROR',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['file', 'console'],
            'level': 'ERROR',
            'propagate': True,
        },
    },
}
