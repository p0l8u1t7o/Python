"""Conformance checks for a device connecting to the test harness.

**The first principle of this module: it does not restate the platform's
rules, it calls them.**

A harness that re-implements "what a valid payload looks like" drifts from the
real ingestor the moment either side changes, and a passing test then means
nothing. So credentials go through :func:`apps.devices.services.authenticate_device`,
topic permission goes through the same predicate the EMQX ACL webhook uses, and
payloads go through :func:`services.ingestor.protocol.decode` and
:func:`~services.ingestor.protocol.validate` - the very functions that run in
production before anything reaches the queue.

Where the harness is deliberately **stricter** than production it says so in
the check's own description, and :data:`STRICTER_THAN_PRODUCTION` lists them.
Stricter is safe; looser would be a lie.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings

from apps.core.timeutils import now
from services.mqtt import topics

PASS = "pass"
FAIL = "fail"
WARN = "warn"
PENDING = "pending"

#: Checks the harness enforces that production tolerates. Being stricter here
#: is intentional - it catches things that would work today but break the first
#: time an operator turns the corresponding safeguard on.
STRICTER_THAN_PRODUCTION = {
    "client_id_format": (
        "Production only pins the client id when DeviceCredential."
        "allowed_client_id is set, and it is empty by default. The harness "
        "always requires zqs:<device_id>."
    ),
    "clean_session": (
        "A broker accepts clean_session=true happily. The protocol requires "
        "false so a QoS 1 downlink survives a short outage."
    ),
    "birth_retained": (
        "A broker does not care whether the birth message is retained. The "
        "platform does: without it a reconnecting console sees no state."
    ),
    "keepalive_range": (
        "Any keepalive is legal MQTT. The protocol document recommends 45 s."
    ),
}


@dataclass
class Check:
    """One line of the acceptance checklist."""

    key: str
    title: str
    status: str = PENDING
    #: What the platform requires, in the device author's terms.
    expected: str = ""
    #: What actually arrived. Empty until the check runs.
    actual: str = ""
    detail: str = ""
    required: bool = True

    def succeed(self, actual: str = "", detail: str = "") -> None:
        self.status = PASS
        self.actual = actual
        self.detail = detail

    def fail(self, actual: str, detail: str = "") -> None:
        self.status = FAIL
        self.actual = actual
        self.detail = detail

    def warn(self, actual: str, detail: str = "") -> None:
        self.status = WARN
        self.actual = actual
        self.detail = detail


def build_checklist(device_id: str) -> dict[str, Check]:
    """The full acceptance list, in the order a device exercises it."""
    root = topics.root()
    return {
        check.key: check
        for check in [
            # ---- CONNECT ------------------------------------------------
            Check(
                "mqtt_version",
                "MQTT 協定版本",
                expected="3.1.1（protocol level 4）或 5.0（level 5）",
            ),
            Check(
                "client_id_format",
                "Client ID 格式",
                expected=f"zqs:{device_id}",
            ),
            Check(
                "username_format",
                "Username 格式",
                expected="dev-<組織代碼>-<device_id>",
            ),
            Check(
                "credentials",
                "帳號密碼驗證",
                expected="通過 authenticate_device()（與正式環境同一個函式）",
            ),
            Check(
                "keepalive_range",
                "Keepalive",
                expected="1–120 秒，建議 45",
                required=False,
            ),
            Check(
                "clean_session",
                "Clean session",
                expected="false（QoS 1 下行才能撐過短暫斷線）",
            ),
            Check("lwt_declared", "LWT 已宣告", expected="CONNECT 帶 will flag"),
            Check(
                "lwt_topic",
                "LWT topic",
                expected=f"{root}/{device_id}/{topics.STATUS}",
            ),
            Check("lwt_qos", "LWT QoS", expected="1"),
            Check("lwt_retain", "LWT retained", expected="true"),
            Check(
                "lwt_payload",
                "LWT payload",
                expected='JSON 物件，status="offline"',
            ),
            # ---- SUBSCRIBE ----------------------------------------------
            Check(
                "subscribe_control",
                "訂閱 control topic",
                expected=f"{root}/{device_id}/{topics.CONTROL}",
            ),
            Check(
                "subscribe_acl",
                "訂閱權限（ACL）",
                expected="只訂閱自己的 control topic",
            ),
            Check("subscribe_qos", "訂閱 QoS", expected="1", required=False),
            # ---- PUBLISH -------------------------------------------------
            Check(
                "birth_status",
                "上線後發布 status",
                expected='連線後立即發一則 status="online"',
            ),
            Check(
                "birth_retained",
                "status 設為 retained",
                expected="retain=true",
            ),
            Check("publish_acl", "發布權限（ACL）", expected="只發布到自己的 topic 子樹"),
            Check("publish_qos", "上行 QoS", expected="1"),
            Check(
                "payload_schema",
                "Payload 通過正式 schema",
                expected="與 ingestor 相同的 decode() + validate()",
            ),
            Check("telemetry_seen", "收到 telemetry", expected="至少一則"),
            # ---- 互動 -----------------------------------------------------
            Check(
                "command_ack",
                "命令回覆（control/ack）",
                expected="收到命令後回 ack，command_id 原樣帶回",
                required=False,
            ),
            Check(
                "lwt_delivered",
                "LWT 實測",
                expected="強制斷線後 broker 確實送出遺言",
                required=False,
            ),
        ]
    }


# ---------------------------------------------------------------------------
# CONNECT
# ---------------------------------------------------------------------------
def check_connect(checks: dict[str, Check], packet, device_id: str) -> list[str]:
    """Run every CONNECT-time check. Returns the keys that failed."""
    root = topics.root()

    # -- protocol version
    level = packet.protocol_level
    if level in (4, 5):
        checks["mqtt_version"].succeed(
            f"protocol level {level}（{'3.1.1' if level == 4 else '5.0'}）"
        )
    else:
        checks["mqtt_version"].fail(
            f"protocol level {level}",
            "只接受 3.1.1（level 4）或 5.0（level 5）。LabVIEW 的 MQTT toolkit "
            "通常有一個「MQTT version」設定，請選 3.1.1。",
        )

    # -- client id
    expected_client_id = f"{settings.MQTT['CLIENT_ID_PREFIX']}:{device_id}"
    if packet.client_id == expected_client_id:
        checks["client_id_format"].succeed(packet.client_id)
    else:
        checks["client_id_format"].fail(
            packet.client_id or "(空字串)",
            f"應為 {expected_client_id!r}，實際收到 {packet.client_id!r}。"
            "ACL webhook 可以把 client id 釘選成這個值。",
        )

    # -- username shape
    username = packet.username or ""
    if not username:
        checks["username_format"].fail("(未提供)", "CONNECT 沒有帶 username。")
    elif username.startswith("dev-") and username.endswith(f"-{device_id}"):
        checks["username_format"].succeed(username)
    else:
        checks["username_format"].fail(
            username,
            f"應為 dev-<組織代碼>-{device_id}，實際收到 {username!r}。"
            "這串是註冊設備時系統發給你的，不要自己編。",
        )

    # -- keepalive
    keepalive = packet.keepalive
    if keepalive == 0:
        checks["keepalive_range"].warn(
            "0（停用）",
            "keepalive=0 代表永不逾時，斷線偵測會完全依賴 TCP，可能拖到數分鐘。",
        )
    elif 1 <= keepalive <= 120:
        detail = "" if keepalive == 45 else "協定文件建議 45 秒。"
        checks["keepalive_range"].succeed(f"{keepalive} 秒", detail)
    else:
        checks["keepalive_range"].warn(
            f"{keepalive} 秒", "超過 120 秒，離線判定會很慢。建議 45 秒。"
        )

    # -- clean session
    if packet.clean_session:
        checks["clean_session"].fail(
            "true",
            "必須設為 false。clean_session=true 會讓 broker 在斷線時丟掉未送達的"
            "下行命令，設備重連後就收不到了。",
        )
    else:
        checks["clean_session"].succeed("false")

    # -- last will
    if not packet.will_flag:
        checks["lwt_declared"].fail(
            "未宣告",
            "CONNECT 沒有設 will flag。沒有 LWT 的話，設備突然斷電時平台完全"
            "不會知道——這一項最容易被忽略，也最容易在正式環境出事。",
        )
        for key in ("lwt_topic", "lwt_qos", "lwt_retain", "lwt_payload"):
            checks[key].fail("(未宣告 LWT)")
    else:
        checks["lwt_declared"].succeed("已宣告")
        _check_will(checks, packet, device_id, root)

    return [key for key, check in checks.items() if check.status == FAIL]


def _check_will(checks: dict[str, Check], packet, device_id: str, root: str) -> None:
    expected_topic = f"{root}/{device_id}/{topics.STATUS}"
    if packet.will_topic == expected_topic:
        checks["lwt_topic"].succeed(packet.will_topic)
    else:
        checks["lwt_topic"].fail(
            packet.will_topic or "(空字串)",
            f"應為 {expected_topic!r}。遺言要發到 status topic，平台才會把它"
            "當成離線通知。",
        )

    if packet.will_qos == 1:
        checks["lwt_qos"].succeed("1")
    else:
        checks["lwt_qos"].fail(
            str(packet.will_qos), "遺言必須是 QoS 1，否則可能在斷線瞬間遺失。"
        )

    if packet.will_retain:
        checks["lwt_retain"].succeed("true")
    else:
        checks["lwt_retain"].fail(
            "false",
            "遺言要 retained，否則重新連線的 console 看不到設備已經離線。",
        )

    from services.ingestor import protocol

    try:
        document = protocol.decode(packet.will_payload)
    except protocol.ProtocolError as exc:
        checks["lwt_payload"].fail(
            _preview(packet.will_payload), f"遺言內容不是合法 JSON 物件：{exc}"
        )
        return

    if document.get("status") != "offline":
        checks["lwt_payload"].fail(
            _preview(packet.will_payload),
            '遺言的 status 必須是 "offline"，實際是 '
            f"{document.get('status')!r}。",
        )
        return

    try:
        protocol.validate(topics.STATUS, document)
    except protocol.ProtocolError as exc:
        checks["lwt_payload"].fail(_preview(packet.will_payload), str(exc))
        return

    checks["lwt_payload"].succeed(_preview(packet.will_payload))


# ---------------------------------------------------------------------------
# Credentials - straight through the production function
# ---------------------------------------------------------------------------
def check_credentials(checks: dict[str, Check], packet) -> tuple[bool, str]:
    """Authenticate exactly as the EMQX webhook does.

    Returns ``(accepted, reason)``. The reason is written for a device author,
    not for a server log.
    """
    from apps.core.errors import PermissionDenied
    from apps.devices.services import authenticate_device

    username = packet.username or ""
    password = packet.password or ""

    if not username or not password:
        reason = "CONNECT 缺少 username 或 password。"
        checks["credentials"].fail("(缺少憑證)", reason)
        return False, reason

    try:
        device = authenticate_device(username, password, client_id=packet.client_id)
    except PermissionDenied as exc:
        reason = f"client id 與註冊時釘選的值不符：{exc}"
        checks["credentials"].fail(packet.client_id, reason)
        return False, reason
    except Exception as exc:  # noqa: BLE001 - report, do not crash the harness
        reason = f"驗證時發生錯誤：{exc!r}"
        checks["credentials"].fail(username, reason)
        return False, reason

    if device is None:
        reason = (
            "帳號或密碼不正確，或該設備已停用／退役。密碼只在註冊（或輪替）時"
            "顯示一次，如果弄丟了就到 console 重新產生。"
        )
        checks["credentials"].fail(username, reason)
        return False, reason

    checks["credentials"].succeed(f"{username} → {device.device_id}")
    return True, ""


# ---------------------------------------------------------------------------
# ACL - the same predicate the webhook uses
# ---------------------------------------------------------------------------
def topic_allowed(topic: str, action: str, device_id: str) -> tuple[bool, str]:
    """Whether ``device_id`` may publish/subscribe to ``topic``.

    Mirrors :func:`apps.devices.emqx.emqx_acl`, minus the database lookup that
    maps a username back to a device - the harness already knows which device
    is on the connection because it authenticated it.
    """
    from apps.devices.emqx import _PUBLISHABLE, _SUBSCRIBABLE, _split_topic

    split = _split_topic(topic)
    if split is None:
        return False, f"topic 不在 {topics.root()}/<device_id>/... 這個結構底下"

    topic_device, suffix = split
    if topic_device != device_id:
        return False, f"topic 屬於 {topic_device!r}，但這條連線的設備是 {device_id!r}"

    if action == "publish":
        if suffix in _PUBLISHABLE:
            return True, ""
        return False, (
            f"設備不可發布到 {suffix!r}；可發布的是 "
            f"{'、'.join(sorted(_PUBLISHABLE))}"
        )

    if action == "subscribe":
        if suffix in _SUBSCRIBABLE:
            return True, ""
        return False, (
            f"設備不可訂閱 {suffix!r}；可訂閱的只有 "
            f"{'、'.join(sorted(_SUBSCRIBABLE))}"
        )

    return False, f"未知的動作 {action!r}"


# ---------------------------------------------------------------------------
# PUBLISH
# ---------------------------------------------------------------------------
@dataclass
class MessageRecord:
    """One received message, as shown in the live log."""

    received_at: dt.datetime
    topic: str
    qos: int
    retain: bool
    payload: bytes
    kind: str = ""
    accepted: bool = False
    reason: str = ""
    parsed: dict[str, Any] = field(default_factory=dict)

    @property
    def payload_text(self) -> str:
        return _preview(self.payload, limit=400)


def check_publish(
    checks: dict[str, Check],
    packet,
    device_id: str,
    *,
    seen_kinds: set[str],
) -> MessageRecord:
    """Validate one PUBLISH exactly as the ingestor would, and score it."""
    from services.ingestor import protocol

    record = MessageRecord(
        received_at=now(),
        topic=packet.topic,
        qos=packet.qos,
        retain=packet.retain,
        payload=packet.payload,
    )

    allowed, reason = topic_allowed(packet.topic, "publish", device_id)
    if not allowed:
        record.reason = reason
        checks["publish_acl"].fail(packet.topic, reason)
        return record
    if checks["publish_acl"].status != FAIL:
        checks["publish_acl"].succeed(packet.topic)

    parsed_topic = topics.parse(packet.topic)
    if parsed_topic is None:
        record.reason = "topic 無法解析"
        checks["publish_acl"].fail(packet.topic, record.reason)
        return record
    record.kind = parsed_topic.kind

    # -- QoS
    if packet.qos == 1:
        if checks["publish_qos"].status != FAIL:
            checks["publish_qos"].succeed("1")
    else:
        checks["publish_qos"].fail(
            str(packet.qos),
            f"{packet.topic} 用了 QoS {packet.qos}。上行一律要 QoS 1，"
            "QoS 0 在網路不穩時會靜靜地掉資料。",
        )

    # -- payload, through the production validators
    try:
        document = protocol.decode(packet.payload)
    except protocol.ProtocolError as exc:
        record.reason = f"[{exc.reason}] {exc}"
        checks["payload_schema"].fail(record.payload_text, record.reason)
        return record

    try:
        protocol.validate(record.kind, document)
    except protocol.ProtocolError as exc:
        record.reason = f"[{exc.reason}] {exc}"
        checks["payload_schema"].fail(record.payload_text, record.reason)
        return record

    record.parsed = document
    record.accepted = True
    if checks["payload_schema"].status != FAIL:
        checks["payload_schema"].succeed(f"{record.kind} 通過")

    seen_kinds.add(record.kind)
    _score_kind(checks, record, document)
    return record


def _score_kind(checks: dict, record: MessageRecord, document: dict) -> None:
    if record.kind == topics.TELEMETRY:
        checks["telemetry_seen"].succeed(f"{record.topic}")
    elif record.kind == topics.STATUS and document.get("status") == "online":
        checks["birth_status"].succeed('status="online"')
        if record.retain:
            checks["birth_retained"].succeed("retain=true")
        else:
            checks["birth_retained"].fail(
                "retain=false",
                "上線的 status 訊息要設 retained，否則重新連線的 console 看不到"
                "設備目前的狀態。",
            )
    elif record.kind == topics.CONTROL_ACK:
        checks["command_ack"].succeed(
            f"command_id={document.get('command_id')} status={document.get('status')}"
        )


# ---------------------------------------------------------------------------
# SUBSCRIBE
# ---------------------------------------------------------------------------
def check_subscribe(
    checks: dict[str, Check], filters: list[tuple[str, int]], device_id: str
) -> list[int]:
    """Score a SUBSCRIBE and return the granted QoS per filter (0x80 = refused)."""
    granted: list[int] = []
    control_topic = f"{topics.root()}/{device_id}/{topics.CONTROL}"

    for topic, qos in filters:
        allowed, reason = topic_allowed(topic, "subscribe", device_id)
        if not allowed:
            checks["subscribe_acl"].fail(topic, reason)
            granted.append(0x80)
            continue

        if checks["subscribe_acl"].status != FAIL:
            checks["subscribe_acl"].succeed(topic)
        if topic == control_topic:
            checks["subscribe_control"].succeed(topic)

        if qos == 1:
            if checks["subscribe_qos"].status != FAIL:
                checks["subscribe_qos"].succeed("1")
        else:
            checks["subscribe_qos"].warn(
                str(qos),
                f"以 QoS {qos} 訂閱 control。命令是 QoS 1 下發的，"
                "訂閱端用 QoS 0 會讓 broker 降級交付。",
            )
        granted.append(min(qos, 1))

    return granted


def _preview(raw: bytes, *, limit: int = 200) -> str:
    text = raw.decode("utf-8", errors="replace")
    return text if len(text) <= limit else text[:limit] + "…"

