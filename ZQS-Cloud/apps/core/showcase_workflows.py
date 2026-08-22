"""The showcase's drawn control flows.

Six workflows, each a complete and runnable example of one pattern the
editor supports, each annotated on the canvas with notes so a customer can
read what the graph does without a guide standing next to it. They run
against the showcase fleet (``seed_showcase``), which answers every command
they send.

Device placeholders are ``{KEY}`` where KEY is one of BESS, METER, PV, LOAD,
EMS; ``seed_showcase`` resolves them against one site's devices.

Positions follow a 280 x 200 grid so the canvas reads top-down: flow on the
left, notes on the right.
"""

from __future__ import annotations

import json


def _node(id_, type_, label, x, y, *, params=None, description="", enabled=True):
    return {
        "id": id_, "type": type_, "label": label, "description": description,
        "enabled": enabled, "params": params or {}, "position": {"x": x, "y": y},
    }


def _note(id_, title, body, x, y):
    return _node(id_, "note", title, x, y, description=body)


def _edge(source, handle, target):
    return {
        "id": f"e-{source}-{handle}-{target}", "source": source, "target": target,
        "source_handle": handle,
    }


def _cond(device, metric, op, threshold):
    return {"device_id": device, "metric_key": metric, "operator": op, "threshold": threshold}


def _setpoint(device, watts):
    return {
        "device_id": device, "command": "set_power_setpoint",
        "param_name": "power_w", "value": watts,
    }


# --------------------------------------------------------------------------
# 1. Peak shaving with a low-SOC interlock (two parallel branches)
# --------------------------------------------------------------------------
def peak_shaving(contract_kw: float, shave_kw: float) -> dict:
    ceiling_w = int(contract_kw * 1000)
    nodes = [
        _note("n-1", "這個流程在做什麼",
              "兩條分支同時跑。\n左：關口電表連續 30 秒超過契約容量就放電削峰；"
              "回落後歸零。\n右：電池電量低於 15% 時強制停止放電，保護電池。\n"
              "每條分支結尾用「跳至」回到自己的判斷節點，形成持續監看的迴圈。",
              640, 40),
        _node("start-1", "start", "需量監看", 40, 40),
        _node("if_end_timer-1", "if_end_timer", "需量持續超過契約", 40, 220,
              params={**_cond("{METER}", "grid_power_w", "gt", ceiling_w), "hold_seconds": 30},
              description="超過契約容量並持續 30 秒才動作，避免瞬間尖峰誤觸發。"),
        _node("set_data-1", "set_data", f"放電 {shave_kw:.0f} kW 削峰", -160, 420,
              params=_setpoint("{BESS}", int(shave_kw * 1000)),
              description="正值 = 放電。PCS 收到設定點後下一筆讀值即反映。"),
        _node("set_data-2", "set_data", "需量正常：電池待命", 240, 420,
              params=_setpoint("{BESS}", 0),
              description="回落到契約以下就把設定點歸零，留電量給下一次尖峰。"),
        _node("node-1", "node", "匯流", 40, 620),
        _node("wait-1", "wait", "每 30 秒檢查一次", 40, 800, params={"seconds": 30},
              description="迴圈節奏：需量以 15 分鐘平均計費，30 秒一輪已足夠，也避免指令洗版。"),
        _node("jump-1", "jump", "重新檢查", 40, 980, params={"target": "if_end_timer-1"},
              description="跳回判斷節點；跳躍本身也會等一個掃描週期，不會空轉。"),
        _node("start-2", "start", "電量保護", 400, 40),
        _node("if_end-1", "if_end", "電量低於 15%", 400, 220,
              params=_cond("{BESS}", "battery_soc", "lt", 15)),
        _node("send_action-1", "send_action", "緊急停止放電", 400, 420,
              params={"device_id": "{BESS}", "command": "emergency_stop", "params": "{}"},
              description="emergency_stop 會覆寫任何設定點，電池立即歸零。"),
        _node("wait-2", "wait", "每 30 秒檢查一次", 400, 620, params={"seconds": 30}),
        _node("jump-2", "jump", "重新檢查", 400, 800, params={"target": "if_end-1"}),
        _note("n-2", "為什麼用「條件計時」",
              "需量是 15 分鐘平均值計費，一兩秒的尖峰不值得動作。\n"
              "條件計時節點要求條件連續成立 30 秒，才走「True」分支。",
              640, 220),
    ]
    edges = [
        _edge("start-1", "out", "if_end_timer-1"),
        _edge("if_end_timer-1", "true", "set_data-1"),
        _edge("if_end_timer-1", "false", "set_data-2"),
        _edge("if_end_timer-1", "unknown", "node-1"),
        _edge("set_data-1", "sent", "node-1"),
        _edge("set_data-1", "failed", "node-1"),
        _edge("set_data-2", "sent", "node-1"),
        _edge("set_data-2", "failed", "node-1"),
        _edge("node-1", "out", "wait-1"),
        _edge("wait-1", "out", "jump-1"),
        _edge("start-2", "out", "if_end-1"),
        _edge("if_end-1", "true", "send_action-1"),
        _edge("if_end-1", "false", "wait-2"),
        _edge("if_end-1", "unknown", "wait-2"),
        _edge("send_action-1", "sent", "wait-2"),
        _edge("send_action-1", "failed", "wait-2"),
        _edge("wait-2", "out", "jump-2"),
    ]
    return {"nodes": nodes, "edges": edges}


