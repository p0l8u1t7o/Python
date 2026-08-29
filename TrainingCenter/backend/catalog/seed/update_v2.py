"""第二版種子資料調整（可重複執行）：

1. 氫廢燃料電池發電平台 → 氫燃料電池發電平台
2. 機器視覺相關模組歸到「軟體」領域
3. 新增「接頭與配線」模組與氣路／流體接頭元件
4. 新增「水氣電供應」模組（domain=utility）與各設備的水氣電教育訓練指南 utility_guide

執行：python backend/catalog/seed/update_v2.py，之後 manage.py load_seed、fetch_photos
"""

import json
from pathlib import Path

SEED_DIR = Path(__file__).parent


def comp(slug, name, category, function, install, pos, mesh, brand="", pn="", specs=None, anim="", pq=""):
    return {
        "slug": slug, "name": name, "category": category, "brand": brand, "part_number": pn,
        "function": function, "install_location": install, "specs": specs or {},
        "pos": pos, "mesh_name": mesh, "animation_key": anim, "photo_query": pq,
    }


# ---- 共用接頭元件（依設備給不同位置） ----
def connector_module(cab, rio, net):
    """cab: 電控櫃附近座標, rio: I/O 箱附近, net: 網路區"""
    cx, cy, cz = cab
    return {
        "slug": "connectors", "name": "接頭與配線模組", "domain": "electrical",
        "description": "感測器、動力與網路線路的標準接頭；新人拆裝線路前必須先認識。",
        "components": [
            comp("m12-connector", "M12 感測器圓形接頭", "接頭",
                 "感測器／電磁閥的標準防水接頭（IP67），A-code 3～5 pin；螺牙鎖緊避免振動鬆脫。",
                 "各感測器線末端、遠端 I/O 箱側面", rio, "conn-m12",
                 "範例：Phoenix Contact", "SAC-4P-M12MS", {"防護": "IP67", "極數": "4 pin A-code"},
                 pq="M12 connector sensor | cat:Electrical connectors ~ M12"),
            comp("terminal-block", "DIN 軌端子台", "接頭",
                 "櫃內配線的中繼點，每個端子有編號對應電路圖；接地端子為黃綠色。",
                 "電控櫃下方 DIN 軌", [cx, cy - 0.35, cz + 0.28], "conn-terminal",
                 "範例：Phoenix Contact", "UT 2,5", {"線徑": "0.14～4 mm²"},
                 pq="terminal block DIN rail | cat:Terminal blocks ~ DIN"),
            comp("cable-gland", "電纜固定頭 (Cable Gland)", "接頭",
                 "線纜穿入櫃體時固定並保持 IP 防護、防止拉扯。",
                 "電控櫃底板進線處", [cx, cy - 0.7, cz + 0.28], "conn-gland",
                 "範例：Lapp", "SKINTOP ST-M20", {"防護": "IP68", "線徑": "7～13 mm"},
                 pq="cable gland | cat:Cable glands"),
            comp("heavy-duty-connector", "重載矩形接頭 (Harting)", "接頭",
                 "多芯動力＋訊號一次插拔，機台分段運輸／維修時快速拆接。",
                 "電控櫃側面與機台段間的線路介面", [cx + 0.42, cy, cz], "conn-hdc",
                 "範例：Harting", "Han 24B", {"極數": "24+PE", "電流": "16 A"},
                 pq="Harting connector | heavy duty connector industrial"),
            comp("ethernet-connector", "工業乙太網路接頭 (RJ45 / M12 D-code)", "接頭",
                 "PLC、相機、手臂控制器之間的通訊線路接頭；工業級 RJ45 有鎖扣與防護殼。",
                 "交換器與各控制器網路埠", net, "conn-rj45",
                 "範例：Phoenix Contact", "VS-08-RJ45-5-Q/IP20", {"等級": "Cat.5e", "防護": "IP20 / IP67 (M12)"},
                 pq="industrial ethernet connector M12 | RJ45 connector industrial | cat:RJ45 ~ industrial"),
            comp("power-connector", "動力接頭與馬達插頭", "接頭",
                 "伺服／變頻馬達的動力與編碼器線用專用航空插頭，接錯相序馬達會反轉。",
                 "各馬達尾端", [cx - 0.5, cy - 0.3, cz + 0.3], "conn-power",
                 "範例：Intercontec", "M23", {"極數": "8 pin + 編碼器 17 pin"},
                 pq="M23 connector servo | circular connector industrial | cat:Electrical connectors ~ circular"),
        ],
    }


