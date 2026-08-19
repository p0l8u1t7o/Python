"""Base settings shared by every deployment target.

Everything environment-specific is read through :mod:`config.env` so the same
image can run in dev, staging and production.
"""

from __future__ import annotations

from pathlib import Path

from config import env

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# --------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------
SECRET_KEY = env.get("DJANGO_SECRET_KEY", "insecure-dev-key-change-me")
DEBUG = env.get_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env.get_list("DJANGO_ALLOWED_HOSTS", ["*"])
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    # Project apps
    "apps.core",
    "apps.accounts",
    "apps.devices",
    "apps.telemetry",
    "apps.alerts",
    "apps.audit",
    "apps.ems",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "apps.core.middleware.RequestContextMiddleware",
]

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

# --------------------------------------------------------------------------
# Database - SQLite by default, swappable without touching application code
# --------------------------------------------------------------------------
DB_ENGINE = env.get("DB_ENGINE", "sqlite").lower()

if DB_ENGINE in {"postgres", "postgresql", "timescale", "timescaledb"}:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env.get("DB_NAME", "zqs_cloud"),
            "USER": env.get("DB_USER", "zqs"),
            "PASSWORD": env.get("DB_PASSWORD", ""),
            "HOST": env.get("DB_HOST", "127.0.0.1"),
            "PORT": env.get("DB_PORT", "5432"),
            "CONN_MAX_AGE": env.get_int("DB_CONN_MAX_AGE", 60),
            "OPTIONS": {"connect_timeout": env.get_int("DB_CONNECT_TIMEOUT", 10)},
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": env.get("DB_NAME", str(BASE_DIR / "data" / "zqs_cloud.sqlite3")),
            "OPTIONS": {
                # WAL keeps the ingest worker writing while the API reads.
                "init_command": (
                    "PRAGMA journal_mode=WAL;"
                    "PRAGMA synchronous=NORMAL;"
                    "PRAGMA busy_timeout=10000;"
                    "PRAGMA foreign_keys=ON;"
                ),
                "transaction_mode": "IMMEDIATE",
            },
        }
    }

# Marks whether the active backend supports TimescaleDB style helpers. The
# telemetry repository degrades gracefully when False.
TIMESCALE_ENABLED = env.get_bool(
    "TIMESCALE_ENABLED", DB_ENGINE in {"timescale", "timescaledb"}
)

# --------------------------------------------------------------------------
# Password hashing / validation
# --------------------------------------------------------------------------
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation."
        "UserAttributeSimilarityValidator"
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": env.get_int("PASSWORD_MIN_LENGTH", 10)},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --------------------------------------------------------------------------
# i18n / l10n - English, Traditional Chinese, Simplified Chinese
# --------------------------------------------------------------------------
LANGUAGE_CODE = env.get("DEFAULT_LANGUAGE", "en")
TIME_ZONE = env.get("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

LANGUAGES = [
    ("en", "English"),
    ("zh-hant", "繁體中文"),
    ("zh-hans", "简体中文"),
]
LOCALE_PATHS = [BASE_DIR / "locale"]

# Timezone used when rendering energy interval / billing boundaries.
SITE_DEFAULT_TIMEZONE = env.get("SITE_DEFAULT_TIMEZONE", "Asia/Taipei")

# --------------------------------------------------------------------------
# Static files
# --------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

# --------------------------------------------------------------------------
# CORS (React dev server / production SPA origin)
# --------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env.get_list(
    "CORS_ALLOWED_ORIGINS", ["http://localhost:5173", "http://127.0.0.1:5173"]
)
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = env.get_list("CSRF_TRUSTED_ORIGINS", CORS_ALLOWED_ORIGINS)

# --------------------------------------------------------------------------
# JWT
# --------------------------------------------------------------------------
JWT_SIGNING_KEY = env.get("JWT_SIGNING_KEY", SECRET_KEY)
JWT_ALGORITHM = env.get("JWT_ALGORITHM", "HS256")
JWT_ISSUER = env.get("JWT_ISSUER", "zqs-cloud")
JWT_ACCESS_TTL_SECONDS = env.get_int("JWT_ACCESS_TTL_SECONDS", 15 * 60)
JWT_REFRESH_TTL_SECONDS = env.get_int("JWT_REFRESH_TTL_SECONDS", 14 * 24 * 3600)

# --------------------------------------------------------------------------
# MQTT (EMQX)
# --------------------------------------------------------------------------
MQTT = {
    "HOST": env.get("MQTT_HOST", "127.0.0.1"),
    "PORT": env.get_int("MQTT_PORT", 1883),
    "USERNAME": env.get("MQTT_USERNAME", ""),
    "PASSWORD": env.get("MQTT_PASSWORD", ""),
    "TLS_ENABLED": env.get_bool("MQTT_TLS_ENABLED", False),
    "TLS_CA_CERT": env.get("MQTT_TLS_CA_CERT", ""),
    "TLS_CERTFILE": env.get("MQTT_TLS_CERTFILE", ""),
    "TLS_KEYFILE": env.get("MQTT_TLS_KEYFILE", ""),
    "TLS_INSECURE": env.get_bool("MQTT_TLS_INSECURE", False),
    "KEEPALIVE": env.get_int("MQTT_KEEPALIVE", 45),
    "CLIENT_ID_PREFIX": env.get("MQTT_CLIENT_ID_PREFIX", "zqs"),
    "TOPIC_ROOT": env.get("MQTT_TOPIC_ROOT", "energy/devices"),
    # EMQX shared subscriptions let several ingestor replicas split the load.
    "SHARED_SUBSCRIPTION_GROUP": env.get("MQTT_SHARED_GROUP", "zqs-ingestor"),
    "USE_SHARED_SUBSCRIPTION": env.get_bool("MQTT_USE_SHARED_SUBSCRIPTION", True),
    "QOS_UPLINK": env.get_int("MQTT_QOS_UPLINK", 1),
    "QOS_DOWNLINK": env.get_int("MQTT_QOS_DOWNLINK", 1),
    "RECONNECT_MIN_DELAY": env.get_int("MQTT_RECONNECT_MIN_DELAY", 1),
    "RECONNECT_MAX_DELAY": env.get_int("MQTT_RECONNECT_MAX_DELAY", 60),
}

