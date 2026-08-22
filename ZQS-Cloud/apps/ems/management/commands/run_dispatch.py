"""Execute scheduled dispatch windows: work out each site's target and issue it.

Run from ``run_scheduler`` on the normal cycle, or by hand with ``--dry-run``
to see what the engine would do without touching any hardware.

Safe to run repeatedly: the engine only issues a command when the target has
actually moved, so an extra invocation is a no-op rather than a duplicate
setpoint.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.accounts.models import Organization
from apps.ems.dispatch import run_organization


class Command(BaseCommand):
    help = "Turn active dispatch windows into device commands."

    def add_arguments(self, parser):
        parser.add_argument("--organization", default="", help="Slug; blank means all.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the decisions without sending anything.",
        )

    def handle(self, *args, **options):
        organizations = Organization.objects.filter(is_active=True)
        if options["organization"]:
            organizations = organizations.filter(slug=options["organization"])

        issued = 0
        for organization in organizations:
            decisions = run_organization(organization, dry_run=options["dry_run"])
            for decision in decisions:
                label = (
                    decision.device.device_id if decision.device else str(decision.site_id)
                )
                if decision.power_w is None:
                    self.stdout.write(f"{label}: idle ({decision.reason})")
                    continue
                if decision.skipped:
                    self.stdout.write(
                        f"{label}: {decision.power_w:.0f} W not sent ({decision.skipped})"
                    )
                    continue
                issued += 1
                note = (
                    f" [was {decision.clamped_from_w:.0f} W]"
                    if decision.clamped_from_w is not None
                    else ""
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"{label}: {decision.power_w:.0f} W - {decision.reason}{note}"
                    )
                )

        self.stdout.write(self.style.SUCCESS(f"issued {issued} command(s)"))
