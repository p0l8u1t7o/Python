"""Fixed-window rate limiting backed by the Django cache.

Good enough to blunt credential stuffing and runaway clients. Swap
``CACHE_BACKEND=redis`` for a limit shared across API replicas - with the
default locmem cache the limit is per process.
"""

from __future__ import annotations

from django.core.cache import cache

from apps.core.errors import RateLimited

KEY_PREFIX = "throttle:"


def throttle(request, *, bucket: str, limit: int, window_s: int) -> None:
    """Raise :class:`RateLimited` once ``limit`` hits occur inside the window."""
    key = f"{KEY_PREFIX}{bucket}"
    try:
        added = cache.add(key, 1, timeout=window_s)
        count = 1 if added else cache.incr(key)
    except ValueError:
        # Key expired between add() and incr(); treat as a fresh window.
        cache.set(key, 1, timeout=window_s)
        count = 1

    if count > limit:
        raise RateLimited(
            "Too many requests; slow down",
            details={"limit": limit, "window_seconds": window_s},
        )


def reset(bucket: str) -> None:
    cache.delete(f"{KEY_PREFIX}{bucket}")
