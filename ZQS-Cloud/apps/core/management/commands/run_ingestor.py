"""Start the MQTT ingestion service."""

from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Subscribe to device MQTT topics and forward validated data to the bus."

    def handle(self, *args, **options):
        from services.ingestor.main import run

        run()
