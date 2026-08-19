# EMQX configuration

Two things have to be configured on the broker for the platform to enforce its
own device identity model:

1. **Authentication** — device credentials live in the ZQS database, not in the
   broker, so a device disabled in the console immediately loses access.
2. **Authorization (ACL)** — a device may only publish to its own topic subtree
   and subscribe to its own `control` topic.

Both are HTTP webhooks pointing back at the API. Set `EMQX_WEBHOOK_TOKEN` in
`.env` first — the endpoints stay disabled while it is empty, and reject any
call whose `X-EMQX-Token` header does not match.

## Option A — dashboard

**Access Control → Authentication → Create → Password-Based → HTTP Server**

| Field | Value |
| --- | --- |
| Method | `POST` |
| URL | `http://api:8000/api/emqx/auth` |
| Headers | `content-type: application/json`, `X-EMQX-Token: <token>` |
| Body | `{"username":"${username}","password":"${password}","clientid":"${clientid}","peerhost":"${peerhost}"}` |

**Access Control → Authorization → Create → HTTP Server**

| Field | Value |
| --- | --- |
| Method | `POST` |
| URL | `http://api:8000/api/emqx/acl` |
| Headers | `content-type: application/json`, `X-EMQX-Token: <token>` |
| Body | `{"username":"${username}","clientid":"${clientid}","topic":"${topic}","action":"${action}"}` |

## Option B — emqx.conf

```hocon
authentication = [
  {
    mechanism = password_based
    backend = http
    enable = true
    method = post
    url = "http://api:8000/api/emqx/auth"
    headers {
      "content-type" = "application/json"
      "X-EMQX-Token" = "${EMQX_WEBHOOK_TOKEN}"
    }
    body {
      username = "${username}"
      password = "${password}"
      clientid = "${clientid}"
      peerhost = "${peerhost}"
    }
    pool_size = 8
    request_timeout = "5s"
  }
]

authorization {
  no_match = deny
  deny_action = disconnect
  sources = [
    {
      type = http
      enable = true
      method = post
      url = "http://api:8000/api/emqx/acl"
      headers {
        "content-type" = "application/json"
        "X-EMQX-Token" = "${EMQX_WEBHOOK_TOKEN}"
      }
      body {
        username = "${username}"
        clientid = "${clientid}"
        topic = "${topic}"
        action = "${action}"
      }
      request_timeout = "5s"
    }
  ]
}
```

`no_match = deny` is the important line: without it, any topic the ACL source
does not explicitly rule on would be allowed.

## Server-side accounts

The ingestor and the API connect as ordinary clients and are *not* covered by
the device webhook (their usernames have no `DeviceCredential`). Create a
built-in account for them, or add a second authenticator ahead of the HTTP one:

```bash
emqx ctl authz cache-clean all
```

Then set `MQTT_USERNAME` / `MQTT_PASSWORD` in `.env` to that account.

## Shared subscriptions

The ingestor subscribes as `$share/zqs-ingestor/energy/devices/+/telemetry`,
so running several replicas splits the load rather than duplicating it. Set
`MQTT_USE_SHARED_SUBSCRIPTION=0` for a single-instance deployment that should
instead keep a persistent session and receive queued QoS 1 messages after a
restart.

## Verifying

```bash
# should succeed with real device credentials
mosquitto_pub -h localhost -p 1883 -u '<mqtt_username>' -P '<mqtt_password>' \
  -t 'energy/devices/ZQS-BESS-0001/telemetry' \
  -m '{"ts":1780000000000,"metrics":{"battery_soc":50}}'

# should be denied - wrong device subtree
mosquitto_pub -h localhost -p 1883 -u '<mqtt_username>' -P '<mqtt_password>' \
  -t 'energy/devices/SOMEONE-ELSE/telemetry' -m '{}'
```