def utility_module(eq_slug, power_pos, air_pos, water_pos=None, ground_pos=None):
    comps = [
        comp("main-breaker", "主電源無熔絲斷路器 (NFB) 與隔離開關", "水氣電供應",
             "設備電力總開關，具過載／短路保護；維修前務必切至 OFF 並上鎖掛牌 (LOTO)。",
             "電控櫃右側門把上方（紅黃色旋鈕）", power_pos, "util-breaker",
             "範例：Schneider", "NSX100", {"額定": "3P 100 A", "遮斷容量": "36 kA"}, anim="blink",
             pq="cat:Circuit breakers ~ industrial | circuit breaker cabinet | cat:Circuit breakers"),
        comp("power-inlet", "電源進線端與匯流排", "水氣電供應",
             "廠務 3Φ 380 VAC 由此進入，經 NFB 後分配至驅動器、變壓器與 24 V 電源。",
             "電控櫃頂部進線孔 → 端子台 L1/L2/L3/N/PE", [power_pos[0], power_pos[1] + 0.45, power_pos[2]], "util-inlet",
             "", "", {"電壓": "3Φ 380 VAC 50/60 Hz", "線徑": "14 mm²"},
             pq="cat:Busbars ~ cabinet | busbar electrical cabinet | cat:Electrical enclosures ~ cabinet"),
        comp("grounding", "接地端子 (PE)", "水氣電供應",
             "所有金屬機殼與櫃體以黃綠線接至 PE 排；接地不良會造成感電與雜訊。",
             "電控櫃底部 PE 排、機架接地點", ground_pos or [power_pos[0], power_pos[1] - 0.8, power_pos[2] + 0.2], "util-pe",
             "", "", {"接地電阻": "< 10 Ω"},
             pq="grounding busbar | earth terminal cabinet | cat:Electrical grounding"),
        comp("air-inlet", "壓縮空氣進氣口與主氣閥 (含排氣鎖定)", "水氣電供應",
             "廠務壓縮空氣由此進入；主氣閥為可上鎖的 3 口閥，關閉時同時把下游殘壓排空。",
             "機架側面 FRL 前端（黃色手柄球閥）", air_pos, "util-airvalve",
             "範例：SMC", "VHS40-04", {"供氣壓力": "0.6～0.7 MPa", "口徑": "1/2\"", "露點": "≤ 3 °C"}, anim="valve",
             pq="cat:Ball valves ~ pneumatic | lockout valve pneumatic | cat:Ball valves"),
    ]
    if water_pos:
        comps.append(comp("water-inlet", "冷卻水進／出水口與球閥", "水氣電供應",
                          "廠務冰水（或純水）供應與回水，進出口有球閥與流量計；開機前先確認流量。",
                          "平台後側散熱器旁（藍色進水、紅色回水）", water_pos, "util-water",
                          "", "", {"水質": "去離子水 < 5 µS/cm", "流量": "≥ 20 L/min", "接頭": "1/2\" 快速接頭"}, anim="flow",
                          pq="cat:Ball valves ~ water | water ball valve pipe | cat:Water supply"))
    return {
        "slug": "utility", "name": "水氣電供應模組", "domain": "utility",
        "description": "設備需要的電力、壓縮空氣（與冷卻水）從哪裡來、怎麼開關、怎麼上鎖。",
        "components": comps,
    }


