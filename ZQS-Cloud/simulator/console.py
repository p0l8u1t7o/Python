# -*- coding: utf-8 -*-
"""ZQS 設備模擬主控台 - 獨立的 MQTT 設備模擬器。

和平台**完全解耦**:不讀資料庫、不載入平台程式,只靠一份 JSON 設定檔
(``simulator/fleet.json``,由 ``manage.py export_fleet_config`` 匯出,或自己手寫)
知道要連哪個 broker、自己是哪些閘道器與設備。之後的一切都只走 MQTT
(Sparkplug B):上線宣告、遙測上傳、接收命令、回覆、離線。

畫面:
* Broker IP / Port / 帳密,可改後重新連線
* 閘道器清單(上線/離線/已發布筆數),全部或選取上線/離線
* **設備即時量測值**:點選設備,右側表格每秒更新目前送出的每個量測值
* 手動測試:事件、警報觸發/解除、手動逐步回覆命令
* 收發日誌

執行::

    .\\scripts\\sim-console.ps1
    .venv\\Scripts\\python.exe -m simulator.console [-c path\\to\\fleet.json]
"""

from __future__ import annotations

import argparse
import queue
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import simulator  # noqa: E402,F401  - configures the codec's settings
from simulator import config as cfg  # noqa: E402
from simulator.gateway import GatewayRunner  # noqa: E402
from simulator.physics import METRIC_UNITS  # noqa: E402

import tkinter as tk  # noqa: E402
from tkinter import filedialog, messagebox, simpledialog, ttk  # noqa: E402

#: 電池目前的運作模式（physics.mode）。
MODE_LABELS = {"normal": "正常", "expired": "設定點過期", "watchdog": "斷線降級", "island": "孤島供電"}
EVENT_LEVELS = ("info", "notice", "warning", "error", "critical")
ALARM_SEVERITIES = ("info", "warning", "major", "critical")


