"""Production settings.

Fails fast on missing secrets rather than booting with insecure defaults.
"""

from __future__ import annotations

from config import env

from .base import *  # noqa: F403

DEBUG = False

SECRET_KEY = env.get("DJANGO_SECRET_KEY")
JWT_SIGNING_KEY = env.get("JWT_SIGNING_KEY", SECRET_KEY)
ALLOWED_HOSTS = env.get_list("DJANGO_ALLOWED_HOSTS")
if not ALLOWED_HOSTS:
    raise env.ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must be set in production")

CORS_ALLOW_ALL_ORIGINS = False

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.get_bool("SECURE_SSL_REDIRECT", True)
SECURE_HSTS_SECONDS = env.get_int("SECURE_HSTS_SECONDS", 31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"
