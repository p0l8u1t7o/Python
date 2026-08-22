"""Standalone device simulator.

Runs as an independent MQTT client, the way a vendor's gateway would: it
knows the broker, a group id, and the gateways/devices it should be - from a
JSON file - and nothing about the platform's database. The platform is only
ever reached over MQTT. ``manage.py export_fleet_config`` writes that JSON
from what the platform has registered; a vendor could just as well write it
by hand.

The Sparkplug codec (``services.sparkplug``) is shared with the platform so
the wire format cannot drift. It reads a few Django settings for decode
limits and topic helpers, so this package configures a minimal settings
object when none is present - no apps, no database, no ORM.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def ensure_settings() -> None:
    """Configure the minimum the codec needs, unless Django is already set up."""
    from django.conf import settings

    # Inside the platform (DJANGO_SETTINGS_MODULE set) the real settings win,
    # whether or not they have been touched yet.
    if settings.configured or os.environ.get("DJANGO_SETTINGS_MODULE"):
        return
    settings.configure(
        USE_TZ=True,
        TIME_ZONE="UTC",
        INGEST={"MAX_PAYLOAD_BYTES": 256 * 1024, "MAX_METRICS_PER_MESSAGE": 512},
        SPARKPLUG={"HOST_ID": os.environ.get("SPARKPLUG_HOST_ID", "zqs-cloud")},
        MQTT={
            "USE_SHARED_SUBSCRIPTION": False,
            "SHARED_SUBSCRIPTION_GROUP": "zqs-ingestor",
            "QOS_UPLINK": 0,
            "QOS_DOWNLINK": 1,
        },
        LOGGING_CONFIG=None,
    )


ensure_settings()
