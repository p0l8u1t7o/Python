# ZQS Cloud device protocol (v1)

Everything a device implementation - LabVIEW or otherwise - needs in order to
talk to the platform. The server validates every field described here and
rejects anything that does not match, so treat this document as the contract.

---

## 1. Connection

| Item | Value |
| --- | --- |
| Protocol | MQTT 3.1.1 or 5.0 |
| Broker | EMQX |
| Port | `1883` plain, `8883` TLS (use TLS in production) |
| Client ID | `zqs:<device_id>` — the ACL webhook can pin this |
| Username | issued at registration, e.g. `dev-demo-ZQS-BESS-0001` |
| Password | issued at registration, **shown once** |
| Keepalive | 45 s recommended |
| Clean session | `false`, so QoS 1 downlink survives a short outage |
| QoS | 1 for telemetry, status, events, alarms and commands |

`device_id` is **globally unique** across the platform, because the topic
carries no tenant segment. Use the serial number or MAC address. Allowed
characters: `A-Z a-z 0-9 . _ -`, 3–64 characters, no MQTT wildcards.

### Last will and testament (required)

Register the LWT **at connect time** so an abrupt power loss is visible:

- Topic: `energy/devices/{device_id}/status`
- Retain: `true`
- QoS: `1`
- Payload: `{"status":"offline","reason":"lwt"}`

Publish the matching `{"status":"online", ...}` immediately after connecting.

---

## 2. Topics

Root is configurable (`MQTT_TOPIC_ROOT`) and defaults to `energy/devices`.

| Direction | Topic | Purpose |
| --- | --- | --- |
| uplink | `energy/devices/{device_id}/telemetry` | measurements |
| uplink | `energy/devices/{device_id}/status` | online/offline, firmware, location |
| uplink | `energy/devices/{device_id}/event` | operation log entries |
| uplink | `energy/devices/{device_id}/alarm` | faults the device detected |
| uplink | `energy/devices/{device_id}/control/ack` | command acknowledgement |
| downlink | `energy/devices/{device_id}/control` | commands from the server |

A device may only publish to its own subtree and subscribe to its own
`control` topic; the broker enforces this through the ACL webhook.

---

## 3. Payloads

All payloads are UTF-8 JSON objects, at most 256 KB. Unknown extra fields are
accepted and ignored, so adding fields later will not break an older server.

### 3.1 Timestamps

`ts` accepts any of:

- epoch **seconds**, **milliseconds**, **microseconds** or **nanoseconds**
  (the magnitude is used to tell them apart — milliseconds is recommended);
- ISO-8601 text, e.g. `2026-06-01T09:15:00Z`; a string with no offset is read
  as UTC.

Guard rails: a timestamp more than **5 minutes in the future** or more than
**7 days in the past** is rejected. Omitting `ts` is allowed on `status`,
`event`, `alarm` and `control/ack` — the server then uses its receive time.
`telemetry` **must** carry `ts`.

If the device has no reliable clock, use the `sync_time` command or omit `ts`
on non-telemetry messages rather than sending a wrong one.

### 3.2 Telemetry

Two interchangeable shapes. Use whichever is easier to build in LabVIEW.

**Dictionary form** — one timestamp for all metrics:

```json
{
  "ts": 1780000000000,
  "seq": 12345,
  "metrics": {
    "battery_soc": 78.2,
    "battery_power_w": -125000,
    "battery_temperature_c": 31.4,
    "pcs_state": "charge"
  }
}
```

**List form** — per-reading timestamps, useful for replaying a buffer after a
network outage:

```json
{
  "ts": 1780000000000,
  "readings": [
    {"metric": "grid_power_w", "value": 214500, "ts": 1780000000000},
    {"metric": "grid_power_w", "value": 218900, "ts": 1780000005000}
  ]
}
```

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `ts` | number/string | yes | see 3.1 |
| `seq` | integer | no | monotonic counter; helps diagnose gaps |
| `metrics` | object | one of | `{metric_key: value}` |
| `readings` | array | one of | `[{metric, value, ts?, quality?}]` |
| `meta` | object | no | free-form context |

