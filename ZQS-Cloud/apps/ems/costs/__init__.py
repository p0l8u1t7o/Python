"""Pluggable cost models, keyed by name.

Importing this package registers every built-in model. Adding one is a new
module here plus an import below - no change to the aggregator, the API or the
database schema.
"""

from apps.ems.costs.base import (  # noqa: F401
    ROLE_DEFAULTS,
    CostContext,
    CostResult,
    UnknownCostModel,
    available,
    compute,
    get,
    model_for,
    register,
)

# Imported for their registration side effect; order is irrelevant.
from apps.ems.costs import battery, diesel, grid  # noqa: F401,E402

__all__ = [
    "ROLE_DEFAULTS",
    "CostContext",
    "CostResult",
    "UnknownCostModel",
    "available",
    "compute",
    "get",
    "model_for",
    "register",
]
