"""Schemas and pagination shared by all API routers."""

from __future__ import annotations

import datetime as dt
from typing import ClassVar
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

    #: How far past "now" a defaulted window reaches. See :meth:`normalized`.
    #: ClassVar, or pydantic would take it for a query parameter.
    DEFAULT_END_GRACE: ClassVar[dt.timedelta] = dt.timedelta(seconds=1)

    def normalized(self, *, default_window_seconds: int = 3600) -> tuple[
        dt.datetime, dt.datetime
    ]:
        """``(start, end)`` for a half-open ``[start, end)`` filter.

        Half-open so consecutive explicit windows tile without counting a
        sample twice.

        A **defaulted** end reaches slightly past the present, which is not the
        same fudge it looks like. With an exclusive bound of exactly ``now()``,
        a row written in the same clock tick as the request is invisible - and
        clock ticks are not small: Windows resolves to roughly 15 ms, so
        "everything up to now" routinely dropped the newest row on the way in.
        The half-open convention earns its keep when one window has a successor
        to tile against; a "latest" window has none, so excluding the present
        instant costs data and buys nothing.
        """
        from apps.core.timeutils import now

        end = self.end or (now() + self.DEFAULT_END_GRACE)
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