Rules:

- metric keys are lowercase `snake_case`, ≤ 64 characters;
- values may be number, boolean (stored as 1/0), string or `null`;
- `NaN` and `Infinity` are rejected — send `null` for "no reading";
- at most 512 readings per message;
- re-sending an identical `(device, metric, ts)` is safe: the server keeps one
  row, so retrying after an uncertain publish cannot double-count.

The metric catalogue (`GET /api/metrics`) lists the built-in keys — see
§7 for the ones that matter for behind-the-meter storage.

### 3.3 Status

```json
{
  "status": "online",
  "ts": 1780000000000,
  "reason": "boot",
  "firmware": "2.1.4",
  "hardware": "PCS-500K rev C",
  "ip": "10.20.30.40",
  "rssi": -63,
  "location": {
    "latitude": 25.0339,
    "longitude": 121.5645,
    "address": "No. 7, Sec. 5, Xinyi Rd, Taipei"
  }
}
```

`status` is `online` or `offline` and is the only required field. When
`location` is supplied it overrides the site's coordinates on the map, and the
server records where the position came from.

Publish `status` **retained** so a reconnecting console sees the current state.
The server ignores a retained status message older than the last transition it
already recorded, so a replayed LWT cannot knock a live device offline.

### 3.4 Event (operation log)

```json
{
  "ts": 1780000000000,
  "level": "warning",
  "code": "E0231",
  "message": "Cooling fan speed below threshold",
  "data": {"fan_rpm": 820, "expected_rpm": 1200}
}
```

`level` ∈ `debug | info | notice | warning | error | critical` (default `info`).

### 3.5 Alarm

```json
{
  "ts": 1780000000000,
  "code": "E0500",
  "severity": "major",
  "message": "Insulation resistance low",
  "active": true,
  "details": {"resistance_kohm": 41}
}
```

`severity` ∈ `info | warning | major | critical`. Send the same `code` with
`"active": false` to clear it — the server then resolves the open alert. While
an alarm stays active, repeats only bump its occurrence counter.

### 3.6 Command acknowledgement

```json
{
  "command_id": "0f9d7a1c-4c1a-4e0e-9a7d-8f2b1c3d4e5f",
  "status": "succeeded",
  "ts": 1780000000000,
  "message": "",
  "result": {"applied_limit_w": 400000}
}
```

`status` ∈ `accepted | rejected | succeeded | failed`. Send `accepted` on
receipt if execution takes a while, then `succeeded` or `failed` when done. A
late `accepted` after a terminal status is ignored, so ordering glitches are
harmless.

---

## 4. Commands (downlink)

The device subscribes to `energy/devices/{device_id}/control` and receives:

```json
{
  "command_id": "0f9d7a1c-4c1a-4e0e-9a7d-8f2b1c3d4e5f",
  "name": "set_power_limit",
  "params": {"limit_w": 400000},
  "issued_at": 1780000000000,
  "expires_at": 1780000060000,
  "reply_to": "energy/devices/ZQS-BESS-0001/control/ack"
}
```

Expected behaviour:

1. Ignore a command whose `expires_at` has already passed — the server has
   marked it expired and no longer expects a reply.
2. Validate `params` locally as well; the server checked them against the
   blueprint, but the device is the last line of defence.
3. Publish an acknowledgement to `reply_to`, echoing `command_id` verbatim.
4. Treat a repeated `command_id` as a duplicate and re-send the previous
   acknowledgement rather than executing twice.

The available commands come from the device's blueprint; the defaults shipped
by `manage.py bootstrap` are:

