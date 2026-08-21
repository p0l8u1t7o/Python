"""A conformance harness that speaks MQTT 3.1.1.

**This is not a production broker and must never be used as one.** It is a test
fixture that happens to accept MQTT connections, so that a device author can
find out *why* a connection would be refused instead of only that it was.

Why a purpose-built listener rather than a real broker: EMQX answers a failed
CONNECT with a single return code. "Bad username or password" does not tell you
that your client id was `LabVIEW_1` instead of `zqs:ZQS-BESS-0001`, and nothing
at all tells you that you forgot the last will. Sitting on the socket is the
only place where every one of those facts is visible at once.

Everything it judges, it judges with the platform's own code - see
:mod:`services.harness.checks`. Where it is stricter, it says so.

What it deliberately does **not** emulate, and therefore cannot prove:

* retained-message replay to a later subscriber
* session persistence across a reconnect with ``clean_session=false``
* shared subscriptions (``$share/...``), which only the ingestor uses
* QoS 2, TLS, and MQTT 5 properties

Those need a smoke test against real EMQX before going live. The final report
says so too.
"""

from __future__ import annotations

import socket
import socketserver
import sys
import threading
import uuid
from dataclasses import dataclass, field
from typing import Callable

import orjson
from django.db import connections

from apps.core.logging import get_logger
from apps.core.timeutils import now
from services.harness import checks as conformance
from services.harness import packets
from services.mqtt import topics

logger = get_logger("harness.broker")

#: Sockets block forever by default; a bounded read lets the loop notice a
#: shutdown request and lets the keepalive check actually fire.
SOCKET_TIMEOUT_SECONDS = 1.0


@dataclass
class Session:
    """One connected device, and everything observed about it."""

    device_id: str
    connect: packets.ConnectPacket
    checks: dict[str, conformance.Check]
    address: str
    connected_at: object = field(default_factory=now)
    subscriptions: set[str] = field(default_factory=set)
    messages: list[conformance.MessageRecord] = field(default_factory=list)
    seen_kinds: set[str] = field(default_factory=set)
    #: Set once the peer sends DISCONNECT, so an abrupt drop can be told apart
    #: from a polite goodbye - which is exactly the difference the will exists
    #: to signal.
    graceful_disconnect: bool = False
    will_published: bool = False


class HarnessState:
    """Shared state across connections. One harness, one device at a time."""

    def __init__(self, *, on_event: Callable[[str, dict], None] | None = None) -> None:
        self._lock = threading.RLock()
        self.sessions: dict[str, Session] = {}
        self.handlers: dict[str, "DeviceHandler"] = {}
        self.history: list[conformance.MessageRecord] = []
        self._on_event = on_event

    def emit(self, kind: str, payload: dict) -> None:
        if self._on_event is not None:
            try:
                self._on_event(kind, payload)
            except Exception:  # noqa: BLE001 - a bad display must not kill ingest
                logger.exception("harness event handler failed")

    def register(self, session: Session, handler: "DeviceHandler") -> None:
        with self._lock:
            self.sessions[session.device_id] = session
            self.handlers[session.device_id] = handler

    def unregister(self, device_id: str) -> None:
        with self._lock:
            self.handlers.pop(device_id, None)

    def handler_for(self, device_id: str) -> "DeviceHandler | None":
        with self._lock:
            return self.handlers.get(device_id)

    def session_for(self, device_id: str) -> Session | None:
        with self._lock:
            return self.sessions.get(device_id)

    def only_session(self) -> Session | None:
        with self._lock:
            return next(iter(self.sessions.values()), None)