GUIDE_COMMON_POWER = {
    "title": "電力 (Electricity)",
    "icon": "bolt",
    "items": [
        "供電規格：3Φ 380 VAC ±10%、50/60 Hz，由廠務配電盤專用迴路供應，迴路 NFB 額定見電控櫃銘牌。",
        "接點位置：電控櫃頂部進線 → 主 NFB → 端子台 L1/L2/L3/N/PE；控制電壓 24 VDC 由櫃內開關電源提供。",
        "送電順序：確認櫃門關閉 → 廠務迴路 ON → 設備主 NFB ON → 控制電源 (24 V) ON → HMI 開機 → 復歸急停。",
        "斷電順序：HMI 執行停機 → 急停 → 控制電源 OFF → 主 NFB OFF → 上鎖掛牌 (LOTO)。",
        "安全：斷電後驅動器內電容仍有高壓，等待 5 分鐘並用電表確認 DC 匯流排 < 50 V 才可作業。",
    ],
}
GUIDE_COMMON_AIR = {
    "title": "壓縮空氣 (Compressed Air)",
    "icon": "air",
    "items": [
        "供氣規格：0.6～0.7 MPa、露點 ≤ 3 °C、含油量 ≤ 0.01 mg/m³（ISO 8573-1 Class 1.4.1），流量依銘牌。",
        "接點位置：機架側面主氣閥（可上鎖 3 口閥）→ FRL 三點組合 → 電磁閥組 → 各氣缸。",
        "供氣順序：確認 FRL 設定壓力 0.5 MPa → 慢開主氣閥（或用緩啟動閥）避免氣缸瞬間動作 → 檢查漏氣聲。",
        "斷氣順序：關主氣閥 → 排氣口洩壓至 0 → 壓力表歸零後才可拆氣管；含蓄壓器的氣路需另外洩壓。",
        "日常點檢：FRL 濾杯排水、壓力表讀值、氣管有無龜裂、速度控制閥有無鬆動。",
    ],
}
GUIDE_COMMON_LOTO = {
    "title": "上鎖掛牌 (LOTO) 與點檢",
    "icon": "lock",
    "items": [
        "維修前一律：斷電 → 斷氣（→ 斷水）→ 洩壓 → 上鎖 → 掛牌 → 嘗試啟動確認零能量。",
        "每人一把鎖，誰上鎖誰解鎖；多人作業使用多鎖扣。",
        "日常點檢表：電壓／電流讀值、供氣壓力、（水流量／溫度）、接地連續性、警報紀錄。",
    ],
}


def guide(*extra):
    return [GUIDE_COMMON_POWER, GUIDE_COMMON_AIR, *extra, GUIDE_COMMON_LOTO]


def upsert_module(data, module):
    mods = data["modules"]
    for i, m in enumerate(mods):
        if m["slug"] == module["slug"]:
            mods[i] = module
            return
    mods.append(module)


def add_components(data, module_slug, comps):
    for m in data["modules"]:
        if m["slug"] == module_slug:
            existing = {c["slug"] for c in m["components"]}
            m["components"] += [c for c in comps if c["slug"] not in existing]
            return
    raise KeyError(module_slug)


def load(slug):
    return json.loads((SEED_DIR / f"{slug}.json").read_text(encoding="utf-8"))