| Blueprint | Command | Parameters |
| --- | --- | --- |
| `bess-pcs` | `set_power_limit` | `limit_w` 0…5 000 000 |
| | `set_power_setpoint` | `power_w` ±5 000 000, `ramp_s` 0…3600 |
| | `set_mode` | `mode` ∈ idle/charge/discharge/auto/standby |
| | `set_soc_limits` | `min_soc`, `max_soc` 0…100 |
| | `emergency_stop` | — |
| | `reboot` | — |
| `smart-meter` | `set_report_interval` | `interval_s` 1…3600 |
| `pv-inverter` | `set_export_limit` | `limit_w` 0…5 000 000 |
| | `set_output_enabled` | `enabled` boolean |
| `ems-controller` | `set_strategy` | `strategy`, `target_kw` |
| | `sync_time` | `epoch_ms` |
| `ev-charger` | `set_current_limit` | `limit_a` 0…500 |
| | `stop_session` | — |

---

## 5. Recommended device behaviour

**Publish cadence.** 1–10 s for power signals, 30–60 s for SOC and
temperature, on-change for state strings. Do not throttle on the device to
save bandwidth: the server's recording policy already decides what to store,
and it needs the full stream to evaluate alerts correctly.

**Buffering.** Keep at least an hour of samples in local storage. On
reconnect, replay them with the list form and their original timestamps; the
uniqueness rule makes replay idempotent, so overlap is safe.

**Backoff.** Reconnect with exponential backoff between 1 s and 60 s plus
jitter. Do not reconnect in a tight loop after an authentication failure —
credentials do not fix themselves, and the broker will rate-limit you.

**Clock.** Sync via NTP where possible. Timestamps outside the skew window are
dropped, and the loss is silent from the device's point of view.

---

## 6. LabVIEW implementation notes

- Any MQTT toolkit works. Publishing requires only: connect with LWT,
  publish string payloads at QoS 1, subscribe to one topic.
- Build JSON with the built-in **Flatten To JSON**, or by string concatenation
  for the fixed telemetry shape — the payload is small and regular.
- Keep one persistent connection for the lifetime of the application; do not
  connect and disconnect per publish.
- Use a producer/consumer queue: acquisition loop → queue → publish loop. If
  the publish loop is disconnected, spill the queue to disk and replay later.
- Handle the control topic in its own event loop so a long-running command
  never blocks telemetry publishing.

Minimal telemetry payload as a format string:

```
{"ts":%d,"metrics":{"battery_soc":%.2f,"battery_power_w":%.1f}}
```

---

## 7. Built-in metric keys for behind-the-meter storage

| Key | Unit | Meaning |
| --- | --- | --- |
| `grid_power_w` | W | at the point of common coupling; **+ import, − export** |
| `grid_voltage_v` | V | |
| `grid_current_a` | A | |
| `grid_frequency_hz` | Hz | |
| `grid_import_energy_kwh` | kWh | cumulative counter |
| `grid_export_energy_kwh` | kWh | cumulative counter |
| `load_power_w` | W | site load, always ≥ 0 |
| `pv_power_w` | W | generation, always ≥ 0 |
| `pv_energy_kwh` | kWh | cumulative counter |
| `battery_power_w` | W | **+ discharging, − charging** |
| `battery_soc` | % | 0–100 |
| `battery_soh` | % | 0–100 |
| `battery_voltage_v` | V | |
| `battery_current_a` | A | |
| `battery_temperature_c` | °C | |
| `battery_charge_energy_kwh` | kWh | cumulative counter |
| `battery_discharge_energy_kwh` | kWh | cumulative counter |
| `pcs_state` | — | string state, e.g. `idle`/`charge`/`discharge` |
| `pcs_fault_code` | — | vendor code |

Sign conventions matter: the energy aggregator splits import from export and
charge from discharge by sign. If your hardware uses the opposite convention,
set **Invert sign** on the energy asset instead of changing device firmware.

Any other key is accepted too — define it under `POST /api/metrics` so the
console knows its unit and label, or let it flow through unlabelled.

---

## 8. Quick check without hardware

```bash
python manage.py simulate_device --device ZQS-BESS-0001 --profile battery --interval 5
```

This publishes exactly the payloads described above, so it doubles as a
reference implementation of the wire format.
