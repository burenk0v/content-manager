"""
Django settings for mysite project.
"""
import os
import socket
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.getenv("FRONTEND_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("FRONTEND_SECRET_KEY is required")
DEBUG = os.getenv("DJANGO_DEBUG", "false").lower() == "true"

ALLOWED_HOSTS = ["0.0.0.0", "localhost", "frontend", os.getenv("FRONTEND_HOST", "127.0.0.1"), socket.gethostname()]
FRONTEND_PUBLIC_URL = os.getenv("FRONTEND_PUBLIC_URL", "").strip().rstrip("/")
CSRF_TRUSTED_ORIGINS = [FRONTEND_PUBLIC_URL] if FRONTEND_PUBLIC_URL else [
    "https://localhost:8443", "https://frontend:8443",
    f'https://{os.getenv("FRONTEND_HOST", "127.0.0.1")}:8443',
]

INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "auth_app",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware", "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware", "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware", "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "mysite.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"], "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.debug", "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth", "django.contrib.messages.context_processors.messages",
        "auth_app.context_processors.theme_context",
    ]},
}]
ASGI_APPLICATION = "mysite.asgi.application"

DB_HOST = os.getenv("DB_HOST", "database")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
if not all((DB_NAME, DB_USER, DB_PASSWORD)):
    raise RuntimeError("DB_NAME, DB_USER and DB_PASSWORD are required")
DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql", "NAME": DB_NAME, "USER": DB_USER,
    "PASSWORD": DB_PASSWORD, "HOST": DB_HOST, "PORT": DB_PORT, "CONN_MAX_AGE": 60,
}}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"
