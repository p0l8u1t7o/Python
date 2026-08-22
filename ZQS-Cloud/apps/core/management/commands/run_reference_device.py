"""Run the reference device simulator against the conformance harness.

The known-good control. Run it before testing the LabVIEW client: if the
harness passes this, the harness is behaving, and any later failure belongs to
the device under test.

    python manage.py run_reference_device --device ZQS-BESS-0001 --password ...
    python manage.py run_reference_device --device ... --misbehave no_lwt

``--misbehave`` deliberately breaks one rule, which is how you confirm the
harness actually catches things rather than passing everything.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from services.harness.simulator import ReferenceDevice

FAULTS = {
    "": "正常行為（預設）",
    "bad_client_id": "用 LabVIEW_1 當 client id → 應觸發 client_id_format 失敗",
    "no_lwt": "不宣告 NDEATH 遺言 → 應觸發 lwt_declared 失敗",
    "clean_session": "clean_session=false → 應觸發 clean_session 失敗",
    "retained_will": "遺言設 retain → 應觸發 lwt_retain 失敗",
    "bad_payload": "DDATA 不是 protobuf → 應觸發 payload_schema 失敗",
    "bad_qos": "DDATA 用 QoS 1 → 應觸發 publish_qos 警告",
    "no_ack": "收到命令不回覆 → command_ack 保持未測",
    "ignore_rebirth": "忽略 Rebirth 要求 → rebirth_honoured 保持未測",
}


class Command(BaseCommand):
    help = "Reference MQTT device: the known-good control for the test harness."

    def add_arguments(self, parser):
        parser.add_argument("--device", required=True, help="device_id")
        parser.add_argument(
            "--username",
            default="",
            help="MQTT username. Looked up from the registry when omitted.",
        )
        parser.add_argument("--password", required=True, help="MQTT password")
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--port", type=int, default=1883)
        parser.add_argument("--interval", type=float, default=5.0)
        parser.add_argument("--keepalive", type=int, default=45)
        parser.add_argument(
            "--duration",
            type=float,
            default=0.0,
            help="Stop after this many seconds. 0 runs until Ctrl-C.",
        )
        parser.add_argument(
            "--abrupt-exit",
            action="store_true",
            help=(
                "Drop the socket without DISCONNECT, so the broker delivers the "
                "will. This is how you test the LWT end to end."
            ),
        )
        parser.add_argument(
            "--misbehave",
            default="",
            choices=sorted(FAULTS),
            help="Break one rule on purpose, to verify the harness catches it.",
        )
        parser.add_argument(
            "--group", default="", help="Sparkplug group_id. Defaults to the device's."
        )
        parser.add_argument(
            "--node", default="", help="Sparkplug edge_node_id. Defaults to the device's."
        )

    def handle(self, *args, **options):
        username, group_id, node_id = self._lookup(options["device"])
        username = options["username"] or username
        group_id = options["group"] or group_id
        node_id = options["node"] or node_id
        if not group_id or not node_id:
            raise CommandError(
                "無法判斷 Sparkplug 位址。請先註冊設備，或用 --group 與 --node "
                "明確指定。"
            )

        device = ReferenceDevice(
            device_id=options["device"],
            username=username,
            password=options["password"],
            group_id=group_id,
            node_id=node_id,
            host=options["host"],
            port=options["port"],
            interval=options["interval"],
            keepalive=options["keepalive"],
            misbehave=options["misbehave"],
        )

        self.stdout.write(self.style.SUCCESS("參考設備模擬器"))
        self.stdout.write(f"  位址       {group_id}/{node_id}/{options['device']}")
        self.stdout.write(f"  username   {username}")
        self.stdout.write(f"  連線至     {options['host']}:{options['port']}")
        self.stdout.write(f"  行為       {FAULTS[options['misbehave']]}")
        if options["abrupt_exit"]:
            self.stdout.write(self.style.WARNING("  結束時會強制斷線以觸發遺言"))
        self.stdout.write("")

        try:
            device.run(
                duration=options["duration"] or None,
                abrupt_exit=options["abrupt_exit"],
            )
        except KeyboardInterrupt:
            device.stop()
        except OSError as exc:
            raise CommandError(
                f"無法連線到 {options['host']}:{options['port']}：{exc}\n"
                "測試工具啟動了嗎？ python manage.py run_test_broker"
            ) from exc

    def _lookup(self, device_id: str) -> tuple[str, str, str]:
        """``(username, group_id, node_id)`` for a registered device."""
        from apps.devices.models import Device

        row = (
            Device.objects.filter(device_id=device_id, deleted_at__isnull=True)
            .values_list(
                "edge_node__credential__mqtt_username",
                "edge_node__group_id",
                "edge_node__node_id",
            )
            .first()
        )
        if row is None:
            return "", "", ""
        return row[0] or "", row[1] or "", row[2] or ""
