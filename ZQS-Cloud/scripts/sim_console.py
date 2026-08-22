# -*- coding: utf-8 -*-
"""ZQS 模擬器主控台 - 桌面版 Sparkplug 閘道器 + 設備模擬器。

一支程式就是一個完整的邊緣節點:一條 MQTT 連線、一個 seq 計數器、一組
生死訊息,底下掛任意數量的模擬設備。取代「gateway 一支、device 一支」
的組合,並提供圖形介面做收發與按鍵動作測試:

* 上線 / 離線(NBIRTH+DBIRTH / DDEATH+NDEATH,含 last-will)
* 遙測:單發一次,或以設定間隔自動發送
* 事件與告警注入(``Event/<code>`` / ``Alarm/<code>`` metric)
* 命令測試:收到 DCMD 後列出,可自動回覆,或手動按
  [接受] / [成功] / [失敗] 觀察平台端的命令生命週期
* 即時收發日誌

執行::

    .venv\\Scripts\\python.exe scripts\\sim_console.py

Tkinter 標準庫即滿足,無額外相依。MQTT 收發在背景執行緒,UI 透過
queue + ``after()`` 更新 - Tk 不允許跨執行緒操作元件。
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: E402

django.setup()

import tkinter as tk  # noqa: E402
from tkinter import ttk  # noqa: E402

from apps.core.management.commands.simulate_device import (  # noqa: E402
    _State,
    _birth_metrics,
    _sample,
    PROFILES,
)
from apps.devices.models import Device  # noqa: E402
from services.mqtt.client import MqttClient  # noqa: E402
from services.sparkplug import payload as sp  # noqa: E402
from services.sparkplug import profile as sp_profile  # noqa: E402
from services.sparkplug import topics  # noqa: E402
from services.sparkplug.node import EdgeNodeClient  # noqa: E402

#: 設備類別 -> 模擬 profile 的預設對應;可在表格中改。
CATEGORY_PROFILE = {
    "battery": "battery",
    "meter": "meter",
    "power-generation-unit": "pv",
    "pv": "pv",
    "fuelcell": "fuelcell",
    "controller": "controller",
    "load": "meter",
}

EVENT_LEVELS = ("info", "notice", "warning", "error", "critical")
ALARM_SEVERITIES = ("info", "warning", "major", "critical")


class Gateway:
    """背景執行緒側:一個邊緣節點連線與其設備。"""

    def __init__(self, log):
        self.log = log
        self.client: MqttClient | None = None
        self.node: EdgeNodeClient | None = None
        self.devices: dict[str, str] = {}
        self.states: dict[str, _State] = {}
        self.pending_commands: "queue.Queue[dict]" = queue.Queue()
        self.auto_ack = True
        self.online = False

    # ---- lifecycle -------------------------------------------------------
    def connect(self, group_id: str, node_id: str, devices: dict[str, str]) -> None:
        self.devices = dict(devices)
        self.states = {device_id: _State() for device_id in devices}

        client = MqttClient(client_suffix=f"simui-{node_id}", clean_session=True)
        node = EdgeNodeClient(client, group_id, node_id)
        node.next_bd_seq()

        will_qos, will_retain = topics.publish_options(topics.MessageType.NDEATH)
        client.set_last_will(
            topics.build(group_id, topics.MessageType.NDEATH, node_id),
            node.death_payload(),
            qos=will_qos,
            retain=will_retain,
        )
        client.on_message_callback = self._on_message
        client.subscriptions = node.command_subscriptions()
        client.connect()

        self.client = client
        self.node = node
        self.log(f"已連線 broker,節點 {group_id}/{node_id}")

    def birth(self) -> None:
        if not self.node:
            return
        self.node.publish_nbirth()
        for device_id, profile_name in self.devices.items():
            self.node.publish_dbirth(
                device_id,
                _birth_metrics(profile_name, _sample(profile_name, self.states[device_id])),
            )
        self.online = True
        self.log(f"NBIRTH + {len(self.devices)} 個 DBIRTH 已發布")

    def death(self) -> None:
        if not self.node:
            return
        for device_id in self.devices:
            self.node.publish_ddeath(device_id)
        self.node.publish_ndeath()
        self.online = False
        self.log("DDEATH + NDEATH 已發布(節點離線)")

    def disconnect(self) -> None:
        if self.online:
            self.death()
        if self.client:
            self.client.disconnect()
        self.client = None
        self.node = None
        self.log("已中斷連線")

    # ---- publishing ------------------------------------------------------
    def publish_telemetry(self) -> int:
        if not self.node or not self.online:
            return 0
        count = 0
        for device_id, profile_name in self.devices.items():
            values = _sample(profile_name, self.states[device_id])
            self.node.publish_ddata(device_id, values)
            count += 1
        return count

    def publish_event(self, device_id: str, code: str, level: str, message: str) -> None:
        if not self.node or not self.online:
            self.log("尚未上線,無法發送")
            return
        self.node.publish_ddata(
            device_id,
            {f"{sp_profile.EVENT_PREFIX}{code}": message},
            properties={f"{sp_profile.EVENT_PREFIX}{code}": {"level": level}},
        )
        self.log(f"TX 事件 {device_id} {code} [{level}] {message}")

    def publish_alarm(self, device_id: str, code: str, severity: str,
                      message: str, active: bool) -> None:
        if not self.node or not self.online:
            self.log("尚未上線,無法發送")
            return
        self.node.publish_ddata(
            device_id,
            {f"{sp_profile.ALARM_PREFIX}{code}": active},
            properties={
                f"{sp_profile.ALARM_PREFIX}{code}": {
                    "severity": severity, "message": message,
                }
            },
        )
        state = "觸發" if active else "解除"
        self.log(f"TX 告警 {device_id} {code} [{severity}] {state}")

    def ack(self, device_id: str, command_id: str, status: str, message: str = "") -> None:
        if self.node:
            self.node.ack(device_id, command_id, status, message=message)
            self.log(f"TX 命令回覆 {command_id} -> {status}")

    # ---- inbound ---------------------------------------------------------
    def _on_message(self, topic: str, raw: bytes, qos: int, retain: bool) -> None:
        parsed = topics.parse(topic)
        if parsed is None:
            return
        try:
            view = sp.decode(raw)
        except sp.PayloadError:
            return
        names = {metric.name: metric.value for metric in view.metrics}

        if names.get(sp.NODE_REBIRTH_METRIC) or names.get(sp.DEVICE_REBIRTH_METRIC):
            self.log("RX 重生請求,重新宣告")
            self.birth()
            return

        command_id = names.get(sp_profile.COMMAND_ID)
        if not command_id or parsed.device_id not in self.devices:
            return
        command_name = str(names.get(sp_profile.COMMAND_NAME, ""))
        params = {
            key: value for key, value in names.items()
            if key not in (sp_profile.COMMAND_ID, sp_profile.COMMAND_NAME)
        }
        self.log(f"RX 命令 {parsed.device_id} {command_name} ({command_id}) {params}")

        if self.auto_ack:
            self.ack(parsed.device_id, str(command_id), "accepted")
            self.ack(parsed.device_id, str(command_id), "succeeded", message="simulated")
        else:
            self.pending_commands.put({
                "device_id": parsed.device_id,
                "command_id": str(command_id),
                "name": command_name,
                "params": params,
            })


class App:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("ZQS 模擬器主控台")
        self.root.geometry("880x640")

        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.gateway = Gateway(self._log_bg)
        self.auto_thread: threading.Thread | None = None
        self.auto_running = threading.Event()

        self._build()
        self._load_devices()
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

        try:
            while True:
                command = self.gateway.pending_commands.get_nowait()
                self.commands.insert(
                    "", "end",
                    values=(command["device_id"], command["name"],
                            command["command_id"], str(command["params"])),
                )
        except queue.Empty:
            pass

        self.root.after(150, self._poll)

    # ---- UI --------------------------------------------------------------
    def _build(self) -> None:
        pad = {"padx": 6, "pady": 3}

        top = ttk.LabelFrame(self.root, text="邊緣節點")
        top.pack(fill="x", **pad)
        ttk.Label(top, text="Group / Node:").grid(row=0, column=0, sticky="w", **pad)
        self.node_var = tk.StringVar()
        self.node_pick = ttk.Combobox(top, textvariable=self.node_var, width=38, state="readonly")
        self.node_pick.grid(row=0, column=1, sticky="w", **pad)
        self.node_pick.bind("<<ComboboxSelected>>", lambda _e: self._load_devices())

        self.connect_button = ttk.Button(top, text="連線並上線", command=self.connect)
        self.connect_button.grid(row=0, column=2, **pad)
        self.offline_button = ttk.Button(top, text="離線", command=self.offline, state="disabled")
        self.offline_button.grid(row=0, column=3, **pad)
        self.disconnect_button = ttk.Button(top, text="中斷連線", command=self.disconnect, state="disabled")
        self.disconnect_button.grid(row=0, column=4, **pad)

        middle = ttk.Frame(self.root)
        middle.pack(fill="both", expand=True, **pad)

        left = ttk.LabelFrame(middle, text="模擬設備")
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        self.devices = ttk.Treeview(
            left, columns=("device", "profile"), show="headings", height=6
        )
        self.devices.heading("device", text="Device ID")
        self.devices.heading("profile", text="Profile")
        self.devices.column("device", width=180)
        self.devices.column("profile", width=100)
        self.devices.pack(fill="both", expand=True, padx=4, pady=4)
        self.devices.bind("<Double-1>", self._cycle_profile)
        ttk.Label(left, text="雙擊 Profile 欄可切換模擬類型").pack(anchor="w", padx=4)

        telemetry = ttk.LabelFrame(middle, text="遙測")
        telemetry.pack(side="left", fill="y", padx=(0, 6))
        ttk.Button(telemetry, text="發送一次", command=self.send_once).pack(fill="x", **pad)
        row = ttk.Frame(telemetry)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="間隔(秒)").pack(side="left")
        self.interval_var = tk.StringVar(value="5")
        ttk.Entry(row, textvariable=self.interval_var, width=5).pack(side="left", padx=4)
        self.auto_button = ttk.Button(telemetry, text="開始自動發送", command=self.toggle_auto)
        self.auto_button.pack(fill="x", **pad)

        inject = ttk.LabelFrame(middle, text="事件 / 告警注入")
        inject.pack(side="left", fill="y")
        self.code_var = tk.StringVar(value="E0231")
        self.level_var = tk.StringVar(value="error")
        self.severity_var = tk.StringVar(value="major")
        self.message_var = tk.StringVar(value="Simulated fault")
        grid = ttk.Frame(inject)
        grid.pack(fill="x", **pad)
        ttk.Label(grid, text="代碼").grid(row=0, column=0, sticky="w")
        ttk.Entry(grid, textvariable=self.code_var, width=10).grid(row=0, column=1)
        ttk.Label(grid, text="訊息").grid(row=1, column=0, sticky="w")
        ttk.Entry(grid, textvariable=self.message_var, width=16).grid(row=1, column=1)
        ttk.Label(grid, text="事件層級").grid(row=2, column=0, sticky="w")
        ttk.Combobox(grid, textvariable=self.level_var, values=EVENT_LEVELS,
                     width=8, state="readonly").grid(row=2, column=1)
        ttk.Label(grid, text="告警嚴重度").grid(row=3, column=0, sticky="w")
        ttk.Combobox(grid, textvariable=self.severity_var, values=ALARM_SEVERITIES,
                     width=8, state="readonly").grid(row=3, column=1)
        ttk.Button(inject, text="送出事件", command=self.send_event).pack(fill="x", **pad)
        ttk.Button(inject, text="觸發告警", command=lambda: self.send_alarm(True)).pack(fill="x", **pad)
        ttk.Button(inject, text="解除告警", command=lambda: self.send_alarm(False)).pack(fill="x", **pad)

        commands = ttk.LabelFrame(self.root, text="收到的命令(按鍵動作測試)")
        commands.pack(fill="both", **pad)
        bar = ttk.Frame(commands)
        bar.pack(fill="x", **pad)
        self.auto_ack_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            bar, text="自動回覆(accepted + succeeded)",
            variable=self.auto_ack_var, command=self._toggle_auto_ack,
        ).pack(side="left")
        ttk.Button(bar, text="接受", command=lambda: self.answer("accepted")).pack(side="right", padx=2)
        ttk.Button(bar, text="成功", command=lambda: self.answer("succeeded")).pack(side="right", padx=2)
        ttk.Button(bar, text="失敗", command=lambda: self.answer("failed")).pack(side="right", padx=2)
        self.commands = ttk.Treeview(
            commands, columns=("device", "name", "id", "params"), show="headings", height=4
        )
        for key, title, width in (
            ("device", "Device", 140), ("name", "命令", 120),
            ("id", "Command ID", 220), ("params", "參數", 260),
        ):
            self.commands.heading(key, text=title)
            self.commands.column(key, width=width)
        self.commands.pack(fill="both", expand=True, padx=4, pady=4)

        logframe = ttk.LabelFrame(self.root, text="收發日誌")
        logframe.pack(fill="both", expand=True, **pad)
        self.log = tk.Text(logframe, height=8, state="disabled",
                           bg="#0b1220", fg="#7dd3fc", font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, padx=4, pady=4)

    # ---- data ------------------------------------------------------------
    def _load_devices(self) -> None:
        registered = list(
            Device.objects.select_related("edge_node", "device_type")
            .filter(deleted_at__isnull=True, edge_node__isnull=False)
        )
        nodes = sorted({
            f"{device.edge_node.group_id}/{device.edge_node.node_id}"
            for device in registered
        })
        self.node_pick["values"] = nodes
        if nodes and not self.node_var.get():
            self.node_var.set(nodes[0])

        wanted = self.node_var.get()
        for row in self.devices.get_children():
            self.devices.delete(row)
        for device in registered:
            key = f"{device.edge_node.group_id}/{device.edge_node.node_id}"
            if key != wanted:
                continue
            category = device.device_type.category if device.device_type_id else ""
            profile = CATEGORY_PROFILE.get(category, "meter")
            self.devices.insert("", "end", values=(device.device_id, profile))

    def _cycle_profile(self, _event) -> None:
        item = self.devices.focus()
        if not item:
            return
        device_id, profile = self.devices.item(item, "values")
        index = (PROFILES.index(profile) + 1) % len(PROFILES) if profile in PROFILES else 0
        self.devices.item(item, values=(device_id, PROFILES[index]))

    def _selected_devices(self) -> dict[str, str]:
        return {
            self.devices.item(item, "values")[0]: self.devices.item(item, "values")[1]
            for item in self.devices.get_children()
        }

    def _target_device(self) -> str | None:
        item = self.devices.focus()
        if item:
            return self.devices.item(item, "values")[0]
        children = self.devices.get_children()
        return self.devices.item(children[0], "values")[0] if children else None

    # ---- actions ---------------------------------------------------------
    def connect(self) -> None:
        chosen = self.node_var.get()
        if not chosen or "/" not in chosen:
            self._log_bg("請先選擇邊緣節點")
            return
        group_id, node_id = chosen.split("/", 1)
        devices = self._selected_devices()
        if not devices:
            self._log_bg("此節點下沒有已註冊設備")
            return

        def work() -> None:
            try:
                self.gateway.connect(group_id, node_id, devices)
                self.gateway.birth()
            except Exception as exc:  # noqa: BLE001 - shown to the tester
                self._log_bg(f"連線失敗:{exc}")
                return
            self.root.after(0, self._set_connected, True)

        threading.Thread(target=work, daemon=True).start()

    def _set_connected(self, connected: bool) -> None:
        state = "disabled" if connected else "normal"
        inverse = "normal" if connected else "disabled"
        self.connect_button.configure(state=state)
        self.offline_button.configure(state=inverse)
        self.disconnect_button.configure(state=inverse)

    def offline(self) -> None:
        self.stop_auto()
        threading.Thread(target=self.gateway.death, daemon=True).start()

    def disconnect(self) -> None:
        self.stop_auto()

        def work() -> None:
            self.gateway.disconnect()
            self.root.after(0, self._set_connected, False)

        threading.Thread(target=work, daemon=True).start()

    def send_once(self) -> None:
        def work() -> None:
            count = self.gateway.publish_telemetry()
            if count:
                self._log_bg(f"TX 遙測 x{count}")

        threading.Thread(target=work, daemon=True).start()

    def toggle_auto(self) -> None:
        if self.auto_running.is_set():
            self.stop_auto()
            return
        try:
            interval = max(0.5, float(self.interval_var.get()))
        except ValueError:
            self._log_bg("間隔必須是數字")
            return
        self.auto_running.set()
        self.auto_button.configure(text="停止自動發送")
        self._log_bg(f"自動發送啟動,每 {interval:g} 秒")

        def loop() -> None:
            while self.auto_running.is_set():
                count = self.gateway.publish_telemetry()
                if count:
                    self._log_bg(f"TX 遙測 x{count}")
                time.sleep(interval)

        self.auto_thread = threading.Thread(target=loop, daemon=True)
        self.auto_thread.start()

    def stop_auto(self) -> None:
        if self.auto_running.is_set():
            self.auto_running.clear()
            self.auto_button.configure(text="開始自動發送")
            self._log_bg("自動發送停止")

    def send_event(self) -> None:
        device_id = self._target_device()
        if device_id:
            self.gateway.publish_event(
                device_id, self.code_var.get().strip() or "E0000",
                self.level_var.get(), self.message_var.get(),
            )

    def send_alarm(self, active: bool) -> None:
        device_id = self._target_device()
        if device_id:
            self.gateway.publish_alarm(
                device_id, self.code_var.get().strip() or "A0000",
                self.severity_var.get(), self.message_var.get(), active,
            )

    def _toggle_auto_ack(self) -> None:
        self.gateway.auto_ack = self.auto_ack_var.get()
        self._log_bg(
            "命令改為自動回覆" if self.gateway.auto_ack else "命令改為手動回覆(按鍵測試)"
        )

    def answer(self, status: str) -> None:
        item = self.commands.focus() or (
            self.commands.get_children()[0] if self.commands.get_children() else ""
        )
        if not item:
            self._log_bg("沒有待回覆的命令")
            return
        device_id, _name, command_id, _params = self.commands.item(item, "values")
        self.gateway.ack(device_id, command_id, status,
                         message="manual test" if status != "accepted" else "")
        if status in ("succeeded", "failed"):
            self.commands.delete(item)

    # ---- main ------------------------------------------------------------
    def run(self) -> None:
        def on_close() -> None:
            self.stop_auto()
            try:
                self.gateway.disconnect()
            finally:
                self.root.destroy()

        self.root.protocol("WM_DELETE_WINDOW", on_close)
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
