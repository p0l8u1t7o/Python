"""Start a queue worker."""

from __future__ import annotations

import socket
import os

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Consume the ingest queue: persist telemetry, evaluate rules, notify."

    def add_arguments(self, parser):
        parser.add_argument(
            "--name",
            default="",
            help=(
                "Consumer name; must be unique per worker process so the broker "
                "can track each one's pending messages. Defaults to host-pid."
            ),
        )

    def handle(self, *args, **options):
        from services.worker.main import run

        name = options["name"] or f"{socket.gethostname()}-{os.getpid()}"
        run(name=name)
