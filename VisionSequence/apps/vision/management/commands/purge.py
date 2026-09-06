"""Housekeeping: drop what the retention settings say is past its keep-by date.

    manage.py purge --dry-run
    manage.py purge --runs 30 --archive-days 90 --archive-gb 20 --audit 730

Run it from a scheduled task if you want a predictable window; the server also prunes as it writes,
so a healthy installation never actually needs this — it is for catching up after a long run with
looser settings, or for freeing space in a hurry.
"""

from __future__ import annotations

import datetime as dt

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.core import audit
from apps.vision import archive, retention
from apps.vision.models import Flow, FlowRun, FlowVersion
from apps.vision.versions import prune as prune_versions


class Command(BaseCommand):
    help = "Delete runs, archived images, audit entries and flow snapshots past their retention."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--runs", type=int, default=None, help="Keep run detail for this many days (0 = keep)")
        parser.add_argument("--archive-days", type=int, default=None)
        parser.add_argument("--archive-gb", type=float, default=None)
        parser.add_argument("--audit", type=int, default=None, help="Keep audit entries for this many days (0 = keep)")
        parser.add_argument("--measurements", type=int, default=None, help="Keep SPC measurement rows for this many days (0 = keep)")
        parser.add_argument("--backups", type=int, default=None, help="Keep this many backup zips and pre-restore database copies")
        parser.add_argument("--pictures", action="store_true", help="Also delete fixed pictures no flow, version or template refers to")

    def handle(self, *args, **options):
        cfg = retention.effective()  # 設定頁改的保存時限是唯一事實來源（沒有列時＝.env／出廠值）
        dry = options["dry_run"]
        runs_days = cfg["run_days"] if options["runs"] is None else options["runs"]
        audit_days = cfg["audit_days"] if options["audit"] is None else options["audit"]

        if runs_days and runs_days > 0:
            cutoff = timezone.now() - dt.timedelta(days=int(runs_days))
            doomed = FlowRun.objects.filter(started_at__lt=cutoff)
            n = doomed.count()
            self.stdout.write(f"runs older than {runs_days}d: {n}")
            if n and not dry:
                for run_id, images in doomed.values_list("id", "images").iterator(chunk_size=500):
                    archive.drop_run(run_id.hex, images)
                doomed.delete()
        else:
            self.stdout.write("runs: keeping everything (0 = no age limit)")

        before = archive.stats()
        self.stdout.write(f"archive: {before['files']} files, {before['bytes'] / (1 << 20):.1f} MB")
        if not dry:
            result = archive.purge(days=options["archive_days"], max_bytes=int(options["archive_gb"] * (1 << 30)) if options["archive_gb"] is not None else None)
            self.stdout.write(f"  removed {result['removed']} files, freed {result['freed'] / (1 << 20):.1f} MB")

        if audit_days and audit_days > 0:
            self.stdout.write(f"audit older than {audit_days}d: {audit.purge(days=0) if dry else audit.purge(days=int(audit_days))} removed")
        meas_days = cfg["measurement_days"] if options["measurements"] is None else options["measurements"]
        if meas_days and meas_days > 0:
            from apps.vision.models import MeasurementLog

            doomed_m = MeasurementLog.objects.filter(ts__lt=timezone.now() - dt.timedelta(days=int(meas_days)))
            n = doomed_m.count()
            self.stdout.write(f"measurements older than {meas_days}d: {n}")
            if n and not dry:
                doomed_m.delete()
        else:
            self.stdout.write("measurements: keeping everything (0 = no age limit)")
        snapshots = 0
        for flow in Flow.objects.all():
            snapshots += 0 if dry else prune_versions(flow)
        self.stdout.write(f"flow snapshots removed: {snapshots} (kept {FlowVersion.objects.count()})")

        keep_backups = cfg["backup_keep"] if options["backups"] is None else options["backups"]
        files = retention.backup_files()
        self.stdout.write(f"backups: {len(files)} files, {sum(st.st_size for _p, st in files) / (1 << 20):.1f} MB (keeping {keep_backups} of each kind)")
        if not dry:
            self.stdout.write(f"  removed {retention.purge_backups(int(keep_backups))} files")

        if options["pictures"]:
            from apps.vision import fixed_images

            orphans = fixed_images.orphans()
            self.stdout.write(f"fixed pictures with nothing referring to them: {len(orphans)}")
            if not dry:
                self.stdout.write(f"  removed {retention.purge_orphan_pictures(min_age_s=0)} files")
        self.stdout.write(self.style.SUCCESS("Dry run — nothing was deleted." if dry else "Purge complete."))