# --------------------------------------------------------------------------
# 2. Off-peak charging window (time window + cross-midnight)
# --------------------------------------------------------------------------
def offpeak_charging(charge_kw: float) -> dict:
    nodes = [
        _note("n-1", "離峰充電排程",
              "每天 22:30–06:30（跨午夜）在離峰電價把電池充飽，白天尖峰再放。\n"
              "「時間窗」節點以場域時區判斷；這裡關閉「等待開窗」，窗外直接走 False 把設定點歸零。"
              "（開啟時分支會停在該節點等到下一次開窗，不佔用步數。）", 400, 40),
        _node("start-1", "start", "開始", 40, 40),
        _node("if_end_time-1", "if_end_time", "離峰時段 22:30–06:30", 40, 220,
              params={"days": "everyday", "start_time": "22:30", "end_time": "06:30",
                      "wait_for_window": False},
              description="跨午夜的時間窗：晚間段屬於當天，清晨段屬於隔天。"),
        _node("if_end-1", "if_end", "電量未滿（< 90%）", -160, 420,
              params=_cond("{BESS}", "battery_soc", "lt", 90)),
        _node("set_data-1", "set_data", f"充電 {charge_kw:.0f} kW", -160, 620,
              params=_setpoint("{BESS}", -int(charge_kw * 1000)),
              description="負值 = 充電。"),
        _node("set_data-2", "set_data", "停止充電", 240, 620, params=_setpoint("{BESS}", 0),
              description="窗外或已充飽：設定點歸零。"),
        _node("wait-1", "wait", "等待 60 秒", 40, 820, params={"seconds": 60},
              description="等待時分支被停放，不消耗資源。"),
        _node("jump-1", "jump", "回到時間判斷", 40, 1000, params={"target": "if_end_time-1"}),
        _note("n-2", "讀法",
              "時間窗 True → 電量判斷 → 充電；\n時間窗 False 或電量已滿 → 停止充電；\n"
              "兩邊都經過 60 秒等待後回到時間判斷。", 400, 420),
    ]
    edges = [
        _edge("start-1", "out", "if_end_time-1"),
        _edge("if_end_time-1", "true", "if_end-1"),
        _edge("if_end_time-1", "false", "set_data-2"),
        _edge("if_end-1", "true", "set_data-1"),
        _edge("if_end-1", "false", "set_data-2"),
        _edge("if_end-1", "unknown", "wait-1"),
        _edge("set_data-1", "sent", "wait-1"),
        _edge("set_data-1", "failed", "wait-1"),
        _edge("set_data-2", "sent", "wait-1"),
        _edge("set_data-2", "failed", "wait-1"),
        _edge("wait-1", "out", "jump-1"),
    ]
    return {"nodes": nodes, "edges": edges}


# --------------------------------------------------------------------------
# 3. PV surplus first (self-consumption)
# --------------------------------------------------------------------------
def pv_surplus(pv_threshold_kw: float, charge_kw: float) -> dict:
    threshold_w = int(pv_threshold_kw * 1000)
    nodes = [
        _note("n-1", "光電餘電優先充電",
              f"光電出力超過 {pv_threshold_kw:.0f} kW（通常代表中午有餘電）就把餘電充進電池，"
              "避免以躉售低價送回電網；出力回落就停止。\n"
              "這是「光儲自發自用」策略的手繪版本，適合拿來解釋內建策略在做什麼。",
              400, 40),
        _node("start-1", "start", "開始", 40, 40),
        _node("if_end-1", "if_end", f"光電出力 > {pv_threshold_kw:.0f} kW", 40, 220,
              params=_cond("{PV}", "pv_power_w", "gt", threshold_w)),
        _node("set_data-1", "set_data", f"餘電充電 {charge_kw:.0f} kW", -160, 420,
              params=_setpoint("{BESS}", -int(charge_kw * 1000))),
        _node("set_data-2", "set_data", "停止充電", 240, 420, params=_setpoint("{BESS}", 0)),
        _node("node-1", "node", "匯流", 40, 620),
        _node("wait-1", "wait", "每 30 秒檢查一次", 40, 800, params={"seconds": 30}),
        _node("jump-1", "jump", "重新檢查", 40, 980, params={"target": "if_end-1"}),
        _note("n-2", "「無讀值」分支",
              "光電逆變器離線或讀值過舊時，判斷節點走「無讀值」而不是猜一邊。\n"
              "這裡把它接到停止充電：不確定時就不動作。", 640, 420),
    ]
    edges = [
        _edge("start-1", "out", "if_end-1"),
        _edge("if_end-1", "true", "set_data-1"),
        _edge("if_end-1", "false", "set_data-2"),
        _edge("if_end-1", "unknown", "set_data-2"),
        _edge("set_data-1", "sent", "node-1"),
        _edge("set_data-1", "failed", "node-1"),
        _edge("set_data-2", "sent", "node-1"),
        _edge("set_data-2", "failed", "node-1"),
        _edge("node-1", "out", "wait-1"),
        _edge("wait-1", "out", "jump-1"),
    ]
    return {"nodes": nodes, "edges": edges}


