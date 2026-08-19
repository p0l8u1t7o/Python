# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Build tools are needed for argon2-cffi; drop them from the final image.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential curl \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-optional.txt ./
RUN pip install -r requirements.txt \
 && pip install -r requirements-optional.txt \
 && apt-get purge -y build-essential \
 && apt-get autoremove -y

COPY . .

# The API, ingestor and worker share one image and differ only by command.
RUN adduser --disabled-password --gecos "" --uid 10001 zqs \
 && mkdir -p /app/data /app/staticfiles \
 && chown -R zqs:zqs /app
USER zqs

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "4", \
     "--timeout", "60", \
     "--access-logfile", "-"]
