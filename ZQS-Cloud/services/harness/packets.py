"""MQTT 3.1.1 packet encoding and decoding.

Just enough of the wire format for the conformance harness: CONNECT, CONNACK,
PUBLISH, PUBACK, SUBSCRIBE, SUBACK, UNSUBSCRIBE, UNSUBACK, PING and DISCONNECT.

Deliberately a separate, dependency-free module. Packet parsing is where a
subtle mistake would silently corrupt every check the harness reports, so it is
kept pure - no sockets, no Django - and unit tested on its own.

Reference: MQTT Version 3.1.1, OASIS Standard, section 3.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

# ---- Control packet types (fixed header, high nibble) ----------------------
CONNECT = 1
CONNACK = 2
PUBLISH = 3
PUBACK = 4
PUBREC = 5
PUBREL = 6
PUBCOMP = 7
SUBSCRIBE = 8
SUBACK = 9
UNSUBSCRIBE = 10
UNSUBACK = 11
PINGREQ = 12
PINGRESP = 13
DISCONNECT = 14

PACKET_NAMES = {
    CONNECT: "CONNECT",
    CONNACK: "CONNACK",
    PUBLISH: "PUBLISH",
    PUBACK: "PUBACK",
    PUBREC: "PUBREC",
    PUBREL: "PUBREL",
    PUBCOMP: "PUBCOMP",
    SUBSCRIBE: "SUBSCRIBE",
    SUBACK: "SUBACK",
    UNSUBSCRIBE: "UNSUBSCRIBE",
    UNSUBACK: "UNSUBACK",
    PINGREQ: "PINGREQ",
    PINGRESP: "PINGRESP",
    DISCONNECT: "DISCONNECT",
}

# ---- CONNACK return codes -------------------------------------------------
CONNACK_ACCEPTED = 0
CONNACK_BAD_PROTOCOL_VERSION = 1
CONNACK_IDENTIFIER_REJECTED = 2
CONNACK_SERVER_UNAVAILABLE = 3
CONNACK_BAD_CREDENTIALS = 4
CONNACK_NOT_AUTHORIZED = 5

#: Protocol level 4 is MQTT 3.1.1; 5 is MQTT 5.0. The device protocol accepts
#: either, but this harness speaks 3.1.1 on the wire.
PROTOCOL_LEVEL_311 = 4
PROTOCOL_LEVEL_50 = 5


class MalformedPacket(ValueError):
    """The bytes on the wire are not a packet this parser can make sense of."""


@dataclass(slots=True)
class RawPacket:
    packet_type: int
    flags: int
    body: bytes

    @property
    def name(self) -> str:
        return PACKET_NAMES.get(self.packet_type, f"UNKNOWN({self.packet_type})")


@dataclass(slots=True)
class ConnectPacket:
    """Everything the harness needs to judge a device's CONNECT.

    The will fields matter as much as the credentials: a device that connects
    perfectly but never declared a last will looks healthy right up until it
    loses power, at which point the platform has no way to notice.
    """

    protocol_name: str
    protocol_level: int
    client_id: str
    clean_session: bool
    keepalive: int
    username: str | None = None
    password: str | None = None
    will_flag: bool = False
    will_topic: str = ""
    will_payload: bytes = b""
    will_qos: int = 0
    will_retain: bool = False


@dataclass(slots=True)
class PublishPacket:
    topic: str
    payload: bytes
    qos: int = 0
    retain: bool = False
    dup: bool = False
    packet_id: int | None = None


@dataclass(slots=True)
class SubscribePacket:
    packet_id: int
    #: ``[(topic filter, requested qos), ...]``
    filters: list[tuple[str, int]] = field(default_factory=list)


@dataclass(slots=True)
class UnsubscribePacket:
    packet_id: int
    filters: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------
def encode_remaining_length(length: int) -> bytes:
    """Variable-length integer, 1-4 bytes, 7 bits each."""
    if length < 0 or length > 268_435_455:
        raise MalformedPacket(f"remaining length {length} out of range")
    out = bytearray()
    while True:
        byte = length % 128
        length //= 128
        if length > 0:
            byte |= 0x80
        out.append(byte)
        if length == 0:
            return bytes(out)


def decode_remaining_length(read_byte) -> int:
    """Decode a variable-length integer using a callable returning one byte."""
    multiplier = 1
    value = 0
    for _ in range(4):
        raw = read_byte()
        if not raw:
            raise MalformedPacket("connection closed while reading remaining length")
        byte = raw[0]
        value += (byte & 0x7F) * multiplier
        if not byte & 0x80:
            return value
        multiplier *= 128
    raise MalformedPacket("remaining length is longer than 4 bytes")


def encode_string(value: str) -> bytes:
    data = value.encode("utf-8")
    if len(data) > 0xFFFF:
        raise MalformedPacket("string longer than 65535 bytes")
    return struct.pack(">H", len(data)) + data


def read_string(body: bytes, offset: int) -> tuple[str, int]:
    if offset + 2 > len(body):
        raise MalformedPacket("truncated string length")
    (length,) = struct.unpack_from(">H", body, offset)
    offset += 2
    if offset + length > len(body):
        raise MalformedPacket("truncated string body")
    raw = body[offset : offset + length]
    try:
        return raw.decode("utf-8"), offset + length
    except UnicodeDecodeError as exc:
        raise MalformedPacket(f"string is not valid UTF-8: {exc}") from exc


def read_bytes(body: bytes, offset: int) -> tuple[bytes, int]:
    if offset + 2 > len(body):
        raise MalformedPacket("truncated binary length")
    (length,) = struct.unpack_from(">H", body, offset)
    offset += 2
    if offset + length > len(body):
        raise MalformedPacket("truncated binary body")
    return body[offset : offset + length], offset + length


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------
def decode_connect(body: bytes) -> ConnectPacket:
    protocol_name, offset = read_string(body, 0)
    if offset + 4 > len(body):
        raise MalformedPacket("CONNECT variable header is truncated")
    level = body[offset]
    flags = body[offset + 1]
    (keepalive,) = struct.unpack_from(">H", body, offset + 2)
    offset += 4

    if flags & 0x01:
        raise MalformedPacket("CONNECT reserved flag bit 0 must be zero")

    clean_session = bool(flags & 0x02)
    will_flag = bool(flags & 0x04)
    will_qos = (flags & 0x18) >> 3
    will_retain = bool(flags & 0x20)
    has_password = bool(flags & 0x40)
    has_username = bool(flags & 0x80)

    client_id, offset = read_string(body, offset)

    will_topic = ""
    will_payload = b""
    if will_flag:
        will_topic, offset = read_string(body, offset)
        will_payload, offset = read_bytes(body, offset)

    username = None
    password = None
    if has_username:
        username, offset = read_string(body, offset)
    if has_password:
        raw_password, offset = read_bytes(body, offset)
        password = raw_password.decode("utf-8", errors="replace")

    return ConnectPacket(
        protocol_name=protocol_name,
        protocol_level=level,
        client_id=client_id,
        clean_session=clean_session,
        keepalive=keepalive,
        username=username,
        password=password,
        will_flag=will_flag,
        will_topic=will_topic,
        will_payload=will_payload,
        will_qos=will_qos,
        will_retain=will_retain,
    )


def decode_publish(flags: int, body: bytes) -> PublishPacket:
    dup = bool(flags & 0x08)
    qos = (flags & 0x06) >> 1
    retain = bool(flags & 0x01)
    if qos > 2:
        raise MalformedPacket("PUBLISH QoS 3 is invalid")

    topic, offset = read_string(body, 0)
    packet_id = None
    if qos > 0:
        if offset + 2 > len(body):
            raise MalformedPacket("PUBLISH with QoS > 0 has no packet id")
        (packet_id,) = struct.unpack_from(">H", body, offset)
        offset += 2

    return PublishPacket(
        topic=topic,
        payload=body[offset:],
        qos=qos,
        retain=retain,
        dup=dup,
        packet_id=packet_id,
    )


def decode_subscribe(body: bytes) -> SubscribePacket:
    if len(body) < 2:
        raise MalformedPacket("SUBSCRIBE is truncated")
    (packet_id,) = struct.unpack_from(">H", body, 0)
    offset = 2
    filters: list[tuple[str, int]] = []
    while offset < len(body):
        topic, offset = read_string(body, offset)
        if offset >= len(body):
            raise MalformedPacket("SUBSCRIBE filter has no QoS byte")
        filters.append((topic, body[offset] & 0x03))
        offset += 1
    if not filters:
        raise MalformedPacket("SUBSCRIBE must carry at least one filter")
    return SubscribePacket(packet_id=packet_id, filters=filters)


def decode_unsubscribe(body: bytes) -> UnsubscribePacket:
    if len(body) < 2:
        raise MalformedPacket("UNSUBSCRIBE is truncated")
    (packet_id,) = struct.unpack_from(">H", body, 0)
    offset = 2
    filters: list[str] = []
    while offset < len(body):
        topic, offset = read_string(body, offset)
        filters.append(topic)
    return UnsubscribePacket(packet_id=packet_id, filters=filters)


def decode_packet_id(body: bytes) -> int:
    if len(body) < 2:
        raise MalformedPacket("packet is too short to carry a packet id")
    return struct.unpack_from(">H", body, 0)[0]


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------
def _frame(packet_type: int, flags: int, body: bytes) -> bytes:
    header = bytes([(packet_type << 4) | (flags & 0x0F)])
    return header + encode_remaining_length(len(body)) + body


def encode_connack(return_code: int, *, session_present: bool = False) -> bytes:
    return _frame(CONNACK, 0, bytes([1 if session_present else 0, return_code]))


def encode_publish(
    topic: str,
    payload: bytes,
    *,
    qos: int = 0,
    retain: bool = False,
    dup: bool = False,
    packet_id: int | None = None,
) -> bytes:
    if qos > 0 and packet_id is None:
        raise MalformedPacket("QoS > 0 requires a packet id")
    flags = (0x08 if dup else 0) | ((qos & 0x03) << 1) | (0x01 if retain else 0)
    body = encode_string(topic)
    if qos > 0:
        body += struct.pack(">H", packet_id)
    return _frame(PUBLISH, flags, body + payload)


def encode_puback(packet_id: int) -> bytes:
    return _frame(PUBACK, 0, struct.pack(">H", packet_id))


def encode_suback(packet_id: int, granted: list[int]) -> bytes:
    return _frame(SUBACK, 0, struct.pack(">H", packet_id) + bytes(granted))


def encode_unsuback(packet_id: int) -> bytes:
    return _frame(UNSUBACK, 0, struct.pack(">H", packet_id))


def encode_pingresp() -> bytes:
    return _frame(PINGRESP, 0, b"")


def encode_connect(packet: ConnectPacket) -> bytes:
    """Only used by the tests, to feed the decoder a known-good CONNECT."""
    flags = 0
    if packet.clean_session:
        flags |= 0x02
    if packet.will_flag:
        flags |= 0x04 | ((packet.will_qos & 0x03) << 3)
        if packet.will_retain:
            flags |= 0x20
    if packet.password is not None:
        flags |= 0x40
    if packet.username is not None:
        flags |= 0x80

    body = encode_string(packet.protocol_name)
    body += bytes([packet.protocol_level, flags])
    body += struct.pack(">H", packet.keepalive)
    body += encode_string(packet.client_id)
    if packet.will_flag:
        body += encode_string(packet.will_topic)
        body += struct.pack(">H", len(packet.will_payload)) + packet.will_payload
    if packet.username is not None:
        body += encode_string(packet.username)
    if packet.password is not None:
        data = packet.password.encode("utf-8")
        body += struct.pack(">H", len(data)) + data
    return _frame(CONNECT, 0, body)


def read_packet(stream) -> RawPacket | None:
    """Read one packet from a binary stream. ``None`` means the peer hung up."""
    header = stream.read(1)
    if not header:
        return None
    packet_type = header[0] >> 4
    flags = header[0] & 0x0F
    length = decode_remaining_length(lambda: stream.read(1))
    body = b""
    while len(body) < length:
        chunk = stream.read(length - len(body))
        if not chunk:
            raise MalformedPacket("connection closed mid-packet")
        body += chunk
    return RawPacket(packet_type=packet_type, flags=flags, body=body)
