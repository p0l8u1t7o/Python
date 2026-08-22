"""Conformance checks for an edge node connecting to the test harness.

**The first principle of this module: it does not restate the platform's
rules, it calls them.**

A harness that re-implements "what a valid payload looks like" drifts from the
real ingestor the moment either side changes, and a passing test then means
nothing. So credentials go through
:func:`apps.devices.edge_nodes.authenticate_edge_node`, topic permission goes
through the same grammar the EMQX ACL webhook uses, and payloads go through
:func:`services.sparkplug.payload.decode` - the very function that runs in
production before anything reaches the queue.

Where the harness is deliberately **stricter** than production it says so in
the check's own description, and :data:`STRICTER_THAN_PRODUCTION` lists them.
Stricter is safe; looser would be a lie.

Three of these checks read backwards to anyone applying ordinary MQTT habits,
and none of them is a mistake:

* **clean session must now be true.** Sparkplug forbids a persistent session,
  because a queued command replayed after a reconnect would be applied against
  state the host has since re-announced.
* **the will must not be retained.** A retained NDEATH outlives the session it
  describes and would tell every future subscriber that a live node is dead.
* **uplinks are QoS 0.** Ordering and loss detection come from ``seq`` and are
  recovered by asking for a rebirth; QoS 1 would add duplicates without adding
  safety.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings

from apps.core.timeutils import now
from services.sparkplug import payload as sp
from services.sparkplug import topics
from services.sparkplug.topics import MessageType

PASS = "pass"
FAIL = "fail"
WARN = "warn"
PENDING = "pending"

#: Checks the harness enforces that production tolerates. Being stricter here
#: is intentional - it catches things that would work today but break the first
#: time an operator turns the corresponding safeguard on.
STRICTER_THAN_PRODUCTION = {
    "client_id_format": (
        "Production only pins the client id when EdgeNodeCredential."
        "allowed_client_id is set, and it is empty by default. The harness "
        "always requires zqs:<edge_node_id>."
    ),
    "keepalive_range": (
        "Any keepalive is legal MQTT. The protocol document recommends 45 s."
    ),
    "birth_aliases": (
        "A birth without aliases is valid Sparkplug and the platform accepts "
        "it. The harness asks for them because the whole point of the birth "
        "table is that DATA afterwards is compact."
    ),
    "publish_qos": (
        "The platform accepts any QoS. The specification fixes uplinks at 0, "
        "and a device using 1 will interoperate badly with other Sparkplug "
        "hosts even though this one tolerates it."
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

    def fail(self, actual: str = "", detail: str = "") -> None:
        self.status = FAIL
        self.actual = actual
        self.detail = detail

    def warn(self, actual: str = "", detail: str = "") -> None:
        self.status = WARN
        self.actual = actual
        self.detail = detail


def build_checklist(group_id: str, node_id: str) -> dict[str, Check]:
    """The full acceptance list, in the order an edge node exercises it."""
    ndeath = topics.build(group_id, MessageType.NDEATH, node_id)
    ncmd = topics.build(group_id, MessageType.NCMD, node_id)
    return {
        check.key: check
        for check in [
            # ---- CONNECT ------------------------------------------------
            Check(
                "mqtt_version",
                "MQTT 協定版本",
                expected="3.1.1（protocol level 4）或 5.0（level 5）",
            ),
            Check("client_id_format", "Client ID 格式", expected=f"zqs:{node_id}"),
            Check(
                "username_format",
                "Username 格式",
                expected="node-<group_id>-<edge_node_id>",
            ),
            Check(
                "credentials",
                "帳號密碼驗證",
                expected="通過 authenticate_edge_node()（與正式環境同一個函式）",
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
                expected="true（Sparkplug 規定，不可保留 session）",
            ),
            Check("lwt_declared", "NDEATH 已宣告為遺言", expected="CONNECT 帶 will flag"),
            Check("lwt_topic", "遺言 topic", expected=ndeath),
            Check("lwt_qos", "遺言 QoS", expected="1"),
            Check("lwt_retain", "遺言 retained", expected="false（規範要求）"),
            Check(
                "lwt_payload",
                "遺言 payload",
                expected="Sparkplug protobuf，含 bdSeq metric",
            ),
            # ---- SUBSCRIBE ----------------------------------------------
            Check("subscribe_ncmd", "訂閱 NCMD", expected=ncmd),
            Check(
                "subscribe_dcmd",
                "訂閱 DCMD",
                expected=f"{topics.build(group_id, MessageType.DCMD, node_id)}/+",
                required=False,
            ),
            Check("subscribe_acl", "訂閱權限（ACL）", expected="只訂閱自己的命令 topic"),
            # ---- BIRTH ---------------------------------------------------
            Check("nbirth_seen", "發布 NBIRTH", expected="連線後立即發布"),
            Check("nbirth_seq", "NBIRTH 的 seq", expected="0（規範要求）"),
            Check(
                "nbirth_bdseq",
                "NBIRTH 的 bdSeq",
                expected="存在，且與遺言中的 bdSeq 相同",
            ),
            Check(
                "nbirth_rebirth_metric",
                "宣告 Node Control/Rebirth",
                expected="NBIRTH 要帶這個可寫 metric，主機才有辦法要求重生",
            ),
            Check("dbirth_seen", "發布 DBIRTH", expected="每台設備各一則"),
            Check(
                "birth_aliases",
                "BIRTH 指派 alias",
                expected="每個 metric 都帶 alias",
                required=False,
            ),
            # ---- DATA ----------------------------------------------------
            Check("publish_acl", "發布權限（ACL）", expected="只發布到自己的位址"),
            Check("publish_qos", "上行 QoS", expected="0（規範要求）", required=False),
            Check("publish_retain", "上行 retain", expected="false（規範要求）"),
            Check(
                "payload_schema",
                "Payload 通過正式解碼器",
                expected="與 ingestor 相同的 sparkplug decode()",
            ),
            Check("ddata_seen", "收到 DDATA", expected="至少一則"),
            Check(
                "seq_monotonic",
                "seq 連續遞增",
                expected="每則訊息 +1，到 255 後回到 0",
            ),
            # ---- 互動 -----------------------------------------------------
            Check(
                "command_ack",
                "命令回覆",
                expected="收到 DCMD 後以 DDATA 回報 Command/ID 與 Command/Status",
                required=False,
            ),
            Check(
                "rebirth_honoured",
                "回應 Rebirth 要求",
                expected="收到 Node Control/Rebirth=true 後重新發布 NBIRTH",
                required=False,
            ),
            Check(
                "lwt_delivered",
                "遺言實測",
                expected="強制斷線後 broker 確實送出 NDEATH",
                required=False,
            ),
        ]
    }


# ---------------------------------------------------------------------------
# CONNECT
# ---------------------------------------------------------------------------
def check_connect(
    checks: dict[str, Check], packet, group_id: str, node_id: str
) -> list[str]:
    """Run every CONNECT-time check. Returns the keys that failed."""
    level = packet.protocol_level
    if level in (4, 5):
        checks["mqtt_version"].succeed(
            f"protocol level {level}（{'3.1.1' if level == 4 else '5.0'}）"
        )
    else:
        checks["mqtt_version"].fail(
            f"protocol level {level}",
            "只接受 3.1.1（level 4）或 5.0（level 5）。",
        )

    expected_client_id = f"{settings.MQTT['CLIENT_ID_PREFIX']}:{node_id}"
    if packet.client_id == expected_client_id:
        checks["client_id_format"].succeed(packet.client_id)
    else:
        checks["client_id_format"].fail(
            packet.client_id or "(空字串)",
            f"應為 {expected_client_id!r}，實際收到 {packet.client_id!r}。"
            "ACL webhook 可以把 client id 釘選成這個值。",
        )

    username = packet.username or ""
    if not username:
        checks["username_format"].fail("(未提供)", "CONNECT 沒有帶 username。")
    elif username.startswith("node-") and username.endswith(f"-{node_id}"):
        checks["username_format"].succeed(username)
    else:
        checks["username_format"].fail(
            username,
            f"應為 node-<group_id>-{node_id}，實際收到 {username!r}。"
            "這串是註冊 edge node 時系統發給你的，不要自己編。",
        )

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

    # Sparkplug requires a *clean* session, and the reason is specific: a
    # persistent session lets the broker replay a command queued before the
    # disconnect,
    # which would then be applied against state the node has already
    # re-announced in its new NBIRTH.
    if packet.clean_session:
        checks["clean_session"].succeed("true")
    else:
        checks["clean_session"].fail(
            "false",
            "Sparkplug 要求 clean session = true（MQTT 5 則是 Clean Start "
            "= true 且 Session Expiry = 0）。保留 session 會讓 broker 把斷線前"
            "排隊的命令在重連後補送，而那時節點已經重新宣告過狀態了。",
        )

    if not packet.will_flag:
        checks["lwt_declared"].fail(
            "未宣告",
            "CONNECT 沒有設 will flag。沒有 NDEATH 的話，設備突然斷電時平台"
            "完全不會知道——這一項最容易被忽略，也最容易在正式環境出事。",
        )
        for key in ("lwt_topic", "lwt_qos", "lwt_retain", "lwt_payload"):
            checks[key].fail("(未宣告遺言)")
    else:
        checks["lwt_declared"].succeed("已宣告")
        _check_will(checks, packet, group_id, node_id)

    return [key for key, check in checks.items() if check.status == FAIL]


def _check_will(checks: dict[str, Check], packet, group_id: str, node_id: str) -> None:
    expected_topic = topics.build(group_id, MessageType.NDEATH, node_id)
    if packet.will_topic == expected_topic:
        checks["lwt_topic"].succeed(packet.will_topic)
    else:
        checks["lwt_topic"].fail(
            packet.will_topic or "(空字串)",
            f"應為 {expected_topic!r}。遺言要發到 NDEATH topic，平台才會把它"
            "當成離線通知。",
        )

    if packet.will_qos == 1:
        checks["lwt_qos"].succeed("1")
    else:
        checks["lwt_qos"].fail(
            str(packet.will_qos),
            "遺言必須是 QoS 1。這是整個命名空間裡唯一不是 QoS 0 的上行訊息，"
            "因為遺言掉了就沒有第二次機會。",
        )

    # A retained will outlives the session it describes: every future
    # subscriber would be told this node is dead, including after it has
    # reconnected and re-announced itself.
    if packet.will_retain:
        checks["lwt_retain"].fail(
            "true",
            "遺言不可 retained。retained 的 NDEATH 會比它描述的那次連線活得更久，"
            "之後任何訂閱者一連上來就會被告知這個節點已經死了——即使它早就回來了。",
        )
    else:
        checks["lwt_retain"].succeed("false")

    try:
        view = sp.decode(packet.will_payload)
    except sp.PayloadError as exc:
        checks["lwt_payload"].fail(
            _preview(packet.will_payload), f"遺言內容不是合法的 Sparkplug payload：{exc}"
        )
        return

    bd_seq = sp.bd_seq_of(view)
    if bd_seq is None:
        checks["lwt_payload"].fail(
            _preview(packet.will_payload),
            "遺言必須帶 bdSeq metric。沒有它，平台無法分辨這則遺言屬於哪一次"
            "連線，也就無法忽略掉重連之後才姍姍來遲的舊遺言。",
        )
        return

    checks["lwt_payload"].succeed(f"bdSeq={bd_seq}")


# ---------------------------------------------------------------------------
# Credentials - straight through the production function
# ---------------------------------------------------------------------------
def check_credentials(checks: dict[str, Check], packet) -> tuple[bool, str]:
    """Authenticate exactly as the EMQX webhook does.

    Returns ``(accepted, reason)``. The reason is written for a device author,
    not for a server log.
    """
    from apps.core.errors import PermissionDenied
    from apps.devices.edge_nodes import authenticate_edge_node

    username = packet.username or ""
    password = packet.password or ""

    if not username or not password:
        reason = "CONNECT 缺少 username 或 password。"
        checks["credentials"].fail("(缺少憑證)", reason)
        return False, reason

    try:
        node = authenticate_edge_node(username, password, client_id=packet.client_id)
    except PermissionDenied as exc:
        reason = f"client id 與註冊時釘選的值不符：{exc}"
        checks["credentials"].fail(packet.client_id, reason)
        return False, reason
    except Exception as exc:  # noqa: BLE001 - report, do not crash the harness
        reason = f"驗證時發生錯誤：{exc!r}"
        checks["credentials"].fail(username, reason)
        return False, reason

    if node is None:
        reason = (
            "帳號或密碼不正確，或該 edge node 已停用。密碼只在註冊（或輪替）時"
            "顯示一次，如果弄丟了就到 console 重新產生。"
        )
        checks["credentials"].fail(username, reason)
        return False, reason

    checks["credentials"].succeed(f"{username} → {node.node_id}")
    return True, ""


# ---------------------------------------------------------------------------
# ACL - the same grammar the webhook uses
# ---------------------------------------------------------------------------
def topic_allowed(
    topic: str, action: str, group_id: str, node_id: str
) -> tuple[bool, str]:
    """Whether this node may publish/subscribe to ``topic``.

    Mirrors :func:`apps.devices.emqx.emqx_acl`, minus the database lookup that
    maps a username back to a node - the harness already knows which node is on
    the connection because it authenticated it.
    """
    from apps.devices.emqx import _PUBLISHABLE, _SUBSCRIBABLE

    parsed = (
        topics.parse_subscription(topic)
        if action == "subscribe"
        else topics.parse(topic)
    )
    if parsed is None:
        return False, f"topic 不符合 Sparkplug 命名空間：{topics.NAMESPACE}/..."

    if parsed.group_id != group_id:
        return False, f"topic 的 group 是 {parsed.group_id!r}，這條連線屬於 {group_id!r}"
    if parsed.edge_node_id != node_id:
        return False, (
            f"topic 屬於節點 {parsed.edge_node_id!r}，但這條連線的節點是 {node_id!r}"
        )

    if action == "publish":
        if parsed.message_type in _PUBLISHABLE:
            return True, ""
        return False, (
            f"設備不可發布 {parsed.message_type}；可發布的是 "
            f"{'、'.join(sorted(str(t) for t in _PUBLISHABLE))}"
        )

    if action == "subscribe":
        if parsed.message_type in _SUBSCRIBABLE:
            return True, ""
        return False, (
            f"設備不可訂閱 {parsed.message_type}；可訂閱的只有 "
            f"{'、'.join(sorted(str(t) for t in _SUBSCRIBABLE))}"
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


class SequenceTracker:
    """Follows the node's ``seq`` counter across a session.

    Kept as an object rather than a module global because a self-test run and a
    real device run can overlap, and a shared counter would report a gap that
    neither device caused.
    """

    def __init__(self) -> None:
        self.last: int | None = None
        self.bd_seq: int | None = None

    def observe(self, seq: int | None, *, is_birth: bool = False) -> str:
        if seq is None:
            return "payload 沒有 seq 欄位；除了 NDEATH 以外每則訊息都必須帶。"

        # An NBIRTH restarts the sequence at zero - that is the point of it.
        # Comparing it against what came before would report a gap every time
        # a node answers a rebirth request, which is the one situation where
        # the host has just *asked* for the counter to be reset.
        if is_birth:
            self.last = seq
            return ""

        if self.last is None:
            self.last = seq
            return ""
        expected = sp.next_seq(self.last)
        self.last = seq
        if seq != expected:
            return f"seq 應為 {expected}，實際收到 {seq}。"
        return ""


def check_publish(
    checks: dict[str, Check],
    packet,
    group_id: str,
    node_id: str,
    *,
    seen_kinds: set[str],
    tracker: SequenceTracker,
) -> MessageRecord:
    """Validate one PUBLISH exactly as the ingestor would, and score it."""
    record = MessageRecord(
        received_at=now(),
        topic=packet.topic,
        qos=packet.qos,
        retain=packet.retain,
        payload=packet.payload,
    )

    allowed, reason = topic_allowed(packet.topic, "publish", group_id, node_id)
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
    record.kind = str(parsed_topic.message_type)

    if packet.qos == 0:
        if checks["publish_qos"].status != FAIL:
            checks["publish_qos"].succeed("0")
    else:
        checks["publish_qos"].warn(
            str(packet.qos),
            f"{packet.topic} 用了 QoS {packet.qos}。Sparkplug 規定上行一律 QoS 0——"
            "順序與遺失偵測靠的是 seq，不是 broker 重送；QoS 1 只會多出重複訊息。",
        )

    if packet.retain:
        checks["publish_retain"].fail(
            "true",
            f"{packet.topic} 設了 retain。Sparkplug 命名空間裡唯一 retained 的是"
            "主機的 STATE topic；節點的訊息一律不 retain。",
        )
    elif checks["publish_retain"].status != FAIL:
        checks["publish_retain"].succeed("false")

    try:
        view = sp.decode(packet.payload)
    except sp.PayloadError as exc:
        record.reason = f"[{exc.reason}] {exc}"
        checks["payload_schema"].fail(record.payload_text, record.reason)
        return record

    record.parsed = {
        "seq": view.seq,
        "metrics": [
            {"name": m.name, "alias": m.alias, "value": m.value} for m in view.metrics
        ],
    }
    record.accepted = True
    if checks["payload_schema"].status != FAIL:
        checks["payload_schema"].succeed(f"{record.kind} 解碼成功")

    # NDEATH is the one message with no seq, by design: the broker publishes it
    # at a moment the node cannot predict.
    if parsed_topic.message_type is not MessageType.NDEATH:
        problem = tracker.observe(
            view.seq, is_birth=parsed_topic.message_type is MessageType.NBIRTH
        )
        if problem:
            checks["seq_monotonic"].fail(str(view.seq), problem)
        elif checks["seq_monotonic"].status != FAIL:
            checks["seq_monotonic"].succeed(f"seq={view.seq}")

    seen_kinds.add(record.kind)
    _score_kind(checks, record, view, tracker)
    return record


def _score_kind(
    checks: dict, record: MessageRecord, view, tracker: SequenceTracker
) -> None:
    from services.sparkplug import profile

    names = {metric.name: metric for metric in view.metrics}

    if record.kind == MessageType.NBIRTH:
        checks["nbirth_seen"].succeed(record.topic)

        if view.seq == 0:
            checks["nbirth_seq"].succeed("0")
        else:
            checks["nbirth_seq"].fail(
                str(view.seq),
                "NBIRTH 的 seq 必須是 0。它是序號的起點，主機就是靠這一則"
                "重新對齊計數器的。",
            )

        bd_seq = sp.bd_seq_of(view)
        if bd_seq is None:
            checks["nbirth_bdseq"].fail("(沒有 bdSeq)", "NBIRTH 必須帶 bdSeq metric。")
        elif tracker.bd_seq is not None and bd_seq != tracker.bd_seq:
            checks["nbirth_bdseq"].fail(
                str(bd_seq),
                f"NBIRTH 的 bdSeq 是 {bd_seq}，但遺言裡宣告的是 {tracker.bd_seq}。"
                "兩者必須相同，平台才能把死亡對應到它結束的那一次連線。",
            )
        else:
            checks["nbirth_bdseq"].succeed(str(bd_seq))

        if sp.NODE_REBIRTH_METRIC in names:
            checks["nbirth_rebirth_metric"].succeed(sp.NODE_REBIRTH_METRIC)
        else:
            checks["nbirth_rebirth_metric"].fail(
                "(未宣告)",
                f"NBIRTH 要宣告可寫的 {sp.NODE_REBIRTH_METRIC!r}。少了它，一旦訊息"
                "遺失，主機就沒有任何辦法要求節點重新宣告，兩邊會永遠對不齊。",
            )

    elif record.kind == MessageType.DBIRTH:
        checks["dbirth_seen"].succeed(record.topic)
        measurements = [
            m
            for m in view.metrics
            if m.name and not profile.is_reserved(m.name)
        ]
        without_alias = [m.name for m in measurements if m.alias is None]
        if not measurements:
            checks["birth_aliases"].warn("(沒有量測 metric)")
        elif without_alias:
            checks["birth_aliases"].warn(
                f"{len(without_alias)}/{len(measurements)} 個沒有 alias",
                "BIRTH 沒有指派 alias 也能運作，但之後每則 DDATA 都得重複完整的"
                "metric 名稱——Sparkplug 省頻寬的效果就沒了。範例："
                f"{'、'.join(without_alias[:3])}",
            )
        else:
            checks["birth_aliases"].succeed(f"{len(measurements)} 個 metric 都有 alias")

    elif record.kind == MessageType.DDATA:
        checks["ddata_seen"].succeed(record.topic)
        if profile.COMMAND_ID in names and profile.COMMAND_STATUS in names:
            checks["command_ack"].succeed(
                f"Command/ID={names[profile.COMMAND_ID].value} "
                f"status={names[profile.COMMAND_STATUS].value}"
            )


# ---------------------------------------------------------------------------
# SUBSCRIBE
# ---------------------------------------------------------------------------
def check_subscribe(
    checks: dict[str, Check],
    filters: list[tuple[str, int]],
    group_id: str,
    node_id: str,
) -> list[int]:
    """Score a SUBSCRIBE and return the granted QoS per filter (0x80 = refused)."""
    granted: list[int] = []
    ncmd = topics.build(group_id, MessageType.NCMD, node_id)

    for topic, qos in filters:
        allowed, reason = topic_allowed(topic, "subscribe", group_id, node_id)
        if not allowed:
            checks["subscribe_acl"].fail(topic, reason)
            granted.append(0x80)
            continue

        if checks["subscribe_acl"].status != FAIL:
            checks["subscribe_acl"].succeed(topic)

        parsed = topics.parse_subscription(topic)
        if topic == ncmd:
            checks["subscribe_ncmd"].succeed(topic)
        elif parsed is not None and parsed.message_type is MessageType.DCMD:
            checks["subscribe_dcmd"].succeed(topic)

        granted.append(min(qos, 1))

    return granted


def _preview(raw: bytes, *, limit: int = 200) -> str:
    """Render a protobuf payload for a human.

    Hex rather than a decode attempt: the payload may be exactly the thing that
    failed to decode, and a traceback in the preview column helps nobody.
    """
    text = raw.hex()
    prefix = f"{len(raw)} bytes: "
    return prefix + (text if len(text) <= limit else text[:limit] + "…")
