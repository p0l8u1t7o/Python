/**
 * The glossary. One entry per term, one place to change it.
 *
 * Why this lives here and not in `src/i18n/locales/*.ts` like everything else:
 * a glossary entry is not three independent strings, it is one explanation
 * that happens to exist in three languages. Keeping them adjacent is what
 * makes it possible to notice that the zh-Hans text is a naive conversion of
 * the zh-Hant one rather than the term a mainland engineer would actually use
 * (光伏 not 太陽光電, 固件 not 韌體, 分时电价 not 時間電價). Split across three
 * files those mistakes are invisible.
 *
 * `expansion` is the English original and is deliberately **not** translated.
 * Someone reading a Chinese UI still has to recognise "SOC" in a datasheet.
 *
 * Adding a term: append an entry here, then use `<Term id="…" />` at the label
 * where it first appears. TypeScript requires all three languages, so a
 * half-finished entry will not compile.
 */

import type { SupportedLanguage } from '@/i18n'

export interface GlossaryEntry {
  /** The abbreviation as it appears in the UI, if the term is one. */
  abbr?: string
  /** English expansion of the abbreviation. Never localised. */
  expansion?: string
  /** The term's name, per language. */
  label: Record<SupportedLanguage, string>
  /** One to three sentences. What it means and why it matters here. */
  definition: Record<SupportedLanguage, string>
  /** Unit shown alongside the name, e.g. `%` or `kWh`. */
  unit?: string
}

