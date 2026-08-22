# EMQX 設定

broker 上有兩件事必須設定，平台才能真正執行自己的設備身分模型：

1. **認證（Authentication）**——設備憑證存在 ZQS 的資料庫裡，不在 broker 裡，
   所以在 console 停用一台設備時它會立刻失去連線權限。
2. **授權（Authorization / ACL）**——一台設備只能發布到自己的 topic 子樹，也只能
   訂閱自己的 `control` topic。

兩者都是指回 API 的 HTTP webhook。請先在 `.env` 設定 `EMQX_WEBHOOK_TOKEN`——留空
時這兩個端點是關閉的，而且任何 `X-EMQX-Token` 標頭不符的呼叫都會被拒絕。

## 方式 A —— 用 dashboard 設定

**Access Control → Authentication → Create → Password-Based → HTTP Server**

| 欄位 | 值 |
| --- | --- |
| Method | `POST` |
| URL | `http://api:8000/api/emqx/auth` |
| Headers | `content-type: application/json`, `X-EMQX-Token: <token>` |
| Body | `{"username":"${username}","password":"${password}","clientid":"${clientid}","peerhost":"${peerhost}"}` |

**Access Control → Authorization → Create → HTTP Server**

| 欄位 | 值 |
| --- | --- |
| Method | `POST` |
| URL | `http://api:8000/api/emqx/acl` |
| Headers | `content-type: application/json`, `X-EMQX-Token: <token>` |
| Body | `{"username":"${username}","clientid":"${clientid}","topic":"${topic}","action":"${action}"}` |

## 方式 B —— 用 emqx.conf 設定

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

`no_match = deny` 是關鍵的一行：少了它，ACL 來源沒有明確裁決的 topic 都會被放行。

## 伺服器端帳號

ingestor 與 API 是以一般客戶端的身分連線，**不**適用設備 webhook（它們的 username
沒有對應的 `DeviceCredential`）。請為它們建立一個 built-in 帳號，或在 HTTP
authenticator 前面再加一個 authenticator：

```bash
emqx ctl authz cache-clean all
```

然後在 `.env` 裡把 `MQTT_USERNAME` / `MQTT_PASSWORD` 設成那個帳號。

## Shared subscription

ingestor 對每一種上行訊息型別各訂閱一次，例如
`$share/zqs-ingestor/spBv1.0/+/DDATA/+/+`，因此跑多個副本是分攤流量而不是重複收。
單一實例的部署可以設定 `MQTT_USE_SHARED_SUBSCRIPTION=0` 改用一般訂閱。

刻意逐一列出訊息型別而不是用 `spBv1.0/#`：後者會讓主機收到自己發出去的 NCMD 與
DCMD。

**Sparkplug 下 shared subscription 有一個代價要知道。** 同一個節點的訊息會被分到
不同的副本，所以 `seq` 在任何單一副本眼中都可能是不連續的，偶爾會觸發一次不必要
的重生要求。這是安全的（節點只是重發一次 BIRTH，而且有 30 秒冷卻），但如果現場
看到重生要求頻繁到礙眼，先把副本數降到 1 再判斷是不是設備的問題。

## 驗證

Sparkplug payload 是 protobuf，用 `mosquitto_pub` 手打不切實際。要驗 ACL，重點是
**topic 有沒有被接受**，內容可以是空的：

```bash
# 自己的位址，應該要成功（payload 空的沒關係，ACL 在解碼之前就判完了）
mosquitto_pub -h localhost -p 1883 -u '<mqtt_username>' -P '<mqtt_password>' \
  -t 'spBv1.0/demo/DDATA/ZQS-GW-0001/ZQS-BESS-0001' -n

# 應該要被拒絕——不是自己的節點
mosquitto_pub -h localhost -p 1883 -u '<mqtt_username>' -P '<mqtt_password>' \
  -t 'spBv1.0/demo/DDATA/SOMEONE-ELSE/X' -n

# 應該要被拒絕——命令是平台下行用的，節點不可以發
mosquitto_pub -h localhost -p 1883 -u '<mqtt_username>' -P '<mqtt_password>' \
  -t 'spBv1.0/demo/NCMD/ZQS-GW-0001' -n
```

要送一段真的 payload，用平台自己的模擬器：

```bash
.\scripts\sim-console.ps1    # 桌面主控台：登記的設備以 MQTT 客戶端上線
```
