# ProtocalBufferPayload — 設備／閘道器端的 payload 定義

這個資料夾是給**設備韌體、閘道器程式、LabVIEW／C#／Go 整合方**用的：不必翻 Python 原始碼，
拿這兩個 `.proto` 就能產生自己語言的資料結構並和 ZQS Cloud 對話。

| 檔案 | 是什麼 | 誰決定 |
|---|---|---|
| `sparkplug_b.proto` | **線上真正的位元組格式**。Eclipse Tahu 原版 Sparkplug B `Payload`，一字未改；與 `services/sparkplug/sparkplug_b.proto` 完全相同 | Sparkplug 規格，本專案不能改 |
| `zqs_profile.proto` | **應用層契約**：ZQS 在 Sparkplug metric 上約定的名稱、型別、命令與回覆對應（Properties/ Capabilities/ Ratings/ Alarm/ Event/ Command/），以及 W6 設定點有效期 | 本專案；版本見 `Properties/Schema Version` |

兩者的關係：`zqs_profile.proto` 的每個欄位註解都以 `→` 標出它落在 Sparkplug `Payload.Metric` 的哪個名稱與型別。
邊緣端用 profile 的型別化 struct 組資料，再依對照填成 `Payload` 送出；**不要**把 `zqs.profile.v1` 的訊息直接序列化上 MQTT，
broker 上的其他 Sparkplug 實作看不懂。

## Topic 與訊息型別

```
spBv1.0/{group_id}/NBIRTH/{edge_node_id}               閘道器出生（bdSeq、Node Control/Rebirth）
spBv1.0/{group_id}/NDEATH/{edge_node_id}               閘道器遺囑（同一個 bdSeq；MQTT will） → NodeDeath
spBv1.0/{group_id}/DBIRTH/{edge_node_id}/{device_id}   設備宣告 + 全部 metric 目前值   → DeviceBirth
spBv1.0/{group_id}/DDATA/{edge_node_id}/{device_id}    週期回報 / 告警 / 事件 / 命令回覆 → DeviceData
spBv1.0/{group_id}/DDEATH/{edge_node_id}/{device_id}   設備離線（不帶 metric）            → DeviceDeath
spBv1.0/{group_id}/DCMD/{edge_node_id}/{device_id}     平台 → 設備 命令                    → Command
spBv1.0/{group_id}/NCMD/{edge_node_id}                 平台 → 閘道器（Node Control/Rebirth）
```

`group_id` 是租戶代碼（示範租戶 `zqs-demo`）。序號規則：`bdSeq` 每次連線 +1 且 NBIRTH／NDEATH 一致；`seq` 每則訊息 +1（0–255 循環），跳號會被要求重生。

## 產生程式碼

```bash
# Python（本專案：產物已提交在 services/sparkplug/sparkplug_b_pb2.py，只在改 .proto 時重生）
python -m grpc_tools.protoc -I ProtocalBufferPayload --python_out=out ProtocalBufferPayload/sparkplug_b.proto ProtocalBufferPayload/zqs_profile.proto

# C#（設備端 / LabVIEW .NET 呼叫）
protoc -I ProtocalBufferPayload --csharp_out=out ProtocalBufferPayload/*.proto

# C（嵌入式，nanopb）
python nanopb/generator/nanopb_generator.py -I ProtocalBufferPayload ProtocalBufferPayload/sparkplug_b.proto

# Go
protoc -I ProtocalBufferPayload --go_out=out ProtocalBufferPayload/*.proto
```

`sparkplug_b.proto` 是 **proto2**（規格如此，含 `extensions`），`zqs_profile.proto` 是 proto3；兩者可同時編譯。
嵌入式端只需要 `sparkplug_b.proto`；profile 可只當文件讀。

## 最小握手（設備端要做的事）

1. 連線：MQTT 3.1.1，will = `NDEATH`（帶本次 `bdSeq`）。
2. 送 `NBIRTH`（`bdSeq`、`Node Control/Rebirth=false`）。
3. 每台設備送 `DBIRTH`：`Properties/Category`（必填，驗收後不可變）、`Properties/Schema Version=1`、能力與額定、**全部** metric 及其目前值。
4. 週期 `DDATA`：只送有變化或到時間的 metric；可用 alias。
5. 收到 `DCMD`：讀 `Command/ID`、`Command/Name`、`Command/Expires` 與 `Command/<param>`；執行後在 `DDATA` 回 `Command/ID` + `Command/Status`（`succeeded|rejected|failed|expired`），建議同一則一併帶新的量測值。
6. `set_power_setpoint` 若帶 `valid_until`／`on_expiry`：到期或失去雲端後**自行**降級（idle／hold／reserve），不等平台。
7. 收到 `NCMD Node Control/Rebirth=true`：重送 NBIRTH 與所有 DBIRTH（`bdSeq` 不變、`seq` 歸零）。

完整規格、逐條驗收清單與自我驗證工具見 `docs/device-protocol.html` 與 `docs/device-test-harness.html`
（`scripts/test-device.ps1` 會把一台真實設備按上述步驟逐項打分）。
