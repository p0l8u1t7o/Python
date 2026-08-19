"""Local development settings."""

from __future__ import annotations

import socket

from config import env  # noqa: F401  (keeps env loaded before base import)

from .base import *  # noqa: F403
from .base import BASE_DIR  # noqa: F401

DEBUG = True
ALLOWED_HOSTS = ["*"]

# Never silently fall back to a shared secret in dev; it is fine to be loud.
CORS_ALLOW_ALL_ORIGINS = True

# Testing from a phone on the same Wi-Fi means requests arrive with a Host of
# 192.168.x.y rather than localhost. ALLOWED_HOSTS above already accepts that,
# and the API is token-authenticated (`csrf=False`), so only the cookie-backed
# views - the admin, the browsable docs form - would otherwise reject the POST.
# Trust this machine's own addresses on the two dev ports so they work too,
# without anyone having to look their IP up first.
try:
    _LAN_ADDRESSES = sorted(
        {
            info[4][0]
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        }
    )
except OSError:  # no DNS, odd hostname setup - not worth failing startup over
    _LAN_ADDRESSES = []

CSRF_TRUSTED_ORIGINS = list(CSRF_TRUSTED_ORIGINS) + [  # noqa: F405
    f"http://{address}:{port}" for address in _LAN_ADDRESSES for port in (8000, 5173)
]

# In-process bus makes `python manage.py runserver` usable with no Redis.
if env.get("BUS_BACKEND", "") == "":
    BUS_BACKEND = "memory"

LOGGING["root"]["level"] = env.get("LOG_LEVEL", "DEBUG").upper()  # noqa: F405