class DeviceHandler(socketserver.StreamRequestHandler):
    """Handles one device connection from CONNECT to disconnect."""

    timeout = None

    @property
    def state(self) -> HarnessState:
        return self.server.state

    def setup(self) -> None:  # noqa: D102 - socketserver hook
        super().setup()
        self.connection.settimeout(SOCKET_TIMEOUT_SECONDS)
        self.session: Session | None = None
        self._write_lock = threading.Lock()
        self._next_packet_id = 1

    # ---- socket helpers --------------------------------------------------
    def send(self, data: bytes) -> None:
        with self._write_lock:
            try:
                self.wfile.write(data)
                self.wfile.flush()
            except OSError:
                pass

    def next_packet_id(self) -> int:
        self._next_packet_id = (self._next_packet_id % 0xFFFF) + 1
        return self._next_packet_id

    # ---- main loop -------------------------------------------------------
    def handle(self) -> None:  # noqa: D102 - socketserver hook
        peer = f"{self.client_address[0]}:{self.client_address[1]}"
        self.state.emit("connection", {"peer": peer, "phase": "opened"})

        try:
            if not self._handle_connect(peer):
                return
            self._serve()
        except packets.MalformedPacket as exc:
            self.state.emit(
                "error",
                {"peer": peer, "message": f"封包格式錯誤，連線中止：{exc}"},
            )
        except (ConnectionError, OSError):
            pass
        except Exception as exc:  # noqa: BLE001
            # socketserver's default is to dump a traceback to stderr and carry
            # on. For a device author that traceback is noise arriving in the
            # middle of their message log, and it buries the fact that this
            # connection was abandoned. Say so in their language instead.
            logger.exception("harness connection failed")
            self.state.emit(
                "error",
                {
                    "peer": peer,
                    "message": (
                        f"測試工具處理這條連線時發生內部錯誤，已中止：{exc!r}\n"
                        "   這是工具的問題，不是設備的問題；請回報這段訊息。"
                    ),
                },
            )
        finally:
            self._finish_session(peer)
            # Django opens a database connection per thread and closes it only
            # at the end of a request. There are no requests here, so without
            # this every device connection would leak one - and a long test
            # session, or a device that reconnects in a loop, eventually
            # exhausts the handles and fails with "unable to open database
            # file" in the middle of an otherwise healthy run.
            connections.close_all()

    def _handle_connect(self, peer: str) -> bool:
        packet = self._read_packet(first=True)
        if packet is None:
            return False

        if packet.packet_type != packets.CONNECT:
            self.state.emit(
                "error",
                {
                    "peer": peer,
                    "message": (
                        f"第一個封包必須是 CONNECT，實際收到 {packet.name}。"
                        "MQTT 規定連線後的第一個控制封包就是 CONNECT。"
                    ),
                },
            )
            return False

        connect = packets.decode_connect(packet.body)

        # The device id is taken from the *username*, which is the field the
        # platform actually issued. Deriving it from the client id would make
        # the client-id check circular - it could never fail.
        device_id = _device_id_from_username(connect.username or "")
        if not device_id:
            self.send(packets.encode_connack(packets.CONNACK_BAD_CREDENTIALS))
            self.state.emit(
                "error",
                {
                    "peer": peer,
                    "message": (
                        f"無法從 username {connect.username!r} 判斷設備。"
                        "username 應為 dev-<組織代碼>-<device_id>，"
                        "是註冊設備時系統發給你的。"
                    ),
                },
            )
            return False

        checks = conformance.build_checklist(device_id)
        conformance.check_connect(checks, connect, device_id)
        accepted, reason = conformance.check_credentials(checks, connect)

        session = Session(
            device_id=device_id, connect=connect, checks=checks, address=peer
        )
        self.session = session
        self.state.register(session, self)
        self.state.emit(
            "connect",
            {
                "peer": peer,
                "device_id": device_id,
                "client_id": connect.client_id,
                "accepted": accepted,
                "checks": checks,
            },
        )

        if not accepted:
            self.send(packets.encode_connack(packets.CONNACK_BAD_CREDENTIALS))
            self.state.emit("error", {"peer": peer, "message": reason})
            return False

        self.send(packets.encode_connack(packets.CONNACK_ACCEPTED))
        return True

    def _serve(self) -> None:
        while not self.server.stopping.is_set():
            packet = self._read_packet()
            if packet is None:
                return
            if packet.packet_type == packets.PUBLISH:
                self._on_publish(packet)
            elif packet.packet_type == packets.SUBSCRIBE:
                self._on_subscribe(packet)
            elif packet.packet_type == packets.UNSUBSCRIBE:
                self._on_unsubscribe(packet)
            elif packet.packet_type == packets.PINGREQ:
                self.send(packets.encode_pingresp())
            elif packet.packet_type == packets.PUBACK:
                self.state.emit(
                    "puback", {"packet_id": packets.decode_packet_id(packet.body)}
                )
            elif packet.packet_type == packets.DISCONNECT:
                if self.session:
                    self.session.graceful_disconnect = True
                return
            else:
                self.state.emit(
                    "error",
                    {
                        "peer": self.session.address if self.session else "",
                        "message": f"收到未支援的封包型別：{packet.name}",
                    },
                )

    def _read_packet(self, *, first: bool = False):
        while True:
            try:
                return packets.read_packet(self.rfile)
            except socket.timeout:
                if self.server.stopping.is_set():
                    return None
                if first:
                    continue
                continue

    # ---- packet handlers -------------------------------------------------
    def _on_publish(self, packet) -> None:
        session = self.session
        if session is None:
            return
        publish = packets.decode_publish(packet.flags, packet.body)

        record = conformance.check_publish(
            session.checks, publish, session.device_id, seen_kinds=session.seen_kinds
        )
        session.messages.append(record)
        self.state.history.append(record)
        self.state.emit("message", {"record": record, "device_id": session.device_id})

        if publish.qos == 1 and publish.packet_id is not None:
            self.send(packets.encode_puback(publish.packet_id))

    def _on_subscribe(self, packet) -> None:
        session = self.session
        if session is None:
            return
        if packet.flags != 0x02:
            self.state.emit(
                "error",
                {
                    "peer": session.address,
                    "message": (
                        f"SUBSCRIBE 的固定標頭旗標應為 0x02，實際為 "
                        f"0x{packet.flags:02x}（MQTT 3.1.1 §3.8.1）。"
                    ),
                },
            )

        subscribe = packets.decode_subscribe(packet.body)
        granted = conformance.check_subscribe(
            session.checks, subscribe.filters, session.device_id
        )
        for (topic, _qos), result in zip(subscribe.filters, granted):
            if result != 0x80:
                session.subscriptions.add(topic)
        self.send(packets.encode_suback(subscribe.packet_id, granted))
        self.state.emit(
            "subscribe",
            {
                "device_id": session.device_id,
                "filters": subscribe.filters,
                "granted": granted,
            },
        )

    def _on_unsubscribe(self, packet) -> None:
        session = self.session
        if session is None:
            return
        unsubscribe = packets.decode_unsubscribe(packet.body)
        for topic in unsubscribe.filters:
            session.subscriptions.discard(topic)
        self.send(packets.encode_unsuback(unsubscribe.packet_id))

    # ---- downlink --------------------------------------------------------
    def publish_to_device(self, topic: str, payload: bytes, *, qos: int = 1) -> bool:
        """Send a command down to this device. Returns whether it was subscribed."""
        session = self.session
        subscribed = session is not None and topic in session.subscriptions
        frame = packets.encode_publish(
            topic,
            payload,
            qos=qos,
            packet_id=self.next_packet_id() if qos > 0 else None,
        )
        self.send(frame)
        return subscribed

    # ---- teardown --------------------------------------------------------
    def _finish_session(self, peer: str) -> None:
        session = self.session
        if session is None:
            self.state.emit("connection", {"peer": peer, "phase": "closed"})
            return

        self.state.unregister(session.device_id)

        # The whole point of a will: an abrupt drop must produce the offline
        # notice, a polite DISCONNECT must not.
        if session.connect.will_flag and not session.graceful_disconnect:
            session.will_published = True
            session.checks["lwt_delivered"].succeed(
                f"{session.connect.will_topic}",
                "連線非正常關閉，broker 依 CONNECT 宣告的遺言送出離線通知。",
            )
            self.state.emit(
                "will",
                {
                    "device_id": session.device_id,
                    "topic": session.connect.will_topic,
                    "payload": session.connect.will_payload,
                },
            )
        elif session.graceful_disconnect:
            session.checks["lwt_delivered"].warn(
                "正常斷線，未觸發",
                "設備送了 DISCONNECT，依 MQTT 規定不發遺言——這是正確行為。"
                "要實測遺言請直接切斷網路或關閉設備電源。",
            )

        self.state.emit(
            "connection",
            {
                "peer": peer,
                "phase": "closed",
                "device_id": session.device_id,
                "graceful": session.graceful_disconnect,
            },
        )


