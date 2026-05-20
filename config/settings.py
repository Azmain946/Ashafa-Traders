"""
Django settings for Ashafa Pharmacy ERP (Railway / PostgreSQL deployment).
"""

import os
import sys
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

IN_TESTS = "test" in sys.argv

# --- Security ---

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if IN_TESTS:
        SECRET_KEY = "test-secret-key-not-for-production"
    elif os.environ.get("DJANGO_DEBUG", "0") == "1":
        SECRET_KEY = "django-insecure-local-dev-only-change-me"
    else:
        raise RuntimeError("DJANGO_SECRET_KEY environment variable is required in production.")

DEBUG = os.environ.get("DJANGO_DEBUG", "0" if os.environ.get("DATABASE_URL") else "1") == "1"

_railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
_allowed = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if h.strip()]
if not _allowed:
    if _railway_domain:
        _allowed = [_railway_domain, ".up.railway.app", ".railway.app"]
    else:
        _allowed = ["localhost", "127.0.0.1", "testserver"]
ALLOWED_HOSTS = _allowed

_csrf_origins = [o.strip() for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]
if not _csrf_origins and _railway_domain:
    _csrf_origins = [f"https://{_railway_domain}"]
CSRF_TRUSTED_ORIGINS = _csrf_origins

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SECURE_SSL_REDIRECT", "1") == "1"
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "pharmacy",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database — PostgreSQL (Railway DATABASE_URL). SQLite only for `manage.py test`.

def _database_url():
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://") :]
        return url
    user = os.environ.get("PGUSER") or os.environ.get("POSTGRES_USER", "postgres")
    password = os.environ.get("PGPASSWORD") or os.environ.get("POSTGRES_PASSWORD", "postgres")
    host = os.environ.get("PGHOST") or os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("PGPORT") or os.environ.get("POSTGRES_PORT", "5432")
    name = os.environ.get("PGDATABASE") or os.environ.get("POSTGRES_DB", "pharmacy")
    return f"postgresql://{user}:{password}@{host}:{port}/{name}"


if IN_TESTS:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }
else:
    import dj_database_url

    db_config = dj_database_url.parse(
        _database_url(),
        conn_max_age=600,
        conn_health_checks=True,
    )
    if not DEBUG and os.environ.get("DATABASE_SSL", "1") == "1":
        db_config.setdefault("OPTIONS", {})
        db_config["OPTIONS"].setdefault(
            "sslmode", os.environ.get("PGSSLMODE", "require")
        )
    DATABASES = {"default": db_config}


# Password validation

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# Internationalization

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "Asia/Dhaka")
USE_I18N = True
USE_TZ = True


# Static & media

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

APP_LOW_STOCK_DEFAULT = 10
APP_EXPIRY_ALERT_DAYS_DEFAULT = 60

QZ_CERTIFICATE_PATH = BASE_DIR / "static" / "qz" / "digital-certificate.txt"
QZ_PRIVATE_KEY_PATH = BASE_DIR / "static" / "qz" / "private-key.pem"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {
        "handlers": ["console"],
        "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO"),
    },
}