# --------------------------------------------------------------------------
# 4. Safety interlock: over-temperature -> stop -> wait to cool -> resume
# --------------------------------------------------------------------------
def thermal_interlock() -> dict:
    nodes = [
        _note("n-1", "電池溫度連鎖",
              "電池溫度超過 45 °C：緊急停止 → 等待降到 40 °C 以下（最多 10 分鐘）→ "
              "恢復待命 → 回到監看。\n等待逾時走「逾時」分支，再發一次緊急停止並結束流程，"
              "留給人員處理。", 640, 40),
        _node("start-1", "start", "溫度監看", 40, 40),
        _node("if_end-1", "if_end", "電池溫度 > 45 °C", 40, 220,
              params=_cond("{BESS}", "battery_temperature_c", "gt", 45)),
        _node("send_action-1", "send_action", "緊急停止", 40, 420,
              params={"device_id": "{BESS}", "command": "emergency_stop", "params": "{}"}),
        _node("condition_wait-1", "condition_wait", "等待降溫至 40 °C 以下", 40, 620,
              params={**_cond("{BESS}", "battery_temperature_c", "lt", 40),
                      "timeout_seconds": 600},
              description="條件等待：每個掃描週期重讀一次，條件成立才繼續。"),
        _node("set_data-1", "set_data", "恢復待命（設定點 0）", -160, 820,
              params=_setpoint("{BESS}", 0)),
        _node("send_action-2", "send_action", "逾時：再次緊急停止", 240, 820,
              params={"device_id": "{BESS}", "command": "emergency_stop", "params": "{}"}),
        _node("end-1", "end", "結束，交由人員處理", 240, 1020),
        _node("jump-1", "jump", "回到監看", 40, 1020, params={"target": "if_end-1"}),
        _node("wait-1", "wait", "每 10 秒檢查一次", 400, 420, params={"seconds": 10},
              description="安全連鎖要快一點：10 秒一輪。"),
        _node("jump-2", "jump", "正常：重新檢查", 400, 620, params={"target": "if_end-1"}),
        _note("n-2", "展示方式",
              "模擬器帶 --faults 時會不定期注入高溫事件；也可以在設備頁對 PCS 手動下 "
              "set_power_setpoint 500000 讓電池滿載升溫觀察。", 640, 820),
    ]
    edges = [
        _edge("start-1", "out", "if_end-1"),
        _edge("if_end-1", "true", "send_action-1"),
        _edge("if_end-1", "false", "wait-1"),
        _edge("if_end-1", "unknown", "wait-1"),
        _edge("wait-1", "out", "jump-2"),
        _edge("send_action-1", "sent", "condition_wait-1"),
        _edge("send_action-1", "failed", "condition_wait-1"),
        _edge("condition_wait-1", "met", "set_data-1"),
        _edge("condition_wait-1", "timeout", "send_action-2"),
        _edge("set_data-1", "sent", "jump-1"),
        _edge("set_data-1", "failed", "jump-1"),
        _edge("send_action-2", "sent", "end-1"),
        _edge("send_action-2", "failed", "end-1"),
    ]
    return {"nodes": nodes, "edges": edges}


