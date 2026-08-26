"""內建開發 broker 的連線偵錯外掛：把 CONNECT／SUBSCRIBE／PUBLISH／DISCONNECT 記進 IngressTrace。

EMQX 走 webhook 所以平台看得到每次認證；內建的 amqtt 是匿名的，沒有這一層。
少了它，設備商最常見的問題——「我到底有沒有連上 broker」——在整合頁上會是
一片空白。這個外掛掛在 amqtt 的事件上補這一段；只在偵錯開啟時寫，其餘
時間零成本。

amqtt 在 CONNECT 階段就拒絕的連線（協定版本不對、will flag 設了卻沒有 topic）
不會經過任何外掛 hook，只留下一行 WARNING；:func:`install_log_bridge` 把那幾行
接成 trace，這正是「為什麼連不上」最常見的答案。

所有寫入都走 :func:`services.diagnostics.trace_bg`：這個行程是 asyncio，Django ORM
不能在 event loop 執行緒上跑。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from amqtt.plugins.base import BasePlugin

from services import diagnostics as diag
from services.sparkplug import topics


def _node_from_topic(topic: str) -> tuple[str, str, str]:
    parsed = topics.parse(topic) or topics.parse_subscription(topic)
    if parsed is None:
        return "", "", ""
    return parsed.group_id, parsed.edge_node_id, str(parsed.message_type)


def _node_from_client(client_id: str) -> str:
    # 慣例 client id 是 zqs:<edge_node_id>；照著做的設備連 CONNECT 都能對上節點。
    return client_id.split(":", 1)[1] if client_id.startswith("zqs:") else ""


class TracePlugin(BasePlugin):
    """amqtt 依 ``on_<event>`` 命名找方法；沒定義的事件就不會被呼叫。"""

    @dataclass
    class Config:
        """amqtt 會用外掛的 Config 類別裝設定；沒有可設的東西也要給它一個空的。"""

    async def on_broker_client_connected(self, *, client_id: str, **_: Any) -> None:
        diag.trace_bg(
            diag.STAGE_BROKER, diag.OUTCOME_OK, edge_node_id=_node_from_client(client_id),
            kind="CONNECT", reason="connected", message=f"CONNECT 已接受，client id = {client_id}",
            detail={"client_id": client_id, "broker": "bundled"},
        )

    async def on_broker_client_disconnected(self, *, client_id: str, **_: Any) -> None:
        diag.trace_bg(
            diag.STAGE_BROKER, diag.OUTCOME_INFO, edge_node_id=_node_from_client(client_id),
            kind="DISCONNECT", reason="disconnected", message=f"連線結束，client id = {client_id}",
            detail={"client_id": client_id, "broker": "bundled"},
        )

    async def on_broker_client_subscribed(self, *, client_id: str, topic: str, qos: int, **_: Any) -> None:
        group, node, kind = _node_from_topic(topic)
        diag.trace_bg(
            diag.STAGE_BROKER, diag.OUTCOME_OK, group_id=group, edge_node_id=node or _node_from_client(client_id),
            topic=topic, kind=kind or "SUBSCRIBE", reason="subscribed", message=f"SUBSCRIBE {topic}（QoS {qos}）",
            detail={"client_id": client_id, "qos": qos},
        )

    async def on_mqtt_packet_received(self, *, packet: Any, session: Any = None, **_: Any) -> None:
        name = type(packet).__name__
        client_id = getattr(session, "client_id", None) or ""
        if name == "ConnectPacket":
            payload = getattr(packet, "payload", None)
            will = bool(getattr(packet, "will_flag", False))
            will_topic = str(getattr(payload, "will_topic", None) or "")
            clean = bool(getattr(packet, "clean_session_flag", True))
            keep = getattr(getattr(packet, "variable_header", None), "keep_alive", None)
            proto = getattr(packet, "proto_level", None)
            username = str(getattr(payload, "username", None) or "")
            cid = str(getattr(payload, "client_id", None) or client_id)
            problems = []
            if not will:
                problems.append("沒有遺言（will）：斷線後要 180 s 才會被判離線，且無法對上 bdSeq")
            elif not will_topic.startswith("spBv1.0/") or "/NDEATH/" not in will_topic:
                problems.append(f"遺言 topic 不是 NDEATH：{will_topic}")
            if not clean:
                problems.append("clean session 不是 true（規範要求）")
            group, node, _ = _node_from_topic(will_topic)
            diag.trace_bg(
                diag.STAGE_BROKER, diag.OUTCOME_WARNING if problems else diag.OUTCOME_OK,
                group_id=group, edge_node_id=node or _node_from_client(cid), topic=will_topic,
                kind="CONNECT", reason="connect",
                message="CONNECT：" + ("；".join(problems) if problems else "遺言、clean session、協定版本都正確"),
                detail={"client_id": cid, "username": username, "clean_session": clean, "keep_alive": keep,
                        "protocol_level": proto, "will": will, "will_topic": will_topic, "broker": "bundled"},
            )
        elif name == "PublishPacket":
            topic = str(getattr(packet, "topic_name", "") or "")
            group, node, kind = _node_from_topic(topic)
            data = bytes(getattr(packet, "data", None) or b"")
            diag.trace_bg(
                diag.STAGE_BROKER, diag.OUTCOME_OK if kind else diag.OUTCOME_WARNING,
                group_id=group, edge_node_id=node or _node_from_client(client_id), topic=topic,
                kind=kind or "PUBLISH", reason="publish" if kind else "publish_outside_namespace",
                message=f"PUBLISH {topic}（{len(data)} bytes, QoS {getattr(packet, 'qos', '?')}"
                        f"{', retain' if getattr(packet, 'retain_flag', False) else ''}）"
                        + ("" if kind else " — 不在 spBv1.0 命名空間，平台不會處理"),
                detail={"client_id": client_id, "qos": getattr(packet, "qos", None),
                        "retain": bool(getattr(packet, "retain_flag", False)), "broker": "bundled"},
                raw=data, size=len(data),
            )
        elif name == "DisconnectPacket":
            diag.trace_bg(
                diag.STAGE_BROKER, diag.OUTCOME_INFO, edge_node_id=_node_from_client(client_id),
                kind="DISCONNECT", reason="disconnect",
                message="收到 DISCONNECT：broker 會丟棄遺言；主動關機前應先自己發 NDEATH",
                detail={"client_id": client_id, "broker": "bundled"},
            )


# ---- CONNECT 階段就被拒絕的連線：只有 WARNING 可看 ---------------------------------
_PEER = re.compile(r"client @=([0-9a-fA-F.:\[\]]+)")
_HINTS = (
    (re.compile(r"Invalid protocol .*: 5"), "MQTT 5 不被內建開發 broker 接受：請改用 MQTT 3.1.1（正式環境的 EMQX 兩者都可）"),
    (re.compile(r"Invalid protocol"), "協定版本不被接受：請用 MQTT 3.1.1"),
    (re.compile(r"[Ww]ill flag set, but will topic/message not present"),
     "CONNECT 設了 will flag 卻沒有 will topic／payload：遺言要帶 NDEATH topic 與 bdSeq payload"),
    (re.compile(r"Failed to initialize client session"), "CONNECT 在建立 session 時被拒絕"),
)


class _BrokerLogBridge(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = record.getMessage()
        except Exception:  # noqa: BLE001
            return
        if "Invalid connection from" in text:
            return  # 緊接著的那一行才有原因
        hint = next((h for pattern, h in _HINTS if pattern.search(text)), None)
        if hint is None:
            return
        peer = _PEER.search(text)
        diag.trace_bg(
            diag.STAGE_BROKER, diag.OUTCOME_REJECTED, kind="CONNECT", reason="connect_refused",
            message=f"{hint}（{text[:160]}）",
            detail={"peer": peer.group(1) if peer else "", "broker": "bundled"},
        )


def install_log_bridge() -> None:
    logger = logging.getLogger("amqtt.broker")
    if not any(isinstance(h, _BrokerLogBridge) for h in logger.handlers):
        logger.addHandler(_BrokerLogBridge(level=logging.WARNING))