export const GLOSSARY = {
  // -------------------------------------------------------------------
  // Battery and power conversion
  // -------------------------------------------------------------------
  soc: {
    abbr: 'SOC',
    expansion: 'State of Charge',
    unit: '%',
    label: {
      en: 'State of charge',
      'zh-Hant': '荷電狀態',
      'zh-Hans': '荷电状态',
    },
    definition: {
      en: 'How full the battery is right now, as a percentage of its usable capacity. 0 % is empty, 100 % is full. It is an estimate the battery management system calculates — not a direct measurement — so it can drift and be recalibrated.',
      'zh-Hant':
        '電池目前的剩餘電量，以可用容量的百分比表示。0 % 是空的，100 % 是滿的。這個數字是電池管理系統「推算」出來的，不是直接量到的，所以會漂移，也會被重新校正。',
      'zh-Hans':
        '电池当前的剩余电量，以可用容量的百分比表示。0 % 为空，100 % 为满。该数值由电池管理系统推算得出，并非直接测量，因此会产生漂移，也会被重新标定。',
    },
  },
  soh: {
    abbr: 'SoH',
    expansion: 'State of Health',
    unit: '%',
    label: {
      en: 'State of health',
      'zh-Hant': '電池健康度',
      'zh-Hans': '电池健康度',
    },
    definition: {
      en: 'Present usable capacity as a percentage of the capacity when new. A battery at 80 % SoH stores four fifths of what it originally did. This falls slowly over years and is the main measure of ageing — unlike SOC, it does not recover after charging.',
      'zh-Hant':
        '電池現在的可用容量相對於全新時的百分比。SoH 80 % 表示只剩下當初的八成。它會隨著年份緩慢下降，是判斷老化的主要指標——和 SOC 不同，充電並不會讓它回升。',
      'zh-Hans':
        '电池当前可用容量相对于全新时的百分比。SoH 为 80 % 表示仅剩出厂时的八成。该值随使用年限缓慢下降，是判断电池老化的主要指标——与 SOC 不同，充电并不会使其回升。',
    },
  },
  dod: {
    abbr: 'DoD',
    expansion: 'Depth of Discharge',
    unit: '%',
    label: {
      en: 'Depth of discharge',
      'zh-Hant': '放電深度',
      'zh-Hans': '放电深度',
    },
    definition: {
      en: 'How much of the battery was drawn down in one discharge, as a percentage. DoD and SOC are complements: discharging to 20 % SOC is an 80 % DoD. Deeper cycles wear the cells faster, so storage plans usually keep a reserve rather than emptying the pack.',
      'zh-Hant':
        '一次放電中用掉的電量佔比。DoD 和 SOC 互補：放到 SOC 20 % 就是 80 % 的 DoD。放得越深，電芯老化越快，所以儲能策略通常會保留一段電量不用完。',
      'zh-Hans':
        '一次放电中放出的电量占比。DoD 与 SOC 互补：放电至 SOC 20 % 即为 80 % 的 DoD。放电深度越大，电芯衰减越快，因此储能策略通常会保留一部分电量而不放空。',
    },
  },
  pcs: {
    abbr: 'PCS',
    expansion: 'Power Conversion System',
    label: {
      en: 'Power conversion system',
      'zh-Hant': '儲能變流器',
      'zh-Hans': '储能变流器',
    },
    definition: {
      en: 'The bidirectional inverter between the battery and the AC grid. It turns DC into AC when discharging and back again when charging, and it is what actually executes a power setpoint — the battery cells only store energy, the PCS decides how fast it moves.',
      'zh-Hant':
        '接在電池和交流電網之間的雙向變流器。放電時把直流轉成交流，充電時反過來。實際執行功率設定值的是它——電芯只負責儲存能量，充放電的速度由 PCS 決定。',
      'zh-Hans':
        '连接电池与交流电网的双向变流器。放电时将直流转换为交流，充电时反向转换。实际执行功率设定值的是它——电芯只负责储存能量，充放电速率由 PCS 决定。',
    },
  },
  bess: {
    abbr: 'BESS',
    expansion: 'Battery Energy Storage System',
    label: {
      en: 'Battery energy storage system',
      'zh-Hant': '電池儲能系統',
      'zh-Hans': '电池储能系统',
    },
    definition: {
      en: 'The whole installation, not just the cells: battery modules, the PCS, the battery management system, thermal control and switchgear. When a site is described as "1 MW / 2 MWh" the first number is the PCS power rating and the second is the battery energy capacity.',
      'zh-Hant':
        '整套設備，不只是電芯：電池模組、PCS、電池管理系統、溫控與開關設備。案場寫「1 MW / 2 MWh」時，前面是 PCS 的功率額定，後面是電池的電量容量。',
      'zh-Hans':
        '整套系统，不仅指电芯：电池模组、PCS、电池管理系统、热管理与开关设备。项目标注「1 MW / 2 MWh」时，前者是 PCS 的功率额定值，后者是电池的能量容量。',
    },
  },
  btm: {
    abbr: 'BTM',
    expansion: 'Behind the Meter',
    label: {
      en: 'Behind the meter',
      'zh-Hant': '表後（用戶側）',
      'zh-Hans': '表后（用户侧）',
    },
    definition: {
      en: 'Equipment on the customer’s side of the utility revenue meter. Energy it produces or stores never passes through the meter, so it reduces the bill directly rather than being sold to the grid. The opposite, front-of-meter, is generation that exists to sell power.',
      'zh-Hant':
        '裝在電表「用戶這一側」的設備。它發出或儲存的電不會經過電表，所以是直接抵掉電費，而不是賣給電網。相對的「表前」則是為了售電而存在的發電設備。',
      'zh-Hans':
        '安装在关口计量表用户侧的设备。其发出或储存的电量不经过计量表，因此直接抵减电费，而非上网销售。与之相对的「表前（电网侧）」则是以售电为目的的发电设施。',
    },
  },
  pv: {
    abbr: 'PV',
    expansion: 'Photovoltaic',
    label: {
      en: 'Solar PV',
      'zh-Hant': '太陽光電',
      'zh-Hans': '光伏',
    },
    definition: {
      en: 'Solar panels and their inverters. Output follows sunlight, so it peaks around midday and is zero at night — which is why pairing it with storage matters: the surplus at noon is what covers the evening load.',
      'zh-Hant':
        '太陽能板與其變流器。發電量跟著日照走，中午最高、晚上為零——這正是要搭配儲能的原因：中午多出來的電，拿去補晚上的用電。',
      'zh-Hans':
        '光伏组件及其逆变器。出力随日照变化，正午最高、夜间为零——这正是需要配置储能的原因：正午的富余电量用于覆盖傍晚的负荷。',
    },
  },
  ems: {
    abbr: 'EMS',
    expansion: 'Energy Management System',
    label: {
      en: 'Energy management system',
      'zh-Hant': '能源管理系統',
      'zh-Hans': '能量管理系统',
    },
    definition: {
      en: 'The layer that decides what the storage should do — charge, discharge or sit idle — based on tariffs, load, solar output and demand limits. This platform is the EMS: devices report, it computes, and it sends the resulting setpoints back down.',
      'zh-Hant':
        '決定儲能該做什麼（充電、放電還是待機）的那一層，依據電價、負載、發電量與需量上限來判斷。這個平台就是 EMS：設備上報資料，平台計算，再把設定值下發回去。',
      'zh-Hans':
        '负责决策储能动作（充电、放电或待机）的层级，依据电价、负荷、发电出力与需量上限进行判断。本平台即为 EMS：设备上报数据，平台计算，再将设定值下发。',
    },
  },
  usableCapacity: {
    label: {
      en: 'Usable capacity',
      'zh-Hant': '可用容量',
      'zh-Hans': '可用容量',
    },
    unit: 'kWh',
    definition: {
      en: 'The energy the battery is actually allowed to cycle, which is less than the nameplate rating. Manufacturers reserve headroom at both ends because charging to 100 % or emptying to 0 % shortens cell life. Savings are computed against this figure, not the nameplate.',
      'zh-Hant':
        '電池實際允許使用的電量，會小於銘牌標示的容量。廠商會在上下兩端各保留一段餘裕，因為充到 100 % 或放到 0 % 都會縮短電芯壽命。節費計算用的是這個數字，不是銘牌值。',
      'zh-Hans':
        '电池实际允许循环的电量，小于铭牌标称容量。厂商会在上下限各预留一部分裕量，因为充至 100 % 或放至 0 % 都会缩短电芯寿命。节费计算基于该数值，而非铭牌值。',
    },
  },

  // -------------------------------------------------------------------
  // Units and billing
  // -------------------------------------------------------------------
  kwVsKwh: {
    label: {
      en: 'kW vs kWh',
      'zh-Hant': 'kW 與 kWh 的差別',
      'zh-Hans': 'kW 与 kWh 的区别',
    },
    definition: {
      en: 'kW is a rate, kWh is an amount. A 5 kW load running for 2 hours consumes 10 kWh. Bills usually charge for both separately: kWh for energy used, and kW for the highest rate you ever drew. Confusing the two is the most common mistake when reading these pages.',
      'zh-Hant':
        'kW 是「速率」，kWh 是「數量」。5 kW 的負載用 2 小時，就是 10 kWh。電費通常兩者分開收：kWh 算用了多少電，kW 算你曾經拉到多高。看這幾頁時最常見的誤解就是把兩者混為一談。',
      'zh-Hans':
        'kW 是「功率」，kWh 是「电量」。5 kW 的负荷运行 2 小时即为 10 kWh。电费通常分开计收：kWh 计量用电量，kW 计量最高用电功率。阅读本页面时最常见的误解就是将两者混淆。',
    },
  },
  contractCapacity: {
    label: {
      en: 'Contract capacity',
      'zh-Hant': '契約容量',
      'zh-Hans': '合同容量（需量申报值）',
    },
    unit: 'kW',
    definition: {
      en: 'The power level agreed with the utility. You pay a fixed monthly charge for it whether you use it or not, and exceeding it triggers a penalty on top. Storage earns its keep partly by keeping demand under this line so the contracted figure can be set lower.',
      'zh-Hant':
        '與台電約定的用電容量。不管有沒有用到，每個月都要按這個數字繳基本電費；超過還要另外罰。儲能的價值有一部分就在於把需量壓在這條線以下，讓契約容量可以簽低一點。',
      'zh-Hans':
        '与供电公司约定的用电容量。无论是否用满，每月均按此数值收取基本电费；超出部分另计罚费。储能的价值之一，就是将需量控制在该限值以下，从而可以申报更低的容量。',
    },
  },
  demand: {
    label: {
      en: 'Demand',
      'zh-Hant': '需量',
      'zh-Hans': '需量',
    },
    unit: 'kW',
    definition: {
      en: 'Average power over a fixed billing interval, typically 15 minutes — not the instantaneous reading. A one-second spike barely moves it, but a sustained load does. This averaging is why a battery only needs to cover a short burst to cut the demand charge.',
      'zh-Hant':
        '一個計費區間（通常 15 分鐘）內的平均功率，不是瞬時值。一秒鐘的尖波幾乎不影響它，持續的負載才會。正因為是取平均，電池只要撐過那一小段就能壓下需量電費。',
      'zh-Hans':
        '一个计费区间（通常 15 分钟）内的平均功率，而非瞬时值。持续一秒的尖峰几乎不影响该值，持续性负荷才会。正因为是取平均值，电池只需覆盖较短的时段即可降低需量电费。',
    },
  },
  peakDemand: {
    label: {
      en: 'Peak demand',
      'zh-Hant': '尖峰需量',
      'zh-Hans': '最大需量',
    },
    unit: 'kW',
    definition: {
      en: 'The highest demand interval in the billing period. One bad quarter-hour sets the charge for the whole month, which is why a single unmanaged event can undo weeks of savings.',
      'zh-Hant':
        '整個計費期間內最高的那一個需量區間。一個月的需量電費由那一刻決定，所以只要有一次沒守住，前面幾週省下來的可能就白費了。',
      'zh-Hans':
        '整个计费周期内最高的那一个需量区间。整月的需量电费由该时刻决定，因此一次失控就可能抵消数周的节费成果。',
    },
  },
  coincidentPeak: {
    label: {
      en: 'Coincident peak',
      'zh-Hant': '同時尖峰',
      'zh-Hans': '同时最大需量',
    },
    unit: 'kW',
    definition: {
      en: 'For a group of sites, the highest total drawn at the same moment. It is computed by summing each interval first and then taking the maximum — never by adding up each site’s individual peak, which would overstate the figure because those peaks happen at different times.',
      'zh-Hant':
        '一群案場「在同一時刻」的用電總和的最高值。算法是先把每個區間相加、再取最大值——絕對不能把各案場各自的尖峰加起來，那樣會高估，因為它們的尖峰不在同一時間發生。',
      'zh-Hans':
        '一组站点「在同一时刻」的用电总和的最大值。计算方式是先对每个区间求和、再取最大值——不能将各站点各自的峰值相加，那样会高估，因为各站点的峰值并不出现在同一时刻。',
    },
  },
  peakShaving: {
    label: {
      en: 'Peak shaving',
      'zh-Hant': '削峰',
      'zh-Hans': '削峰填谷',
    },
    definition: {
      en: 'Discharging the battery during the short windows when site demand would otherwise set a new peak, so the billed maximum stays down. It saves money on the demand charge even when total energy consumption is unchanged.',
      'zh-Hant':
        '在案場需量即將創新高的那幾個短時段放電，把計費用的最高值壓下來。就算總用電量完全沒變，也能省下需量電費。',
      'zh-Hans':
        '在站点需量即将创新高的短时段内放电，压低计费用的最大值；低谷时段充电则称为填谷。即使总用电量不变，也能降低需量电费。',
    },
  },
  tariff: {
    label: {
      en: 'Tariff',
      'zh-Hant': '電價方案',
      'zh-Hans': '电价方案',
    },
    definition: {
      en: 'The pricing rules the site is billed under: energy rates by time of day, the demand charge, and any export price. Every cost and savings figure on these pages comes from applying the site’s tariff to its measured intervals, so a wrong tariff makes the numbers wrong rather than merely imprecise.',
      'zh-Hant':
        '案場適用的計價規則：分時段的電能費率、需量電費，以及躉售價格。這些頁面上的所有費用與節費數字，都是把電價方案套到實測區間算出來的——電價設錯，數字就是錯的，不只是不準。',
      'zh-Hans':
        '站点适用的计价规则：分时段的电度电价、需量电费，以及上网电价。本页面所有费用与节费数字，均由电价方案套用于实测区间计算得出——电价配置错误会导致结果错误，而不只是不够精确。',
    },
  },
  touArbitrage: {
    abbr: 'ToU',
    expansion: 'Time of Use',
    label: {
      en: 'Time-of-use arbitrage',
      'zh-Hant': '時間電價套利',
      'zh-Hans': '分时电价套利',
    },
    definition: {
      en: 'Charging when energy is cheap and discharging when it is expensive, profiting from the price difference. It only pays if the spread is wider than the round-trip loss plus the cost of the wear the extra cycling causes.',
      'zh-Hant':
        '電價便宜時充電、貴時放電，賺取價差。只有當價差大於往返效率的損失、再加上多充放一次造成的電池損耗成本時，這樣做才划算。',
      'zh-Hans':
        '在电价低谷时段充电、高峰时段放电，赚取价差。只有当价差大于往返效率损失加上额外循环带来的电池损耗成本时，该策略才有收益。',
    },
  },
  selfConsumption: {
    label: {
      en: 'Self-consumption',
      'zh-Hant': '自用率',
      'zh-Hans': '自发自用率',
    },
    unit: '%',
    definition: {
      en: 'The share of solar generation used on site instead of being exported. Looks at it from the generation side: of everything the panels made, how much stayed here. Storage raises it by holding midday surplus for the evening.',
      'zh-Hant':
        '發電量之中，留在案場自己用掉、沒有躉售出去的比例。這是從「發電端」看：太陽能發的電，有多少留在自己家。儲能把中午的餘電留到晚上用，就能提高這個比例。',
      'zh-Hans':
        '光伏发电量中在本站消纳、未上网的比例。这是从「发电侧」看：组件发出的电有多少留在本地使用。储能将正午的富余电量留到傍晚使用，即可提高该比例。',
    },
  },
  selfSufficiency: {
    label: {
      en: 'Self-sufficiency',
      'zh-Hant': '自給率',
      'zh-Hans': '自给率',
    },
    unit: '%',
    definition: {
      en: 'The share of site load met without importing from the grid. Looks at it from the consumption side, which is why it is not the same number as self-consumption: a site can consume all of its solar and still import most of what it needs.',
      'zh-Hant':
        '案場用電之中，不靠電網、由自己供應的比例。這是從「用電端」看，所以和自用率不是同一個數字：太陽能可能百分之百自用，但案場仍然大部分電要跟電網買。',
      'zh-Hans':
        '站点负荷中无需从电网购电、由本地供应的比例。这是从「用电侧」看，因此与自发自用率并非同一数值：光伏可能全部自用，但站点仍需从电网购入大部分用电。',
    },
  },
  roundTrip: {
    label: {
      en: 'Round-trip efficiency',
      'zh-Hant': '往返效率',
      'zh-Hans': '往返效率',
    },
    unit: '%',
    definition: {
      en: 'Energy out divided by energy in over a full charge-and-discharge cycle. Around 85–90 % is typical; the missing part is lost as heat in the cells and the PCS. It means stored energy is always worth less than it cost, so arbitrage needs a price spread wider than the loss.',
      'zh-Hant':
        '完整充放一次之後，放出來的電除以充進去的電。一般在 85–90 % 之間，少掉的部分變成電芯與 PCS 的熱。這代表存起來的電一定比當初買的貴，所以套利的價差必須大於這個損失。',
      'zh-Hans':
        '完整充放一次后，放出电量除以充入电量。通常为 85–90 %，损失部分以热能形式散失于电芯与 PCS。这意味着储存的电量成本始终高于购入成本，因此套利的价差必须大于该损失。',
    },
  },

  // -------------------------------------------------------------------
  // Platform architecture
  // -------------------------------------------------------------------
  telemetry: {
    label: {
      en: 'Telemetry',
      'zh-Hant': '遙測',
      'zh-Hans': '遥测',
    },
    definition: {
      en: 'Measurements the device reports on its own schedule — power, voltage, temperature, SOC and so on. It is the raw material for every chart and report here. Devices push it; the platform never polls.',
      'zh-Hant':
        '設備依自己的節奏主動上報的量測值——功率、電壓、溫度、SOC 等等。這裡所有圖表與報表都是從它來的。是設備推送上來的，平台不會去輪詢。',
      'zh-Hans':
        '设备按自身周期主动上报的测量值——功率、电压、温度、SOC 等。本平台所有图表与报表均源于此。数据由设备主动推送，平台不进行轮询。',
    },
  },
  rollup: {
    label: {
      en: 'Rollup',
      'zh-Hant': '彙總資料',
      'zh-Hans': '汇总数据',
    },
    definition: {
      en: 'Pre-computed summaries — hourly and daily minimum, maximum, average and count — built from raw samples on a schedule. Long date ranges are drawn from these instead of millions of raw points, which is why a year-long chart loads as fast as a day.',
      'zh-Hant':
        '事先算好的摘要——每小時、每日的最小值、最大值、平均值與筆數，由原始樣本定期產生。長時間區間的圖用的是這些，而不是幾百萬筆原始資料，所以看一年跟看一天一樣快。',
      'zh-Hans':
        '预先计算的汇总数据——按小时和按天的最小值、最大值、平均值与样本数，由原始采样定期生成。长时间跨度的图表基于汇总数据绘制，而非数百万条原始记录，因此查看一年与查看一天速度相当。',
    },
  },
  ingestor: {
    label: {
      en: 'Ingestor',
      'zh-Hant': '接收服務（ingestor）',
      'zh-Hans': '接收服务（ingestor）',
    },
    definition: {
      en: 'The process that subscribes to MQTT, validates each payload and puts it on the queue. It deliberately never touches the database, so a slow or locked database cannot stop messages being consumed — the queue absorbs the burst instead of the broker dropping it.',
      'zh-Hant':
        '訂閱 MQTT、驗證每筆 payload、然後丟進佇列的那個行程。它刻意完全不碰資料庫，這樣資料庫變慢或被鎖住時，訊息消費也不會停——由佇列吸收突發流量，而不是讓 broker 把訊息丟掉。',
      'zh-Hans':
        '订阅 MQTT、校验每条报文并投入队列的进程。它刻意完全不访问数据库，这样即使数据库变慢或被锁定，消息消费也不会中断——由队列吸收突发流量，而不是让 broker 丢弃消息。',
    },
  },
  worker: {
    label: {
      en: 'Worker',
      'zh-Hant': '處理服務（worker）',
      'zh-Hans': '处理服务（worker）',
    },
    definition: {
      en: 'The process that takes messages off the queue and does the slow work: writing time series in batches, evaluating alert rules and sending notifications. Splitting it from the ingestor is what lets ingest keep up while storage catches up.',
      'zh-Hant':
        '從佇列取出訊息、做比較慢的那些事的行程：批次寫入時序資料、跑告警規則、發送通知。把它和 ingestor 分開，接收才能繼續跟上，讓寫入慢慢追。',
      'zh-Hans':
        '从队列取出消息并执行耗时操作的进程：批量写入时序数据、评估告警规则、发送通知。将其与 ingestor 分离，才能保证接收不被写入拖慢。',
    },
  },
  coverage: {
    label: {
      en: 'Coverage',
      'zh-Hant': '資料覆蓋率',
      'zh-Hans': '数据覆盖率',
    },
    unit: '%',
    definition: {
      en: 'How much of an interval actually had data behind it. Below 100 % the device was offline or silent for part of the period, so the totals for that interval are understated — the platform reports the gap instead of quietly filling it in.',
      'zh-Hant':
        '一個區間裡實際有資料的比例。低於 100 % 表示設備在那段時間離線或沒上報，該區間的總計就會偏低——平台會把缺口誠實標出來，而不是靜靜補一個數字進去。',
      'zh-Hans':
        '一个区间内实际有数据的比例。低于 100 % 说明设备在该时段离线或未上报，该区间的合计值会偏低——平台会如实标注缺口，而不是静默补值。',
    },
  },
  includeInBalance: {
    label: {
      en: 'Include in balance',
      'zh-Hant': '計入能量平衡',
      'zh-Hans': '计入能量平衡',
    },
    definition: {
      en: 'Whether this binding counts toward the site energy balance. Turn it off for sub-meters that measure something already covered by the main meter — leaving both on double-counts the load silently, and the totals will simply be wrong with no error shown.',
      'zh-Hant':
        '這筆綁定要不要計入案場的能量平衡。如果是量測「主電表已經包含的那一段」的分表，就要關掉——兩邊都開會靜靜地重複計算，總量直接錯掉，而且不會有任何錯誤訊息。',
      'zh-Hans':
        '该绑定是否计入站点能量平衡。若为计量「主表已覆盖部分」的分表，应关闭此项——两者同时开启会静默重复计算，导致合计值直接出错，且不会有任何报错提示。',
    },
  },
  deadband: {
    label: {
      en: 'Deadband',
      'zh-Hant': '死區',
      'zh-Hans': '死区',
    },
    definition: {
      en: 'A change threshold below which a new sample is not stored. It cuts storage volume for slow-moving signals, but only affects storage — the alert engine still sees every reading, so a deadband can never hide a fault.',
      'zh-Hant':
        '變化量小於這個門檻的樣本就不儲存。對變化緩慢的訊號可以大幅減少儲存量。它只影響「儲存」——告警引擎仍然看得到每一筆讀值，所以死區不會把故障藏起來。',
      'zh-Hans':
        '变化量小于该阈值的采样不予存储。对变化缓慢的信号可显著减少存储量。它只影响「存储」——告警引擎仍会读取每一条数据，因此死区不会掩盖故障。',
    },
  },
  blueprint: {
    label: {
      en: 'Blueprint',
      'zh-Hant': '設備型號範本',
      'zh-Hans': '设备型号模板',
    },
    definition: {
      en: 'The device type that defines what a model can do: its metrics, its command set and its default capabilities. Individual devices inherit from it, so fixing a definition once corrects every device of that model.',
      'zh-Hant':
        '定義某個型號「能做什麼」的設備類型：有哪些量測項、有哪些命令、預設能力是什麼。個別設備繼承它，所以改一次定義，同型號的所有設備都會跟著修正。',
      'zh-Hans':
        '定义某一型号「能做什么」的设备类型：包含哪些指标、支持哪些命令、默认能力如何。各设备继承该模板，因此修改一次定义即可修正该型号的所有设备。',
    },
  },

  // -------------------------------------------------------------------
  // MQTT
  // -------------------------------------------------------------------
  mqtt: {
    abbr: 'MQTT',
    expansion: 'Message Queuing Telemetry Transport',
    label: {
      en: 'MQTT',
      'zh-Hant': 'MQTT 通訊協定',
      'zh-Hans': 'MQTT 通信协议',
    },
    definition: {
      en: 'The lightweight publish-subscribe protocol devices use to talk to the platform. Devices connect out to a broker and publish to topics; nothing has to reach into the device, which is what makes it work behind a firewall or a mobile connection.',
      'zh-Hant':
        '設備與平台溝通用的輕量級發布／訂閱協定。設備主動向 broker 連出去、發布到 topic；不需要從外面連進設備，所以在防火牆後面或行動網路上都能用。',
      'zh-Hans':
        '设备与平台通信所用的轻量级发布／订阅协议。设备主动向 broker 建立外连并发布到主题；无需从外部反向连接设备，因此在防火墙后或移动网络下均可正常工作。',
    },
  },
  qos: {
    abbr: 'QoS',
    expansion: 'Quality of Service',
    label: {
      en: 'Quality of service',
      'zh-Hant': '服務品質等級',
      'zh-Hans': '服务质量等级',
    },
    definition: {
      en: 'The delivery guarantee on an MQTT message. QoS 0 is fire-and-forget and can silently lose data on a flaky link; QoS 1 keeps retrying until acknowledged. This platform requires QoS 1 both ways, because a dropped reading looks exactly like a reading that never happened.',
      'zh-Hant':
        'MQTT 訊息的送達保證等級。QoS 0 送出就不管，網路不穩時會靜靜掉資料；QoS 1 會一直重送直到對方確認。本平台上下行都要求 QoS 1，因為掉掉的資料和「本來就沒有」長得一模一樣。',
      'zh-Hans':
        'MQTT 消息的送达保证等级。QoS 0 为发送后不确认，网络不稳时会静默丢失数据；QoS 1 会持续重发直至收到确认。本平台上下行均要求 QoS 1，因为丢失的数据与「本就没有数据」表现完全相同。',
    },
  },
  lwt: {
    abbr: 'LWT',
    expansion: 'Last Will and Testament',
    label: {
      en: 'Last will',
      'zh-Hant': '遺言訊息',
      'zh-Hans': '遗嘱消息',
    },
    definition: {
      en: 'A message the device registers at connect time, which the broker publishes on its behalf if the connection drops without a proper goodbye. It is the only way a sudden power cut becomes visible — without it, a dead device just stops sending and looks idle.',
      'zh-Hant':
        '設備在連線當下就先登記好的一則訊息，之後若連線非正常中斷，由 broker 代它發出。這是突然斷電唯一會被看見的方式——沒有它，設備死掉只是「不再送資料」，看起來就像閒著。',
      'zh-Hans':
        '设备在建立连接时预先登记的一条消息，若连接非正常断开，由 broker 代为发布。这是突然断电唯一能被感知的途径——若无此机制，设备宕机只表现为「不再发送数据」，看上去与空闲无异。',
    },
  },
  retained: {
    label: {
      en: 'Retained message',
      'zh-Hant': '保留訊息',
      'zh-Hans': '保留消息',
    },
    definition: {
      en: 'A message the broker keeps as the current value of a topic and hands to anyone who subscribes later. Status messages are retained so a console opened after the device connected still sees its state instead of a blank until the next update.',
      'zh-Hant':
        'Broker 會把它記成該 topic 的「目前值」，之後才訂閱的人一連上就會收到。狀態訊息設為保留，是為了讓設備連上之後才打開的畫面也能看到目前狀態，而不是一片空白等下一次更新。',
      'zh-Hans':
        'Broker 会将其保存为该主题的「当前值」，后续订阅者一旦连接即可收到。状态消息设为保留，是为了让设备连接后才打开的界面也能看到当前状态，而不是空白等待下次更新。',
    },
  },
  uplink: {
    label: {
      en: 'Uplink',
      'zh-Hant': '上行',
      'zh-Hans': '上行',
    },
    definition: {
      en: 'Traffic from the device up to the platform: telemetry, status, events and alarms. Devices decide when to send it; the platform only listens.',
      'zh-Hant':
        '從設備往平台方向的流量：遙測、狀態、事件與告警。何時要送由設備決定，平台只負責接收。',
      'zh-Hans':
        '由设备发往平台方向的数据：遥测、状态、事件与告警。发送时机由设备决定，平台仅负责接收。',
    },
  },
  downlink: {
    label: {
      en: 'Downlink',
      'zh-Hant': '下行',
      'zh-Hans': '下行',
    },
    definition: {
      en: 'Traffic from the platform down to the device: control commands. Every command carries an id the device must echo back in its acknowledgement, which is how a command that was never acted on is told apart from one that succeeded.',
      'zh-Hant':
        '從平台往設備方向的流量：控制命令。每則命令都帶一個編號，設備回覆時必須原樣帶回——這才分得出來「沒執行」和「執行成功」的差別。',
      'zh-Hans':
        '由平台发往设备方向的数据：控制命令。每条命令都带有一个编号，设备应答时必须原样返回——这样才能区分「未执行」与「执行成功」。',
    },
  },

  // -------------------------------------------------------------------
  // Device lifecycle
  // -------------------------------------------------------------------
  lifecycle: {
    label: {
      en: 'Lifecycle state',
      'zh-Hant': '生命週期狀態',
      'zh-Hans': '生命周期状态',
    },
    definition: {
      en: 'Where the device sits between registration and retirement: pending, active, suspended, retired or rejected. It controls whether the device may connect and whether it may be commanded — separately, because a suspect device’s data is often exactly what you need to diagnose it.',
      'zh-Hant':
        '設備從註冊到退役之間的位置：待確認、運轉中、暫停、已退役、已拒絕。它決定設備能不能連線、能不能被下命令——這兩件事分開控制，因為可疑設備的資料往往正是診斷它所需要的。',
      'zh-Hans':
        '设备从注册到退役之间所处的阶段：待确认、运行中、暂停、已退役、已拒绝。它决定设备能否连接、能否被下发命令——两者分别控制，因为可疑设备的数据往往正是诊断所需。',
    },
  },
  lifecyclePending: {
    label: {
      en: 'Pending',
      'zh-Hant': '待確認',
      'zh-Hans': '待确认',
    },
    definition: {
      en: 'Registered but not yet confirmed by an operator. Telemetry is accepted on purpose — you need to see what the thing actually reports before deciding — but dispatch commands are refused until someone signs it off.',
      'zh-Hant':
        '已註冊但還沒有人確認過。遙測會照收，這是刻意的——要先看得到它實際報什麼，才有東西可以判斷；但在有人簽核之前，調度命令一律拒絕。',
      'zh-Hans':
        '已注册但尚未经运维人员确认。遥测数据照常接收，这是刻意设计的——需要先看到设备实际上报的内容才能判断；但在确认之前，调度命令一律拒绝。',
    },
  },
  lifecycleActive: {
    label: {
      en: 'Active',
      'zh-Hant': '運轉中',
      'zh-Hans': '运行中',
    },
    definition: {
      en: 'Confirmed and in normal service. It may connect, report and be commanded within its capabilities.',
      'zh-Hant': '已確認，正常運轉中。可以連線、上報，並在其能力範圍內接受命令。',
      'zh-Hans': '已确认，处于正常运行状态。可以连接、上报，并在其能力范围内接受命令。',
    },
  },
  lifecycleSuspended: {
    label: {
      en: 'Suspended',
      'zh-Hant': '暫停',
      'zh-Hans': '暂停',
    },
    definition: {
      en: 'Temporarily out of service — under maintenance, or behaving oddly. Commands are refused but data is still recorded, which is deliberate: silencing a suspect device removes the evidence you need to work out what is wrong with it.',
      'zh-Hant':
        '暫時停用——維修中，或行為異常。命令會被拒絕，但資料仍然照常記錄。這是刻意的：把可疑設備靜音，等於把診斷所需的證據一起丟掉。',
      'zh-Hans':
        '临时停用——处于维护中或行为异常。命令将被拒绝，但数据仍照常记录。这是刻意设计的：让可疑设备静默，等于丢弃诊断所需的证据。',
    },
  },
  lifecycleRetired: {
    label: {
      en: 'Retired',
      'zh-Hant': '已退役',
      'zh-Hans': '已退役',
    },
    definition: {
      en: 'Permanently out of service. It can no longer connect or be commanded, but it is not deleted — its history stays readable, because reports covering past periods still need it.',
      'zh-Hant':
        '永久停用。不能再連線，也不能下命令，但並沒有被刪除——歷史資料仍然查得到，因為涵蓋過去期間的報表還需要它。',
      'zh-Hans':
        '永久停用。无法再连接或接受命令，但并未被删除——历史数据仍可查询，因为涉及过往周期的报表仍需引用。',
    },
  },
  lifecycleRejected: {
    label: {
      en: 'Rejected',
      'zh-Hant': '已拒絕',
      'zh-Hans': '已拒绝',
    },
    definition: {
      en: 'A device that announced itself and was turned down — wrong hardware, not ours, or registered by mistake. It cannot connect. The record is kept so the same device announcing itself again is recognised rather than re-reviewed.',
      'zh-Hant':
        '設備自己上線宣告，但被拒絕了——硬體不對、不是我們的，或是註冊錯誤。它無法連線。紀錄會保留，這樣同一台再次宣告時能被認出來，不用重新審一次。',
      'zh-Hans':
        '设备自行上线声明但被拒绝——硬件不符、非本方设备，或注册有误。该设备无法连接。记录会保留，以便同一设备再次声明时能被识别，无需重新审核。',
    },
  },

  // -------------------------------------------------------------------
  // Capability flags
  // -------------------------------------------------------------------
  capabilities: {
    label: {
      en: 'Capabilities',
      'zh-Hant': '設備能力',
      'zh-Hans': '设备能力',
    },
    definition: {
      en: 'The four flags that decide which commands a device may be given. Only confirmed values count — what the device claims about itself is recorded separately and never enforces anything, because a compromised or misconfigured device must not be able to grant itself permissions.',
      'zh-Hant':
        '決定設備可以接受哪些命令的四個旗標。只有「已確認」的值算數——設備自己宣稱的內容另外記錄，永遠不會用來放行任何動作，因為被入侵或設定錯誤的設備不能自己給自己權限。',
      'zh-Hans':
        '决定设备可接受哪些命令的四个标志位。只有「已确认」的值生效——设备自身声明的内容单独记录，永远不用于放行任何操作，因为被入侵或配置错误的设备不能自行授予权限。',
    },
  },
  canCharge: {
    label: {
      en: 'Can charge',
      'zh-Hant': '可充電',
      'zh-Hans': '可充电',
    },
    definition: {
      en: 'The device can absorb energy. Without it, any command that would drive power into the unit is refused before it is sent — including a negative setpoint on a command that also allows discharging.',
      'zh-Hant':
        '設備可以吸收電能。沒有這個能力，任何會把功率灌進去的命令在送出前就會被擋掉——包括那種同時允許放電的命令裡帶負值的情況。',
      'zh-Hans':
        '设备可以吸收电能。若不具备该能力，任何会向设备注入功率的命令在下发前即被拒绝——包括在同时允许放电的命令中传入负设定值的情况。',
    },
  },
  canDischarge: {
    label: {
      en: 'Can discharge',
      'zh-Hant': '可放電',
      'zh-Hans': '可放电',
    },
    definition: {
      en: 'The device can deliver stored energy back out. Metering-only equipment never has this, which is what stops a meter from being handed a dispatch instruction it cannot act on.',
      'zh-Hant':
        '設備可以把儲存的電放出來。純量測設備不會有這個能力，這樣就不會有人對電表下一個它根本執行不了的調度指令。',
      'zh-Hans':
        '设备可以将储存的电量释放出来。纯计量设备不具备该能力，从而避免向电表下发其根本无法执行的调度指令。',
    },
  },
  canExport: {
    label: {
      en: 'Can export',
      'zh-Hant': '可躉售',
      'zh-Hans': '可上网',
    },
    definition: {
      en: 'The device is permitted to push power back onto the grid. This is a regulatory and interconnection limit as much as a hardware one — many sites are technically able to export but contractually not allowed to.',
      'zh-Hant':
        '設備獲准把電送回電網。這與其說是硬體限制，不如說是法規與併聯契約的限制——很多案場技術上做得到，合約上卻不允許。',
      'zh-Hans':
        '设备获准向电网反向送电。这与其说是硬件限制，不如说是法规与并网协议的限制——许多站点技术上可以上网，合同上却不允许。',
    },
  },
  isDispatchable: {
    label: {
      en: 'Dispatchable',
      'zh-Hant': '可調度',
      'zh-Hans': '可调度',
    },
    definition: {
      en: 'The platform may send this device operating setpoints at all. A device can be perfectly capable of charging and discharging yet not be dispatchable — for instance while it is under local or manual control.',
      'zh-Hant':
        '平台可不可以對這台設備下運轉設定值。一台設備可能完全有能力充放電，卻不可調度——例如它目前處於就地或手動控制模式。',
      'zh-Hans':
        '平台是否可以向该设备下发运行设定值。一台设备可能完全具备充放电能力却不可调度——例如当前处于就地或手动控制模式。',
    },
  },
  declaration: {
    label: {
      en: 'Device declaration',
      'zh-Hant': '設備自我宣告',
      'zh-Hans': '设备自我声明',
    },
    definition: {
      en: 'What the device reports about itself — its category, capabilities and firmware. It is untrusted input, kept separate from the confirmed configuration and informational only until an operator accepts it. A mismatch usually means the hardware was swapped without registering a replacement.',
      'zh-Hant':
        '設備自己回報的資訊——類別、能力、韌體版本。這是不可信輸入，與已確認的設定分開存放，在有人接受之前只供參考。宣告不符通常代表硬體被換過，但沒有登記替換。',
      'zh-Hans':
        '设备自行上报的信息——类别、能力、固件版本。这属于不可信输入，与已确认的配置分开存放，在运维人员接受之前仅供参考。声明不匹配通常意味着硬件被更换但未登记替换。',
    },
  },
} as const satisfies Record<string, GlossaryEntry>

