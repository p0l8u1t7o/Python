"""平台服務組裝：設定、資料庫、授權、工作佇列、資料夾監看、維護、日誌"""
import logging
import logging.handlers
import os
import threading
import time

from ..ingest.watcher import FolderWatcher
from ..store.db import Database
from .jobs import JobQueue
from .license import LicenseManager, collect_hardware
from .maintenance import Maintenance


def setup_logging(settings):
    os.makedirs(settings.logs_dir, exist_ok=True)
    root = logging.getLogger("xrayvision")
    if any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
        return
    h = logging.handlers.RotatingFileHandler(os.path.join(settings.logs_dir, "xrayvision.log"),
                                             maxBytes=10 << 20, backupCount=10, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(h)
    root.setLevel(logging.INFO)


class Platform:
    """
    enforce_license=False 只供開發與自動測試使用 (程式呼叫參數，不提供設定檔或命令列選項)。
    """

    def __init__(self, settings, workers=None, watch=True, enforce_license=True, hardware_collector=collect_hardware):
        settings.ensure_dirs()
        setup_logging(settings)
        self.settings = settings
        self.db = Database(settings.db_path)
        self.enforce_license = enforce_license
        self.license = LicenseManager(settings.data_dir, self.db, collector=hardware_collector)
        self._lic_cache = (0.0, None)
        self._lic_lock = threading.Lock()
        self.queue = JobQueue(settings, lambda: self.db, workers, can_run=self.analysis_allowed,
                              module_allowed=self.module_allowed)
        self.watcher = FolderWatcher(settings, lambda: self.db, on_import=self.queue.notify,
                                     can_import=self.analysis_allowed) if watch else None
        self.maintenance = Maintenance(settings, lambda: self.db)

    # ---- 授權 (快取 30 秒，避免每個請求都重新檢查) ----
    def license_status(self, refresh=False):
        with self._lic_lock:
            t, st = self._lic_cache
            if refresh or st is None or time.time() - t > 30:
                st = self.license.status()
                self._lic_cache = (time.time(), st)
            return st

    def analysis_allowed(self):
        return (not self.enforce_license) or self.license_status()["analysis_allowed"]

    def module_allowed(self, module_id):
        return (not self.enforce_license) or self.license.module_allowed(module_id)

    def start(self):
        self.queue.start()
        if self.watcher:
            self.watcher.start()
        self.maintenance.start()
        logging.getLogger("xrayvision").info("platform started: %s", self.settings.data_dir)

    def stop(self):
        self.maintenance.stop()
        if self.watcher:
            self.watcher.stop()
        self.queue.stop()
        logging.getLogger("xrayvision").info("platform stopped")
