"""API assembly: routers, authentication and the error contract.

Every failure leaves through one of the handlers below, so clients always get
``{"error": {"code": ..., "message": ..., "details": ...}}`` with a stable
machine-readable ``code`` they can map to a translated message.
"""

from __future__ import annotations

import orjson
from django.conf import settings
from django.db import DatabaseError
from django.http import Http404
from ninja import NinjaAPI
from ninja.errors import AuthenticationError as NinjaAuthError
from ninja.errors import ValidationError as NinjaValidationError
from ninja.renderers import BaseRenderer

from apps.accounts.api import apikey_router, member_router, org_router, router as auth_router
from apps.accounts.security import api_auth
from apps.alerts.api import alerts_router, channels_router, rules_router
from apps.audit.api import router as audit_router
from apps.core.errors import APIError
from apps.core.logging import get_logger
from apps.core.system_api import router as system_router
from apps.devices.api import (
    blueprints_router,
    commands_router,
    devices_router,
    edge_nodes_router,
    events_router,
    sites_router,
)
from apps.devices.emqx import router as emqx_router
from apps.workflows.api import router as workflows_router, runs_router as workflow_runs_router
from apps.ems.api import router as ems_router
from apps.telemetry.api import metrics_router, policies_router, series_router

logger = get_logger("api")


class ORJSONRenderer(BaseRenderer):
    """orjson is materially faster on the large arrays telemetry endpoints return."""

    media_type = "application/json"

    def render(self, request, data, *, response_status):
        return orjson.dumps(data, default=str)


api = NinjaAPI(
    title="ZQS Cloud API",
    version="1.0.0",
    description=(
        "Control and data plane for distributed energy devices: registry, "
        "telemetry, alerting, downlink commands and behind-the-meter storage."
    ),
    auth=api_auth,
    renderer=ORJSONRenderer(),
    urls_namespace="zqs",
    docs_url="/docs" if settings.DEBUG else None,
    csrf=False,  # token auth only; no cookie-based session for the API
)

# --------------------------------------------------------------------------
# Routers
# --------------------------------------------------------------------------
api.add_router("/", auth_router)
api.add_router("/organizations", org_router)
api.add_router("/members", member_router)
api.add_router("/api-keys", apikey_router)

api.add_router("/sites", sites_router)
api.add_router("/blueprints", blueprints_router)
api.add_router("/devices", devices_router)
api.add_router("/edge-nodes", edge_nodes_router)
api.add_router("/events", events_router)
api.add_router("/workflows", workflows_router)
api.add_router("/workflow-runs", workflow_runs_router)
api.add_router("/commands", commands_router)

api.add_router("/metrics", metrics_router)
api.add_router("/recording-policies", policies_router)
api.add_router("/telemetry", series_router)

api.add_router("/alert-rules", rules_router)
api.add_router("/alerts", alerts_router)
api.add_router("/notification-channels", channels_router)

api.add_router("/audit", audit_router)
api.add_router("/ems", ems_router)
api.add_router("/system", system_router)
api.add_router("/emqx", emqx_router)


# --------------------------------------------------------------------------
# Error handling
# --------------------------------------------------------------------------
@api.exception_handler(APIError)
def handle_api_error(request, exc: APIError):
    if exc.status_code >= 500:
        # Never use "message" as an extra key: logging reserves it on LogRecord
        # and raises, which would turn every 5xx into a crash in the handler.
        logger.error(
            "api error", extra={"error_code": exc.code, "error_message": exc.message}
        )
    return api.create_response(request, exc.to_dict(), status=exc.status_code)


@api.exception_handler(NinjaValidationError)
def handle_validation_error(request, exc: NinjaValidationError):
    """Flatten pydantic's error list into the project's error envelope."""
    details = [
        {
            "field": ".".join(str(part) for part in error.get("loc", [])[1:]) or "body",
            "message": error.get("msg", ""),
            "type": error.get("type", ""),
        }
        for error in exc.errors
    ]
    return api.create_response(
        request,
        {
            "error": {
                "code": "validation_error",
                "message": "Request payload is invalid",
                "details": details,
            }
        },
        status=422,
    )


@api.exception_handler(NinjaAuthError)
def handle_auth_error(request, exc: NinjaAuthError):
    return api.create_response(
        request,
        {"error": {"code": "unauthenticated", "message": "Authentication required"}},
        status=401,
    )


@api.exception_handler(Http404)
def handle_not_found(request, exc: Http404):
    return api.create_response(
        request,
        {"error": {"code": "not_found", "message": "Resource not found"}},
        status=404,
    )


@api.exception_handler(DatabaseError)
def handle_database_error(request, exc: DatabaseError):
    logger.exception("database error")
    return api.create_response(
        request,
        {
            "error": {
                "code": "database_unavailable",
                "message": "The database is temporarily unavailable",
            }
        },
        status=503,
    )


@api.exception_handler(Exception)
def handle_unexpected(request, exc: Exception):
    logger.exception("unhandled API exception")
    if settings.DEBUG:
        raise exc
    return api.create_response(
        request,
        {"error": {"code": "internal_error", "message": "An unexpected error occurred"}},
        status=500,
    )