export type GlossaryId = keyof typeof GLOSSARY

export interface ResolvedTerm {
  id: GlossaryId
  /** Display name in the active language. */
  label: string
  abbr?: string
  expansion?: string
  unit?: string
  definition: string
}

/**
 * Look up a term in one language, falling back to English.
 *
 * The fallback matters: a term added in a hurry with only English filled in
 * should still explain itself rather than render blank. TypeScript normally
 * prevents that, but the fallback also covers a language added later.
 */
export function resolveTerm(id: GlossaryId, language: SupportedLanguage): ResolvedTerm {
  const entry: GlossaryEntry = GLOSSARY[id]
  return {
    id,
    label: entry.label[language] || entry.label.en,
    abbr: entry.abbr,
    expansion: entry.expansion,
    unit: entry.unit,
    definition: entry.definition[language] || entry.definition.en,
  }
}

/**
 * The heading shown at the top of the bubble.
 *
 * For an abbreviation the English expansion is always shown next to the
 * localised name — the whole point of the request was that "SOC" alone is not
 * an explanation, and a reader who only ever sees 荷電狀態 will not recognise
 * the term in an English datasheet.
 */
export function termHeading(term: ResolvedTerm): string {
  if (!term.abbr) return term.unit ? `${term.label}（${term.unit}）` : term.label
  const parts = [term.abbr]
  if (term.expansion) parts.push(`· ${term.expansion}`)
  return parts.join(' ')
}