class HarnessServer(socketserver.ThreadingTCPServer):
    #: POSIX only. On Windows SO_REUSEADDR does not mean "reuse a TIME_WAIT
    #: port", it means "bind a port someone else is actively listening on" -
    #: two listeners then split the incoming connections and the harness sees
    #: an arbitrary half of the traffic. Refusing to bind is far better than
    #: producing a report built from part of the conversation.
    allow_reuse_address = sys.platform != "win32"
    daemon_threads = True

    def __init__(self, address, state: HarnessState) -> None:
        self.state = state
        self.stopping = threading.Event()
        super().__init__(address, DeviceHandler)

    def shutdown_harness(self) -> None:
        self.stopping.set()
        self.shutdown()
        self.server_close()


def send_command(
    state: HarnessState,
    device_id: str,
    name: str,
    params: dict | None = None,
    *,
    timeout_seconds: int = 60,
) -> tuple[bool, str, str]:
    """Publish a downlink command in exactly the platform's envelope.

    Returns ``(delivered, command_id, note)``. ``delivered`` only means the
    bytes went out on a socket the device had subscribed on - whether it acts
    on them is what ``control/ack`` tells you.
    """
    handler = state.handler_for(device_id)
    if handler is None:
        return False, "", f"設備 {device_id!r} 目前沒有連線。"

    command_id = str(uuid.uuid4())
    issued_at = now()
    payload = {
        "command_id": command_id,
        "name": name,
        "params": params or {},
        "issued_at": int(issued_at.timestamp() * 1000),
        "expires_at": int(issued_at.timestamp() * 1000) + timeout_seconds * 1000,
        "reply_to": topics.device_topic(device_id, topics.CONTROL_ACK),
    }
    topic = topics.control_topic(device_id)
    subscribed = handler.publish_to_device(topic, orjson.dumps(payload))

    note = (
        ""
        if subscribed
        else f"注意：設備尚未訂閱 {topic}，命令送出了但對方收不到。"
    )
    return True, command_id, note


def _device_id_from_username(username: str) -> str:
    """``dev-<org slug>-<device id>`` → device id.

    The slug may itself contain dashes, so the split is anchored on the known
    ``dev-`` prefix and then matched against the registry rather than guessed
    positionally.
    """
    if not username.startswith("dev-"):
        return ""
    remainder = username[len("dev-") :]

    from apps.devices.models import DeviceCredential

    device_id = (
        DeviceCredential.objects.filter(mqtt_username=username)
        .values_list("device__device_id", flat=True)
        .first()
    )
    if device_id:
        return device_id

    # Unknown credential: fall back to the text after the first dash so the
    # checklist can still report *which* device the client claimed to be.
    return remainder.split("-", 1)[1] if "-" in remainder else remainder