def save(slug, data):
    (SEED_DIR / f"{slug}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------- fuel-cell ----------
d = load("fuel-cell")
d["name"] = "氫燃料電池發電平台"
d["summary"] = "回收製程氫氣，經純化後送入 PEM 燃料電池堆發電，並以 DC/DC 與併網逆變器輸出電力。"
d["description"] = d["description"].replace("廢氫", "氫氣")
for m in d["modules"]:
    for c in m["components"]:
        c["function"] = c["function"].replace("廢氫", "氫氣")
add_components(d, "h2-supply", [
    comp("tube-fitting", "不鏽鋼雙套環管接頭 (Swagelok)", "接頭",
         "氫氣管路的標準接頭，前後套環咬合管壁形成金屬密封；鎖緊圈數依規範（1-1/4 圈）。",
         "氫氣管路每個轉接處", [-1.2, 0.72, 0.1], "fit-tube", "範例：Swagelok", "SS-400-6",
         {"管徑": "1/4\"", "材質": "316 SS"}, pq="Swagelok fitting | compression fitting stainless tube"),
    comp("vcr-fitting", "VCR 面封接頭", "接頭",
         "以金屬墊片面封，洩漏率極低，用於電堆入口等高潔淨氫氣段；每次拆裝需換墊片。",
         "電堆陽極入口", [-0.45, 0.7, 0.05], "fit-vcr", "範例：Swagelok", "SS-4-VCR",
         {"密封": "金屬墊片", "洩漏率": "< 4×10⁻⁹ atm·cc/s He"}, pq="VCR fitting face seal | stainless steel tube fitting | cat:Compression fittings"),
])
add_components(d, "thermal", [
    comp("coolant-quick-connect", "冷卻液快速接頭", "接頭",
         "拆電堆或散熱器時可不排空冷卻液即斷開，雙向自動止漏。",
         "電堆冷卻液進出口軟管端", [-0.2, 0.42, -0.35], "fit-coolant", "範例：CPC", "NS4 系列",
         {"口徑": "1/2\"", "材質": "PP / EPDM"}, pq="quick disconnect coupling liquid | quick coupling hose | cat:Hoses ~ coupling"),
])
upsert_module(d, connector_module(cab=[-2.2, 0.9, -0.8], rio=[-1.8, 0.75, -0.55], net=[-2.5, 0.95, -0.55]))
upsert_module(d, utility_module("fuel-cell", power_pos=[-2.55, 1.2, -0.55], air_pos=[-2.6, 0.5, 0.4],
                                water_pos=[0.7, 0.35, -1.3]))
d["utility_guide"] = guide(
    {
        "title": "冷卻水 (Cooling Water)",
        "icon": "water",
        "items": [
            "水質：電堆冷卻迴路為去離子水，導電度 < 5 µS/cm；廠務冰水只接到板式熱交換器一次側，不可直接進電堆。",
            "接點位置：平台後側散熱器旁，藍色為進水、紅色為回水，各有球閥與流量計。",
            "供水順序：先開回水閥再開進水閥 → 確認流量 ≥ 20 L/min → 觀察管路無滲漏 → 才允許電堆啟動。",
            "斷水順序：電堆停機且溫度 < 40 °C 後，先關進水再關回水；冬季長期停機需排空防凍。",
            "點檢：去離子濾芯導電度、水位、泵浦噪音、快速接頭有無滲漏。",
        ],
    },
    {
        "title": "氫氣 (Hydrogen) 特別注意",
        "icon": "gas",
        "items": [
            "氫氣為易燃氣體 (LEL 4%)，作業區禁火、使用防爆工具；頂棚偵測器 > 25% LEL 會自動切斷供氫。",
            "供氫順序：開啟排風 → 確認氫氣偵測器正常 → 開儲槽閥 → 減壓閥設定 0.8 bar → 氮氣吹掃 → 才通氫。",
            "斷氫順序：關儲槽閥 → 讓電堆消耗管內殘氫 → 氮氣吹掃 → 關閉電磁閥。",
        ],
    },
)
save("fuel-cell", d)

# ---------- aoi ----------
d = load("aoi")
for m in d["modules"]:
    if m["slug"] == "vision-hw":
        m["domain"] = "software"
        m["name"] = "機器視覺：影像擷取"
        m["description"] = "相機、鏡頭與光源決定影像品質，是視覺軟體的輸入端；歸在軟體領域一併學習。"
add_components(d, "conveyor", [
    comp("push-in-fitting", "氣管快速接頭 (Push-in Fitting)", "接頭",
         "氣管直接插入即密封，按壓釋放環即可拔出；Ø6／Ø4 管徑對應不同接頭。",
         "各氣缸與電磁閥組的氣口", [0.9, 0.42, 0.55], "fit-pushin", "範例：SMC", "KQ2H06-01S",
         {"管徑": "Ø6 mm", "螺牙": "R1/8"}, pq="push-in fitting pneumatic | pneumatic fitting tube | cat:Pneumatics ~ fitting | cat:Pneumatic hoses ~ fitting"),
    comp("quick-coupler", "氣源快速接頭 (Coupler)", "接頭",
         "機台與廠務氣源之間的快拆接頭，母座具自動止氣閥。",
         "主氣閥出口", [-1.6, 0.42, 0.5], "fit-coupler", "範例：SMC", "KK4S-08H",
         {"口徑": "1/4\""}, pq="pneumatic quick coupler | air hose quick coupling"),
])
upsert_module(d, connector_module(cab=[-1.2, 0.6, -0.9], rio=[1.0, 0.55, 0.5], net=[-1.55, 1.0, -0.6]))
upsert_module(d, utility_module("aoi", power_pos=[-1.45, 1.05, -0.7], air_pos=[-1.7, 0.4, 0.5]))
d["utility_guide"] = guide()
save("aoi", d)

# ---------- transfer ----------
d = load("transfer")
add_components(d, "pneumatic", [
    comp("quick-coupler", "氣源快速接頭 (Coupler)", "接頭",
         "機台與廠務氣源之間的快拆接頭，母座具自動止氣閥。",
         "主氣閥出口", [-2.8, 0.45, 0.4], "fit-coupler", "範例：SMC", "KK4S-08H",
         {"口徑": "1/4\""}, pq="pneumatic quick coupler | air hose quick coupling"),
])
upsert_module(d, connector_module(cab=[2.9, 0.75, -0.6], rio=[0.7, 0.68, 0.45], net=[2.9, 1.15, -0.35]))
upsert_module(d, utility_module("transfer", power_pos=[3.25, 1.1, -0.35], air_pos=[-2.9, 0.45, 0.4]))
d["utility_guide"] = guide({
    "title": "AGV 對接站供電",
    "icon": "bolt",
    "items": [
        "對接站的光通訊模組由線體 24 V 供電，AGV 本身由車載電池供電並在充電站補電，兩者無電氣連接。",
        "AGV 充電站為獨立 48 V 迴路，維修對接站不需切 AGV 充電站電源。",
    ],
})
save("transfer", d)

# ---------- robot-cell ----------
d = load("robot-cell")
for m in d["modules"]:
    if m["slug"] == "vision":
        m["domain"] = "software"
        m["name"] = "機器視覺與手眼協調"
add_components(d, "eoat", [
    comp("push-in-fitting", "氣管快速接頭 (Push-in Fitting)", "接頭",
         "夾爪／吸盤的 Ø4 氣管接頭，隨手臂運動的氣管要用耐彎折的 PU 管。",
         "夾爪氣口與手臂上的中繼板", [-1.05, 1.5, 0.08], "fit-pushin", "範例：SMC", "KQ2H04-M5",
         {"管徑": "Ø4 mm", "螺牙": "M5"}, pq="push-in fitting pneumatic | pneumatic fitting tube | cat:Pneumatics ~ fitting | cat:Pneumatic hoses ~ fitting"),
    comp("rotary-union", "旋轉接頭 (Rotary Union)", "接頭",
         "讓氣路穿過 J6 無限旋轉而不纏管。",
         "J6 末端與法蘭之間", [-1.05, 1.55, -0.06], "fit-rotary", "範例：Deublin", "1101-020",
         {"通道": "2", "壓力": "0.7 MPa"}, pq="rotary union pneumatic | rotary joint swivel | cat:Swivel joints"),
])
upsert_module(d, connector_module(cab=[2.8, 0.9, -1.2], rio=[-1.9, 0.9, -0.4], net=[2.55, 0.85, -0.9]))
upsert_module(d, utility_module("robot-cell", power_pos=[3.4, 1.4, -1.0], air_pos=[2.6, 0.5, 1.2]))
d["utility_guide"] = guide({
    "title": "機械手臂專用注意事項",
    "icon": "robot",
    "items": [
        "手臂控制器需獨立迴路（每台 1Φ 200～240 VAC 或 3Φ 200 VAC，依型號），電源異常會遺失原點需重新校正。",
        "斷電前先把手臂移到 HOME 姿態；J2/J3 煞車失效時手臂會下墜，維修上臂需先以吊帶固定。",
        "夾爪氣壓消失時工件會掉落，斷氣前先把工件放到安全位置。",
    ],
})
save("robot-cell", d)
print("seed v2 updated")
