"""串流推送：每個開啟串流的通道一條執行緒，以 fps 上限把最新影格送出（共享記憶體優先，沒槽就丟幀）。"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

from vscapture import protocol as P
from vscapture.frames import frame_item, prepare
from vscapture.protocol import FrameHeader, MsgType

if TYPE_CHECKING:
    from vscapture.channel import Channel
    from vscapture.transport.client import TransportClient

log = logging.getLogger(__name__)


class StreamPusher(threading.Thread):
    def __init__(self, channel: Channel, client: TransportClient, chan_index: int, max_fps: float) -> None:
        super().__init__(name=f"vsc-stream-{channel.id}", daemon=True)
        self.channel = channel
        self.client = client
        self.chan_index = chan_index
        self.max_fps = float(max_fps or 0)
        self._halt = threading.Event()
        self.sent = 0
        self.dropped = 0

    def stop(self) -> None:
        self._halt.set()

    def run(self) -> None:
        ch = self.channel
        last_seq = ch.slot.seq
        last_sent = 0.0
        cap = self.max_fps if self.max_fps > 0 else ch.cfg.delivery.stream_fps
        if ch.cfg.delivery.stream_fps > 0:
            cap = min(cap, ch.cfg.delivery.stream_fps) if cap > 0 else ch.cfg.delivery.stream_fps
        period = 1.0 / cap if cap > 0 else 0.0
        while not self._halt.is_set():
            frame = ch.slot.wait_for(last_seq + 1, 0.5)
            if frame is None:
                continue
            last_seq = frame.seq
            now = time.perf_counter()
            if period and now - last_sent < period:
                continue
            try:
                ring = self.client.rings.get(ch.id)
                fields, arr = prepare(frame, ch.cfg.roi, ch.cfg.delivery, force_raw=ring is not None)
                if ring is not None:
                    slot = ring.try_write(frame.seq, arr)
                    if slot is None:
                        self.dropped += 1
                        continue
                    hdr = FrameHeader.for_image(self.chan_index, frame.seq, frame.ts_ns, fields["width"], fields["height"], fields["channels"], fields["dtype"],
                                                roi_x=fields["roi_x"], roi_y=fields["roi_y"], full_w=fields["full_w"], full_h=fields["full_h"], flags=fields["flags"], slot=slot)
                    self.client.queue.put_control(P.pack_message(MsgType.FRAME, 0, hdr.pack()))
                else:
                    hdr = FrameHeader.for_image(self.chan_index, frame.seq, frame.ts_ns, fields["width"], fields["height"], fields["channels"], fields["dtype"],
                                                roi_x=fields["roi_x"], roi_y=fields["roi_y"], full_w=fields["full_w"], full_h=fields["full_h"], encoding=fields["encoding"], flags=fields["flags"])
                    item, _ = frame_item(MsgType.FRAME, 0, hdr, arr, fields["encoding"], ch.cfg.delivery.jpeg_quality)
                    if self.client.queue.put_stream(ch.id, item):
                        self.dropped += 1
                self.sent += 1
                last_sent = now
            except Exception:  # noqa: BLE001
                log.exception("通道 %s 串流推送失敗", ch.id)
                time.sleep(0.2)