# --------------------------------------------------------------------------
# 5. Demand-response drill: a one-shot sequence (discharge, hold, release)
# --------------------------------------------------------------------------
def demand_response_drill(discharge_kw: float, hold_seconds: int) -> dict:
    nodes = [
        _note("n-1", "需量反應演練（一次性流程）",
              f"模擬台電需量反應通知：電池以 {discharge_kw:.0f} kW 放電 {hold_seconds} 秒後恢復。\n"
              "沒有迴圈、跑完就結束，適合用「執行」按鈕現場示範：\n"
              "指令 → 設備 ack → 電表取用下降 → 區間與受益更新。", 400, 40),
        _node("start-1", "start", "收到需量反應通知", 40, 40),
        _node("if_end-1", "if_end", "電量足夠（> 30%）", 40, 220,
              params=_cond("{BESS}", "battery_soc", "gt", 30),
              description="電量不足就不參與，走 False 直接結束。"),
        _node("set_data-1", "set_data", f"放電 {discharge_kw:.0f} kW", 40, 420,
              params=_setpoint("{BESS}", int(discharge_kw * 1000))),
        _node("wait-1", "wait", f"維持 {hold_seconds} 秒", 40, 620,
              params={"seconds": hold_seconds}),
        _node("set_data-2", "set_data", "恢復待命", 40, 820, params=_setpoint("{BESS}", 0)),
        _node("end-1", "end", "演練結束", 40, 1020),
        _node("end-2", "end", "電量不足，不參與", 400, 420),
        _note("n-2", "可以搭配",
              "「單節點執行」能只跑選取的一個節點，例如只送「放電」指令看設備反應；\n"
              "「中斷點」可以讓流程停在某一步，檢視當下讀值再繼續。", 400, 620),
    ]
    edges = [
        _edge("start-1", "out", "if_end-1"),
        _edge("if_end-1", "true", "set_data-1"),
        _edge("if_end-1", "false", "end-2"),
        _edge("if_end-1", "unknown", "end-2"),
        _edge("set_data-1", "sent", "wait-1"),
        _edge("set_data-1", "failed", "end-2"),
        _edge("wait-1", "out", "set_data-2"),
        _edge("set_data-2", "sent", "end-1"),
        _edge("set_data-2", "failed", "end-1"),
    ]
    return {"nodes": nodes, "edges": edges}


# --------------------------------------------------------------------------
# 6. Orchestrator: starts another workflow (run_workflow), gated by time
# --------------------------------------------------------------------------
def orchestrator() -> dict:
    nodes = [
        _note("n-1", "主控：呼叫其他流程",
              "示範「執行工作流程」節點：工作日 08:00–20:00 啟動「需量反應演練」，"
              "否則結束。\n子流程獨立成一次執行，可在執行紀錄分別查看。", 400, 40),
        _node("start-1", "start", "開始", 40, 40),
        _node("if_end_time-1", "if_end_time", "工作日 08:00–20:00", 40, 220,
              params={"days": "weekdays", "start_time": "08:00", "end_time": "20:00",
                      "wait_for_window": False}),
        _node("run_workflow-1", "run_workflow", "啟動需量反應演練", 40, 420,
              params={"workflow_id": "{WORKFLOW:需量反應演練}"},
              description="子流程被拒絕（例如已停用）時走「已拒絕」分支。"),
        _node("end-1", "end", "已啟動", -160, 620),
        _node("end-2", "end", "未啟動", 240, 620),
    ]
    edges = [
        _edge("start-1", "out", "if_end_time-1"),
        _edge("if_end_time-1", "true", "run_workflow-1"),
        _edge("if_end_time-1", "false", "end-2"),
        _edge("run_workflow-1", "started", "end-1"),
        _edge("run_workflow-1", "refused", "end-2"),
    ]
    return {"nodes": nodes, "edges": edges}


#: name -> (description, site code, builder)
SHOWCASE_WORKFLOWS = [
    ("削峰與低電量保護", "兩條並行分支：需量連續 30 秒超過契約容量即放電削峰；電量低於 15% 即緊急停止。",
     "hsinchu-a", lambda: peak_shaving(680.0, 150.0)),
    ("離峰充電排程", "每天 22:30–06:30 離峰時段把電池充到 90%，跨午夜時間窗示範。",
     "hsinchu-a", lambda: offpeak_charging(300.0)),
    ("光電餘電優先充電", "光電出力超過 250 kW 時把餘電充進電池，回落即停；含「無讀值」分支處理。",
     "hsinchu-b", lambda: pv_surplus(250.0, 100.0)),
    ("電池溫度連鎖", "電池過溫即緊急停止，等待降溫後恢復；逾時則結束交由人員處理。",
     "taichung", thermal_interlock),
    ("需量反應演練", "一次性流程：電量足夠時放電 300 kW 維持 120 秒後恢復，適合現場按「執行」示範。",
     "taichung", lambda: demand_response_drill(300.0, 120)),
    ("主控排程", "工作日 08:00–20:00 啟動「需量反應演練」子流程；示範執行工作流程節點。",
     "taichung", orchestrator),
]


def render(graph: dict, devices: dict[str, str], workflows: dict[str, str]) -> dict:
    """Resolve ``{BESS}``-style device and ``{WORKFLOW:name}`` placeholders."""
    text = json.dumps(graph, ensure_ascii=False)
    for key, pk in devices.items():
        text = text.replace("{" + key + "}", pk)
    for name, pk in workflows.items():
        text = text.replace("{WORKFLOW:" + name + "}", pk)
    return json.loads(text)