class App:
    def __init__(self, config_path: Path) -> None:
        self.root = tk.Tk()
        self.root.title("ZQS 設備模擬主控台")
        self.root.geometry("1180x760")

        self.config_path = config_path
        self.fleet = cfg.FleetConfig()
        self.runners: list[GatewayRunner] = []
        self.log_queue: "queue.Queue[str]" = queue.Queue()

        self._build()
        self._load_config(config_path)
        self._poll()

    # ---- logging (thread-safe) ------------------------------------------
    def _log_bg(self, message: str) -> None:
        self.log_queue.put(time.strftime("%H:%M:%S ") + message)

    def _poll(self) -> None:
        try:
            while True:
                line = self.log_queue.get_nowait()
                self.log.configure(state="normal")
                self.log.insert("end", line + "\n")
                self.log.see("end")
                self.log.configure(state="disabled")
        except queue.Empty:
            pass
        for runner in self.runners:
            try:
                while True:
                    command = runner.pending_commands.get_nowait()
                    self.commands.insert("", "end", values=(
                        command["node_id"], command["device_id"], command["name"],
                        command["command_id"], str(command["params"])))
            except queue.Empty:
                pass
        self._refresh_status()
        self._refresh_values()
        self.root.after(500, self._poll)

    # ---- UI --------------------------------------------------------------
    def _build(self) -> None:
        pad = {"padx": 6, "pady": 3}

        # Broker + config
        top = ttk.LabelFrame(self.root, text="MQTT Broker 與設定檔")
        top.pack(fill="x", **pad)
        ttk.Label(top, text="IP / 主機:").grid(row=0, column=0, sticky="w", **pad)
        self.host_var = tk.StringVar(value="127.0.0.1")
        ttk.Entry(top, textvariable=self.host_var, width=18).grid(row=0, column=1, sticky="w", **pad)
        ttk.Label(top, text="Port:").grid(row=0, column=2, sticky="w", **pad)
        self.port_var = tk.StringVar(value="1883")
        ttk.Entry(top, textvariable=self.port_var, width=6).grid(row=0, column=3, sticky="w", **pad)
        ttk.Label(top, text="帳號:").grid(row=0, column=4, sticky="w", **pad)
        self.user_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.user_var, width=16).grid(row=0, column=5, sticky="w", **pad)
        ttk.Label(top, text="密碼:").grid(row=0, column=6, sticky="w", **pad)
        self.pass_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.pass_var, width=16, show="•").grid(row=0, column=7, sticky="w", **pad)
        ttk.Label(top, text="Group ID:").grid(row=0, column=8, sticky="w", **pad)
        self.group_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.group_var, width=14).grid(row=0, column=9, sticky="w", **pad)

        ttk.Label(top, text="設定檔:").grid(row=1, column=0, sticky="w", **pad)
        self.config_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.config_var, width=60, state="readonly").grid(row=1, column=1, columnspan=5, sticky="we", **pad)
        ttk.Button(top, text="開啟…", command=self._pick_config).grid(row=1, column=6, **pad)
        ttk.Button(top, text="重新載入", command=lambda: self._load_config(self.config_path)).grid(row=1, column=7, **pad)
        ttk.Button(top, text="儲存 broker 設定", command=self._save_config).grid(row=1, column=8, columnspan=2, sticky="w", **pad)

        # Options + fleet
        mid = ttk.LabelFrame(self.root, text="閘道器(Sparkplug 邊緣節點)")
        mid.pack(fill="x", **pad)
        bar = ttk.Frame(mid)
        bar.pack(fill="x", **pad)
        ttk.Label(bar, text="上傳間隔(秒):").pack(side="left")
        self.interval_var = tk.StringVar(value="5")
        ttk.Spinbox(bar, from_=1, to=60, textvariable=self.interval_var, width=4).pack(side="left", padx=(0, 12))
        self.faults_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="自動注入事件/警報", variable=self.faults_var).pack(side="left", padx=(0, 12))
        self.autonomous_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="電池自主削峰(未收到設定點時)", variable=self.autonomous_var).pack(side="left", padx=(0, 18))
        self.all_on = ttk.Button(bar, text="全部上線", command=self.connect_all)
        self.all_on.pack(side="left", padx=(0, 6))
        self.all_off = ttk.Button(bar, text="全部離線", command=self.disconnect_all, state="disabled")
        self.all_off.pack(side="left", padx=(0, 18))
        ttk.Button(bar, text="選取上線", command=self.connect_selected).pack(side="left", padx=(0, 6))
        ttk.Button(bar, text="選取離線", command=self.disconnect_selected).pack(side="left")
        # W6：停電模擬——關口電壓歸零，邊緣自己轉孤島；平台端應偵測到停電。
        ttk.Button(bar, text="選取停電/復電", command=self.toggle_outage_selected).pack(side="left", padx=(18, 0))

        self.fleet_view = ttk.Treeview(mid, columns=("node", "site", "devices", "status", "mode", "published"), show="headings", height=6)
        for key, label, width in (("node", "閘道器 (node_id)", 170), ("site", "場域", 160), ("devices", "設備", 440),
                                  ("status", "狀態", 90), ("mode", "電池模式", 110), ("published", "已發布", 70)):
            self.fleet_view.heading(key, text=label)
            self.fleet_view.column(key, width=width, anchor="w")
        self.fleet_view.pack(fill="x", padx=4, pady=4)

        lower = ttk.Frame(self.root)
        lower.pack(fill="both", expand=True, **pad)

        # Device values
        values = ttk.LabelFrame(lower, text="設備即時量測值")
        values.pack(side="left", fill="both", expand=True, padx=(0, 6))
        row = ttk.Frame(values)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="設備:").pack(side="left")
        self.target_var = tk.StringVar()
        self.target_pick = ttk.Combobox(row, textvariable=self.target_var, width=40, state="readonly")
        self.target_pick.pack(side="left", padx=(4, 0))
        self.values_at = ttk.Label(row, text="")
        self.values_at.pack(side="left", padx=10)
        self.values_view = ttk.Treeview(values, columns=("metric", "value", "unit"), show="headings", height=10)
        for key, label, width in (("metric", "量測項", 220), ("value", "數值（雙擊覆寫）", 150), ("unit", "單位", 60)):
            self.values_view.heading(key, text=label)
            self.values_view.column(key, width=width, anchor="w")
        self.values_view.pack(fill="both", expand=True, padx=4, pady=4)
        self.values_view.tag_configure("override", foreground="#b45309")
        self.values_view.bind("<Double-1>", self._override_selected)
        ov = ttk.Frame(values)
        ov.pack(fill="x", **pad)
        ttk.Button(ov, text="覆寫選取值", command=self._override_selected).pack(side="left")
        ttk.Button(ov, text="解除選取覆寫", command=self._clear_selected_override).pack(side="left", padx=4)
        ttk.Button(ov, text="解除此設備全部覆寫", command=self._clear_device_overrides).pack(side="left", padx=4)
        ttk.Label(ov, text="★ = 強制上傳值", foreground="#b45309").pack(side="right")

        # 場域物理量鎖定：把負載 / PV / 電池 / SOC 釘成固定數，關掉雜訊，
        # 讓雲端算出來的 kWh、電費、需量可以用手算對帳。
        lock = ttk.LabelFrame(values, text="場域物理量鎖定（驗證雲端計算）")
        lock.pack(fill="x", padx=4, pady=(2, 4))
        self.lock_vars = {key: tk.StringVar() for key in ("load_kw", "pv_kw", "battery_kw", "soc")}
        for col, (key, label) in enumerate((("load_kw", "負載 kW"), ("pv_kw", "PV kW"),
                                            ("battery_kw", "電池 kW(+放電)"), ("soc", "SOC %"))):
            ttk.Label(lock, text=label).grid(row=0, column=col * 2, sticky="w", padx=(6, 2), pady=2)
            ttk.Entry(lock, textvariable=self.lock_vars[key], width=9).grid(row=0, column=col * 2 + 1, padx=(0, 6))
        self.deterministic_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(lock, text="固定值(關閉隨機抖動)", variable=self.deterministic_var,
                        command=self._apply_deterministic).grid(row=1, column=0, columnspan=4, sticky="w", padx=6)
        ttk.Button(lock, text="套用並立即上傳", command=self._apply_lock).grid(row=1, column=4, columnspan=2, sticky="e", padx=4)
        ttk.Button(lock, text="全部解除", command=self._clear_lock).grid(row=1, column=6, columnspan=2, sticky="w", padx=4)
        ttk.Label(lock, text="空白 = 不鎖定；電網 = 負載 − PV − 電池，雲端 kWh = kW × 時數",
                  foreground="#6b7280").grid(row=2, column=0, columnspan=8, sticky="w", padx=6, pady=(0, 4))

        # Tests + commands + log
        right = ttk.Frame(lower)
        right.pack(side="left", fill="both", expand=True)

        test = ttk.LabelFrame(right, text="手動測試(對上方選取的設備)")
        test.pack(fill="x")
        ev = ttk.Frame(test)
        ev.pack(fill="x", **pad)
        ttk.Label(ev, text="事件").pack(side="left")
        self.event_code = tk.StringVar(value="E0231")
        self.event_level = tk.StringVar(value="error")
        self.event_message = tk.StringVar(value="模擬事件")
        ttk.Entry(ev, textvariable=self.event_code, width=7).pack(side="left", padx=3)
        ttk.Combobox(ev, textvariable=self.event_level, values=EVENT_LEVELS, width=8, state="readonly").pack(side="left", padx=3)
        ttk.Entry(ev, textvariable=self.event_message, width=18).pack(side="left", padx=3)
        ttk.Button(ev, text="送出", command=self.send_event).pack(side="left", padx=3)
        al = ttk.Frame(test)
        al.pack(fill="x", **pad)
        ttk.Label(al, text="警報").pack(side="left")
        self.alarm_code = tk.StringVar(value="A0007")
        self.alarm_severity = tk.StringVar(value="major")
        self.alarm_message = tk.StringVar(value="PCS 過溫(模擬)")
        ttk.Entry(al, textvariable=self.alarm_code, width=7).pack(side="left", padx=3)
        ttk.Combobox(al, textvariable=self.alarm_severity, values=ALARM_SEVERITIES, width=8, state="readonly").pack(side="left", padx=3)
        ttk.Entry(al, textvariable=self.alarm_message, width=18).pack(side="left", padx=3)
        ttk.Button(al, text="觸發", command=lambda: self.send_alarm(True)).pack(side="left", padx=2)
        ttk.Button(al, text="解除", command=lambda: self.send_alarm(False)).pack(side="left", padx=2)

        cmd = ttk.LabelFrame(right, text="平台命令")
        cmd.pack(fill="x", pady=(6, 0))
        self.auto_ack_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(cmd, text="自動執行並回覆(取消即可手動回覆)", variable=self.auto_ack_var,
                        command=self._toggle_auto_ack).pack(anchor="w", padx=4)
        self.commands = ttk.Treeview(cmd, columns=("node", "device", "name", "id", "params"), show="headings", height=4)
        for key, label, width in (("node", "閘道器", 100), ("device", "設備", 120), ("name", "命令", 120),
                                  ("id", "ID", 80), ("params", "參數", 140)):
            self.commands.heading(key, text=label)
            self.commands.column(key, width=width)
        self.commands.pack(fill="x", padx=4, pady=2)
        answer = ttk.Frame(cmd)
        answer.pack(fill="x", padx=4, pady=2)
        for label, status in (("接受", "accepted"), ("成功", "succeeded"), ("失敗", "failed")):
            ttk.Button(answer, text=label, command=lambda s=status: self.answer(s)).pack(side="left", padx=2)

        logf = ttk.LabelFrame(right, text="收發日誌")
        logf.pack(fill="both", expand=True, pady=(6, 0))
        self.log = tk.Text(logf, height=8, state="disabled", wrap="none", font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, padx=4, pady=4)

    # ---- config ------------------------------------------------------------
    def _pick_config(self) -> None:
        chosen = filedialog.askopenfilename(title="選擇 fleet.json", filetypes=[("JSON", "*.json")],
                                            initialdir=str(self.config_path.parent))
        if chosen:
            self._load_config(Path(chosen))

    def _load_config(self, path: Path) -> None:
        if any(r.is_alive() for r in self.runners):
            self.disconnect_all()
            self._join_all(timeout=6)
        self.config_path = Path(path)
        self.config_var.set(str(self.config_path))
        try:
            self.fleet = cfg.load(self.config_path)
        except FileNotFoundError:
            self.fleet = cfg.FleetConfig()
            self._log_bg(f"找不到設定檔 {self.config_path};請在平台端執行 manage.py export_fleet_config,或自行撰寫")
        except Exception as exc:  # noqa: BLE001
            self.fleet = cfg.FleetConfig()
            messagebox.showerror("設定檔錯誤", str(exc))
        self.host_var.set(self.fleet.broker.host)
        self.port_var.set(str(self.fleet.broker.port))
        self.user_var.set(self.fleet.broker.username)
        self.pass_var.set(self.fleet.broker.password)
        self.group_var.set(self.fleet.group_id)
        self.runners = [self._new_runner(spec) for spec in self.fleet.gateways]
        self.fleet_view.delete(*self.fleet_view.get_children())
        for runner in self.runners:
            self.fleet_view.insert("", "end", iid=runner.node_id, values=(
                runner.node_id, runner.site_name, ", ".join(d.device_id for d in runner.devices), "離線", 0))
        self._log_bg(f"已載入 {len(self.runners)} 台閘道器、{sum(len(r.devices) for r in self.runners)} 台設備;全部離線")
        self._refresh_targets()

    def _broker(self) -> cfg.BrokerConfig:
        try:
            port = int(self.port_var.get())
        except ValueError:
            port = 1883
        return cfg.BrokerConfig(host=self.host_var.get().strip() or "127.0.0.1", port=port,
                                username=self.user_var.get().strip(), password=self.pass_var.get(),
                                protocol=self.fleet.broker.protocol)

    def _save_config(self) -> None:
        self.fleet.broker = self._broker()
        self.fleet.group_id = self.group_var.get().strip() or self.fleet.group_id
        cfg.save(self.fleet, self.config_path)
        self._log_bg(f"已儲存 {self.config_path}")

    # ---- runners -------------------------------------------------------------
    def _new_runner(self, spec: cfg.GatewayConfig, physics=None) -> GatewayRunner:
        runner = GatewayRunner(
            self._broker(), self.group_var.get().strip() or self.fleet.group_id, spec,
            interval=float(self.interval_var.get() or 5), faults=self.faults_var.get(),
            autonomous=self.autonomous_var.get(), report=self._log_bg, physics=physics,
        )
        runner.auto_ack = self.auto_ack_var.get()
        return runner

    def _runner(self, node_id: str) -> GatewayRunner | None:
        return next((r for r in self.runners if r.node_id == node_id), None)

    def _start(self, runner: GatewayRunner) -> None:
        if runner.is_alive():
            return
        if runner.ident is not None:  # a thread runs once; keep the physics, new thread
            fresh = self._new_runner(runner.spec, physics=runner.physics)
            fresh.physics.autonomous = self.autonomous_var.get()
            self.runners = [fresh if r is runner else r for r in self.runners]
            runner = fresh
        runner.start()

    def connect_all(self) -> None:
        for runner in list(self.runners):
            self._start(runner)

    def toggle_outage_selected(self) -> None:
        for node_id in self.fleet_view.selection():
            runner = self._runner(node_id)
            if runner is None:
                continue
            runner.physics.grid_outage = not runner.physics.grid_outage
            state = "停電" if runner.physics.grid_outage else "復電"
            self._log_bg(f"[{node_id}] {state}：關口電壓 {'0 V，電池轉孤島供電' if runner.physics.grid_outage else '恢復'}")

    def disconnect_all(self) -> None:
        for runner in self.runners:
            runner.stop_event.set()

    def _join_all(self, timeout: float) -> None:
        # A runner that was never brought online is a thread that never
        # started; joining it raises. Only wait for the ones that ran.
        for runner in self.runners:
            if runner.ident is not None:
                runner.join(timeout=timeout)

    def connect_selected(self) -> None:
        for node_id in self.fleet_view.selection():
            runner = self._runner(str(node_id))
            if runner:
                self._start(runner)

    def disconnect_selected(self) -> None:
        for node_id in self.fleet_view.selection():
            runner = self._runner(str(node_id))
            if runner:
                runner.stop_event.set()

    def _refresh_status(self) -> None:
        any_online = False
        for runner in self.runners:
            online = runner.online.is_set()
            any_online = any_online or online
            if self.fleet_view.exists(runner.node_id):
                status = "上線" if online else ("連線失敗" if runner.last_error and not runner.is_alive() else "離線")
                self.fleet_view.set(runner.node_id, "status", status)
                self.fleet_view.set(runner.node_id, "mode", MODE_LABELS.get(runner.physics.mode, runner.physics.mode))
                self.fleet_view.set(runner.node_id, "published", runner.published)
        self.all_off.configure(state="normal" if any_online else "disabled")

    def _refresh_targets(self) -> None:
        targets = [f"{r.node_id} / {d.device_id}" for r in self.runners for d in r.devices]
        self.target_pick.configure(values=targets)
        if targets and self.target_var.get() not in targets:
            self.target_var.set(targets[0])

    def _target(self) -> tuple[GatewayRunner, str] | None:
        raw = self.target_var.get()
        if " / " not in raw:
            return None
        node_id, device_id = raw.split(" / ", 1)
        runner = self._runner(node_id)
        return (runner, device_id) if runner else None

    def _refresh_values(self) -> None:
        target = self._target()
        if target is not None and getattr(self, "_lock_shown_for", None) is not target[0].node_id:
            self._lock_shown_for = target[0].node_id
            for key, var in self.lock_vars.items():
                value = target[0].physics.forced.get(key)
                var.set("" if value is None else f"{value:g}")
        self.values_view.delete(*self.values_view.get_children())
        if target is None:
            self.values_at.configure(text="")
            return
        runner, device_id = target
        values = runner.latest.get(device_id)
        if not values:
            self.values_at.configure(text="（尚未上線）" if not runner.online.is_set() else "")
            return
        self.values_at.configure(text=time.strftime("更新 %H:%M:%S", time.localtime(runner.latest_at.get(device_id, 0))))
        forced = runner.overrides.get(device_id, {})
        for key in sorted(values):
            value = values[key]
            shown = f"{value:,.3f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)
            if key in forced:
                shown = f"★ {shown}"
            self.values_view.insert("", "end", iid=key, values=(key, shown, METRIC_UNITS.get(key, "")),
                                    tags=("override",) if key in forced else ())

    # ---- overrides (驗證雲端計算) ---------------------------------------------
    def _override_selected(self, _event=None) -> None:
        target = self._target()
        selected = self.values_view.selection()
        if target is None or not selected:
            return
        runner, device_id = target
        metric = str(selected[0])
        current = runner.latest.get(device_id, {}).get(metric)
        raw = simpledialog.askstring("覆寫上傳值", f"{device_id} / {metric}\n輸入要強制上傳的數值（留空解除）：",
                                     initialvalue="" if current is None else str(current), parent=self.root)
        if raw is None:
            return
        raw = raw.strip()
        if raw == "":
            runner.set_override(device_id, metric, None)
            self._log_bg(f"[{runner.node_id}] 解除覆寫 {device_id}.{metric}")
        else:
            try:
                value: float | str = float(raw)
            except ValueError:
                value = raw
            runner.set_override(device_id, metric, value)
            self._log_bg(f"[{runner.node_id}] 覆寫 {device_id}.{metric} = {value}")
        self._push(runner)

    def _clear_selected_override(self) -> None:
        target = self._target()
        selected = self.values_view.selection()
        if target is None or not selected:
            return
        runner, device_id = target
        runner.set_override(device_id, str(selected[0]), None)
        self._push(runner)

    def _clear_device_overrides(self) -> None:
        target = self._target()
        if target is None:
            return
        runner, device_id = target
        runner.overrides.pop(device_id, None)
        self._log_bg(f"[{runner.node_id}] 解除 {device_id} 全部覆寫")
        self._push(runner)

    def _apply_deterministic(self) -> None:
        for runner in self.runners:
            runner.physics.deterministic = self.deterministic_var.get()

    def _apply_lock(self) -> None:
        target = self._target()
        if target is None:
            return
        runner, _device_id = target
        values: dict[str, float | None] = {}
        for key, var in self.lock_vars.items():
            raw = var.get().strip()
            if raw == "":
                values[key] = None
                continue
            try:
                values[key] = float(raw)
            except ValueError:
                messagebox.showerror("格式錯誤", f"{key} 不是數字：{raw!r}")
                return
        runner.physics.force(**values)
        locked = ", ".join(f"{k}={v:g}" for k, v in values.items() if v is not None) or "（無）"
        self._log_bg(f"[{runner.node_id}] 鎖定物理量：{locked}")
        self._push(runner)

    def _clear_lock(self) -> None:
        target = self._target()
        if target is None:
            return
        runner, _device_id = target
        runner.physics.force(load_kw=None, pv_kw=None, battery_kw=None, soc=None)
        for var in self.lock_vars.values():
            var.set("")
        self._log_bg(f"[{runner.node_id}] 解除物理量鎖定")
        self._push(runner)

    def _push(self, runner: GatewayRunner) -> None:
        if runner.publish_now():
            self._log_bg(f"[{runner.node_id}] 已立即上傳一輪")
        else:
            self._log_bg(f"[{runner.node_id}] 離線：覆寫已記住，上線後生效")
        self._refresh_values()

    # ---- manual tests ----------------------------------------------------------
    def send_event(self) -> None:
        target = self._target()
        if target:
            runner, device_id = target
            runner.publish_event(device_id, self.event_code.get().strip(), self.event_level.get(), self.event_message.get())

    def send_alarm(self, active: bool) -> None:
        target = self._target()
        if target:
            runner, device_id = target
            runner.publish_alarm(device_id, self.alarm_code.get().strip(), self.alarm_severity.get(),
                                 self.alarm_message.get(), active)

    def _toggle_auto_ack(self) -> None:
        for runner in self.runners:
            runner.auto_ack = self.auto_ack_var.get()

    def answer(self, status: str) -> None:
        selected = self.commands.selection()
        if not selected:
            return
        node_id, device_id, name, command_id, params = self.commands.item(selected[0], "values")
        runner = self._runner(node_id)
        if runner is None:
            return
        import ast

        try:
            parsed = ast.literal_eval(params) if params else {}
        except (ValueError, SyntaxError):
            parsed = {}
        threading.Thread(target=runner.answer, args=(device_id, command_id, status),
                         kwargs={"name": name, "params": parsed}, daemon=True).start()
        if status in ("succeeded", "failed"):
            self.commands.delete(selected[0])

    # ---- lifecycle ---------------------------------------------------------------
    def run(self) -> None:
        def on_close() -> None:
            self.disconnect_all()
            self._join_all(timeout=3)
            self.root.destroy()

        self.root.protocol("WM_DELETE_WINDOW", on_close)
        self.root.mainloop()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="ZQS standalone device simulator")
    parser.add_argument("-c", "--config", default=str(cfg.DEFAULT_PATH), help="fleet.json path")
    args = parser.parse_args(argv)
    App(Path(args.config)).run()


if __name__ == "__main__":
    main()
