"""Resolving which storage plan actually drives a site.

Plans bind per site, but sites form a tree, and the natural reading of a
binding on a parent is "this covers my children unless they say otherwise".
So the *effective* plan is: the site's own binding, else the nearest
ancestor's. A child that needs different behaviour binds its own plan and
thereby overrides; a child with no opinion follows the facility it belongs
to. Tariffs ride along - a plan carries its tariff, so tariff inheritance is
this same rule seen from the billing side.
"""

from __future__ import annotations

from apps.ems.models import StoragePlan

#: More levels than any sane site tree; a cycle guard, not a limit.
MAX_TREE_DEPTH = 20


def effective_plan(site) -> tuple[StoragePlan | None, object | None]:
    """The plan driving ``site`` and the site the binding actually lives on.

    Returns ``(plan, source_site)``; ``source_site is site`` means a direct
    binding, anything else means inherited. Walks the parent chain with one
    query per level - site trees are shallow and the callers are per-site
    paths, not bulk sweeps (those use :func:`effective_plan_map`).
    """
    current = site
    for _ in range(MAX_TREE_DEPTH):
        if current.storage_plan_id is not None:
            return current.storage_plan, current
        if current.parent_id is None:
            return None, None
        current = current.parent
    return None, None


def effective_plan_map(organization) -> dict:
    """site_id -> (plan, source_site_id) for a whole tenant, in three queries.

    The bulk companion to :func:`effective_plan`, for the dispatch sweep and
    the roll-ups, where walking parents one query at a time would multiply.
    """
    from apps.devices.models import Site

    rows = list(
        Site.objects.filter(organization=organization, deleted_at__isnull=True)
        .values("id", "parent_id", "storage_plan_id")
    )
    plans = {
        plan.pk: plan
        for plan in StoragePlan.objects.filter(
            organization=organization
        ).select_related("tariff")
    }
    parent_of = {row["id"]: row["parent_id"] for row in rows}
    own = {row["id"]: row["storage_plan_id"] for row in rows}

    result: dict = {}
    for site_id in own:
        current = site_id
        for _ in range(MAX_TREE_DEPTH):
            plan_id = own.get(current)
            if plan_id is not None and plan_id in plans:
                result[site_id] = (plans[plan_id], current)
                break
            parent = parent_of.get(current)
            if parent is None:
                break
            current = parent
    return result
