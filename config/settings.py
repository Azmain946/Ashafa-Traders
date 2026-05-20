"""
Django settings for config project.
"""

import os
from pathlib import Path
from urllib.parse import urlparse

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-local-dev-only-change-me",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",")
    if h.strip()
]

CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if o.strip()
]

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


def _postgresql_from_url(database_url: str) -> dict:
    if database_url.startswith("postgres://"):
        database_url = "postgresql://" + database_url[len("postgres://") :]
    db_url = urlparse(database_url)
    if db_url.scheme not in ("postgresql", "postgres"):
        raise ImproperlyConfigured(
            f"DATABASE_URL must use postgresql:// (got {db_url.scheme!r})."
        )
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": db_url.path.lstrip("/"),
        "USER": db_url.username or "",
        "PASSWORD": db_url.password or "",
        "HOST": db_url.hostname or "",
        "PORT": str(db_url.port or ""),
    }


def _postgresql_from_env() -> dict:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url:
        return _postgresql_from_url(database_url)

    name = (
        os.environ.get("POSTGRES_DB", "").strip()
        or os.environ.get("DB_NAME", "").strip()
    )
    if not name:
        raise ImproperlyConfigured(
            "PostgreSQL is required. Set DATABASE_URL or POSTGRES_DB "
            "(and POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST, POSTGRES_PORT)."
        )
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": name,
        "USER": os.environ.get("POSTGRES_USER", os.environ.get("DB_USER", "")),
        "PASSWORD": os.environ.get(
            "POSTGRES_PASSWORD", os.environ.get("DB_PASSWORD", "")
        ),
        "HOST": os.environ.get("POSTGRES_HOST", os.environ.get("DB_HOST", "localhost")),
        "PORT": os.environ.get("POSTGRES_PORT", os.environ.get("DB_PORT", "5432")),
    }


DATABASES = {"default": _postgresql_from_env()}


AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "Asia/Dhaka")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

APP_LOW_STOCK_DEFAULT = 10
APP_EXPIRY_ALERT_DAYS_DEFAULT = 60

QZ_CERTIFICATE_PATH = BASE_DIR / "static" / "qz" / "digital-certificate.txt"
QZ_PRIVATE_KEY_PATH = BASE_DIR / "static" / "qz" / "private-key.pem"
