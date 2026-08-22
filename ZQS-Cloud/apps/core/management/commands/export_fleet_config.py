r"""Write the simulator's fleet description from what the platform has registered.

    manage.py export_fleet_config                      # -> simulator/fleet.json
    manage.py export_fleet_config --out C:\site\fleet.json --site taichung

The file is the whole contract with the standalone simulator: broker, group
id, gateways and their devices with physics sizing. Edit it freely - the
simulator never reads this database.
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import Organization
from services.harness.fleet import export_fleet_config
from simulator import config as cfg


class Command(BaseCommand):
    help = "Export the registered gateways and devices as the simulator's fleet.json."

    def add_arguments(self, parser):
        parser.add_argument("--organization", default="", help="Organization slug (default: first).")
        parser.add_argument("--site", action="append", default=[], help="Site code(s); default all.")
        parser.add_argument("--out", default=str(cfg.DEFAULT_PATH), help="Output path.")
        parser.add_argument("--host", default="", help="Broker host to write (default: this deployment's).")
        parser.add_argument("--port", type=int, default=0, help="Broker port to write.")

    def handle(self, *args, **options):
        organization = (
            Organization.objects.filter(slug=options["organization"]).first()
            if options["organization"]
            else Organization.objects.order_by("created_at").first()
        )
        if organization is None:
            raise CommandError("No organization found; seed the database first.")
        config = export_fleet_config(organization, only_sites=set(options["site"]) or None)
        if options["host"]:
            config.broker.host = options["host"]
        if options["port"]:
            config.broker.port = options["port"]
        path = cfg.save(config, Path(options["out"]))
        devices = sum(len(g.devices) for g in config.gateways)
        self.stdout.write(self.style.SUCCESS(
            f"wrote {path}: {len(config.gateways)} gateway(s), {devices} device(s), "
            f"broker {config.broker.host}:{config.broker.port}, group {config.group_id}"
        ))
