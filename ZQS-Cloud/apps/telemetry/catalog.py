"""Cached metric definitions.

Used by the worker to flag implausible readings and by the API to label series.
Definitions resolve tenant-first, then fall back to the built-in catalogue.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass

from apps.core.logging import get_logger

logger = get_logger("telemetry.catalog")


@dataclass(frozen=True, slots=True)
class MetricDef:
    key: str
    display_name: str
    unit: str
    value_type: str
    kind: str
    aggregation: str
    decimals: int
    min_value: float | None
    max_value: float | None
    translations: dict
    category: str

    def is_plausible(self, value: float | None) -> bool:
        if value is None:
            return True
        if self.min_value is not None and value < self.min_value:
            return False
        if self.max_value is not None and value > self.max_value:
            return False
        return True

    def label(self, language: str = "en") -> str:
        return (self.translations or {}).get(language) or self.display_name or self.key


class MetricCatalog:
    def __init__(self, ttl_seconds: int = 60) -> None:
        self.ttl = ttl_seconds
        self._by_org: dict[uuid.UUID | None, dict[str, MetricDef]] = {}
        self._loaded_at = 0.0
        self._lock = threading.RLock()

    def refresh(self, *, force: bool = False) -> None:
        with self._lock:
            if not force and (time.monotonic() - self._loaded_at) < self.ttl:
                return
            self._load()

    def _load(self) -> None:
        from apps.telemetry.models import Metric

        index: dict[uuid.UUID | None, dict[str, MetricDef]] = {}
        for row in Metric.objects.filter(is_active=True).values(
            "organization_id",
            "key",
            "display_name",
            "unit",
            "value_type",
            "kind",
            "aggregation",
            "decimals",
            "min_value",
            "max_value",
            "translations",
            "category",
        ):
            index.setdefault(row["organization_id"], {})[row["key"]] = MetricDef(
                key=row["key"],
                display_name=row["display_name"],
                unit=row["unit"],
                value_type=row["value_type"],
                kind=row["kind"],
                aggregation=row["aggregation"],
                decimals=row["decimals"],
                min_value=row["min_value"],
                max_value=row["max_value"],
                translations=row["translations"] or {},
                category=row["category"],
            )
        self._by_org = index
        self._loaded_at = time.monotonic()
        logger.debug("metric catalog loaded", extra={"tenants": len(index)})

    def get(self, organization_id: uuid.UUID, metric_key: str) -> MetricDef | None:
        self.refresh()
        with self._lock:
            tenant = self._by_org.get(organization_id)
            if tenant is not None and metric_key in tenant:
                return tenant[metric_key]
            return self._by_org.get(None, {}).get(metric_key)

    def for_organization(self, organization_id: uuid.UUID) -> dict[str, MetricDef]:
        """Built-ins merged with tenant definitions, tenant wins on conflict."""
        self.refresh()
        with self._lock:
            merged = dict(self._by_org.get(None, {}))
            merged.update(self._by_org.get(organization_id, {}))
            return merged

    def invalidate(self) -> None:
        with self._lock:
            self._loaded_at = 0.0


_catalog: MetricCatalog | None = None
_lock = threading.Lock()


def get_catalog() -> MetricCatalog:
    global _catalog
    if _catalog is None:
        with _lock:
            if _catalog is None:
                _catalog = MetricCatalog()
    return _catalog
