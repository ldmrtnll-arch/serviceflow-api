import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import DATABASES, env_bool


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ImproperlyConfigured(f"{name} must be set in production.")
    return value


DEBUG = False
SECRET_KEY = required_env("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = [value.strip() for value in required_env("DJANGO_ALLOWED_HOSTS").split(",")]
CSRF_TRUSTED_ORIGINS = [
    value.strip()
    for value in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if value.strip()
]

SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", True)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", True)
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", True)
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", True)
if env_bool("SECURE_PROXY_SSL_HEADER_ENABLED", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

statement_timeout = int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "30000"))
if DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql":
    DATABASES["default"].setdefault("OPTIONS", {})["options"] = (
        f"-c statement_timeout={statement_timeout}"
    )
