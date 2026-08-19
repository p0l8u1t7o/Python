"""Schemas and pagination shared by all API routers."""

from __future__ import annotations

import datetime as dt
from typing import Any, Generic, TypeVar

from ninja import Schema
from pydantic import Field

T = TypeVar("T")


class ErrorDetail(Schema):
    code: str
    message: str
    details: Any | None = None


class ErrorResponse(Schema):
    error: ErrorDetail


class OkResponse(Schema):
    ok: bool = True
    message: str = ""


class Page(Schema, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class PageParams(Schema):
    limit: int = Field(default=50, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


def paginate(queryset, params: PageParams) -> dict[str, Any]:
    """Offset pagination with a single COUNT - fine for admin-scale listings."""
    total = queryset.count()
    items = list(queryset[params.offset : params.offset + params.limit])
    return {
        "items": items,
        "total": total,
        "limit": params.limit,
        "offset": params.offset,
    }


class TimeRangeParams(Schema):
    """Common ``?start=&end=`` filter for time series and log endpoints."""

    start: dt.datetime | None = None
    end: dt.datetime | None = None

    def normalized(self, *, default_window_seconds: int = 3600) -> tuple[
        dt.datetime, dt.datetime
    ]:
        from apps.core.timeutils import now

        end = self.end or now()
        start = self.start or (end - dt.timedelta(seconds=default_window_seconds))
        if start >= end:
            from apps.core.errors import ValidationError

            raise ValidationError("start must be earlier than end", code="invalid_range")
        if start.tzinfo is None:
            start = start.replace(tzinfo=dt.timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=dt.timezone.utc)
        return start, end


class GeoPoint(Schema):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