# Shared secret EMQX presents when calling the auth / ACL webhooks.
EMQX_WEBHOOK_TOKEN = env.get("EMQX_WEBHOOK_TOKEN", "")

# --------------------------------------------------------------------------
# Internal message bus
# --------------------------------------------------------------------------
BUS_BACKEND = env.get("BUS_BACKEND", "redis").lower()  # redis | rabbitmq | memory
BUS = {
    "REDIS_URL": env.get("REDIS_URL", "redis://127.0.0.1:6379/0"),
    "AMQP_URL": env.get("AMQP_URL", "amqp://guest:guest@127.0.0.1:5672/%2F"),
    "STREAM_PREFIX": env.get("BUS_STREAM_PREFIX", "zqs"),
    "CONSUMER_GROUP": env.get("BUS_CONSUMER_GROUP", "zqs-workers"),
    # Trim streams so a stalled worker cannot fill the disk.
    "MAX_STREAM_LENGTH": env.get_int("BUS_MAX_STREAM_LENGTH", 1_000_000),
    "CLAIM_MIN_IDLE_MS": env.get_int("BUS_CLAIM_MIN_IDLE_MS", 60_000),
}

# --------------------------------------------------------------------------
# Ingestion / worker tuning
# --------------------------------------------------------------------------
INGEST = {
    # Reject samples whose timestamp drifts too far from server time.
    "MAX_CLOCK_SKEW_FUTURE_S": env.get_int("INGEST_MAX_SKEW_FUTURE_S", 300),
    "MAX_CLOCK_SKEW_PAST_S": env.get_int("INGEST_MAX_SKEW_PAST_S", 7 * 24 * 3600),
    "MAX_PAYLOAD_BYTES": env.get_int("INGEST_MAX_PAYLOAD_BYTES", 256 * 1024),
    "MAX_METRICS_PER_MESSAGE": env.get_int("INGEST_MAX_METRICS_PER_MESSAGE", 512),
    # Auto-register devices seen on the wire but absent from the registry.
    "AUTO_PROVISION": env.get_bool("INGEST_AUTO_PROVISION", False),
    "AUTO_PROVISION_ORG_SLUG": env.get("INGEST_AUTO_PROVISION_ORG", "default"),
}

WORKER = {
    "BATCH_SIZE": env.get_int("WORKER_BATCH_SIZE", 500),
    "BATCH_FLUSH_INTERVAL_MS": env.get_int("WORKER_FLUSH_INTERVAL_MS", 2000),
    "BLOCK_MS": env.get_int("WORKER_BLOCK_MS", 1000),
    "REGISTRY_CACHE_TTL_S": env.get_int("WORKER_REGISTRY_CACHE_TTL_S", 30),
    "MAX_RETRIES": env.get_int("WORKER_MAX_RETRIES", 3),
}

# Device is considered offline when no uplink arrives within this window and no
# explicit LWT was received.
DEVICE_OFFLINE_GRACE_SECONDS = env.get_int("DEVICE_OFFLINE_GRACE_SECONDS", 180)

# Default downlink command timeout before it is marked as expired.
COMMAND_DEFAULT_TIMEOUT_SECONDS = env.get_int("COMMAND_DEFAULT_TIMEOUT_SECONDS", 60)

# --------------------------------------------------------------------------
# Cache (also backs the worker's registry / policy cache)
# --------------------------------------------------------------------------
if env.get("CACHE_BACKEND", "locmem") == "redis":
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": env.get("CACHE_REDIS_URL", BUS["REDIS_URL"]),
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "zqs-default",
        }
    }

# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
LOG_LEVEL = env.get("LOG_LEVEL", "INFO").upper()
LOG_JSON = env.get_bool("LOG_JSON", False)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)-8s %(name)s %(message)s"},
        "json": {"()": "apps.core.logging.JsonFormatter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json" if LOG_JSON else "plain",
        },
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django.db.backends": {"level": "WARNING", "propagate": True},
        "zqs": {"level": LOG_LEVEL, "propagate": True},
    },
}

# --------------------------------------------------------------------------
# django-ninja
# --------------------------------------------------------------------------
NINJA_PAGINATION_PER_PAGE = env.get_int("API_PAGE_SIZE", 50)
NINJA_PAGINATION_MAX_LIMIT = env.get_int("API_PAGE_MAX_SIZE", 1000)
