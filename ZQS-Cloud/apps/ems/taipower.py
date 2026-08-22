"""Built-in Taipower (台灣電力公司) time-of-use tariff presets.

Why presets and not an API: Taipower publishes *posted* tariffs, revised by
the electricity price review committee roughly twice a year - there is no
public real-time price feed to integrate against. The honest architecture is
therefore a bundled rate table the operator applies and can edit, with the
tariff year stated on every preset so a stale table is visible, not silent.

The numbers below are the 114 (2025) residential/commercial posted rates.
They are reference values: progressive surcharges (>2000 kWh), the per-meter
basic fee, and power-factor adjustments are out of scope of the per-kWh
model, and the operator is told to check the current Taipower announcement
before billing anyone off these figures.

Period shape matches :mod:`apps.ems.tariffs`: first match wins, weekdays are
Monday=0..Sunday=6, months are calendar months, times are local (the presets
pin ``Asia/Taipei``).
"""

from __future__ import annotations

SUMMER = [6, 7, 8, 9]
NON_SUMMER = [1, 2, 3, 4, 5, 10, 11, 12]
WEEKDAYS = [0, 1, 2, 3, 4]
SATURDAY = [5]
WEEKEND = [5, 6]

#: The tariff year the bundled numbers came from, shown in the UI.
TARIFF_YEAR = "114 (2025)"

PRESETS: list[dict] = [
    {
        "key": "taipower-residential-2tier",
        "name": "台電 表燈簡易時間電價（二段式）",
        "description": (
            "住商用電二段式時間電價。夏月(6-9月)平日尖峰 09:00-24:00、"
            "非夏月平日尖峰 06:00-11:00 與 14:00-24:00，其餘離峰；"
            "週六日全日離峰。"
        ),
        "tariff": {
            "kind": "tou",
            "currency": "TWD",
            "timezone_name": "Asia/Taipei",
            "demand_charge_per_kw": 0.0,
            "default_import_price": 2.24,
            "default_export_price": 0.0,
            "periods": [
                {"name": "夏月尖峰", "months": SUMMER, "weekdays": WEEKDAYS,
                 "start": "09:00", "end": "24:00", "import_price": 5.54},
                {"name": "夏月離峰", "months": SUMMER,
                 "start": "00:00", "end": "24:00", "import_price": 2.32},
                {"name": "非夏月尖峰(早)", "months": NON_SUMMER, "weekdays": WEEKDAYS,
                 "start": "06:00", "end": "11:00", "import_price": 5.34},
                {"name": "非夏月尖峰(午後)", "months": NON_SUMMER, "weekdays": WEEKDAYS,
                 "start": "14:00", "end": "24:00", "import_price": 5.34},
                {"name": "非夏月離峰", "months": NON_SUMMER,
                 "start": "00:00", "end": "24:00", "import_price": 2.24},
            ],
        },
    },
    {
        "key": "taipower-residential-3tier",
        "name": "台電 表燈簡易時間電價（三段式）",
        "description": (
            "住商用電三段式時間電價。夏月平日尖峰 16:00-22:00、"
            "半尖峰 09:00-16:00 與 22:00-24:00；非夏月平日半尖峰 "
            "06:00-11:00 與 14:00-24:00；週六為半尖峰折價時段、週日離峰。"
        ),
        "tariff": {
            "kind": "tou",
            "currency": "TWD",
            "timezone_name": "Asia/Taipei",
            "demand_charge_per_kw": 0.0,
            "default_import_price": 1.89,
            "default_export_price": 0.0,
            "periods": [
                {"name": "夏月尖峰", "months": SUMMER, "weekdays": WEEKDAYS,
                 "start": "16:00", "end": "22:00", "import_price": 6.92},
                {"name": "夏月半尖峰(早)", "months": SUMMER, "weekdays": WEEKDAYS,
                 "start": "09:00", "end": "16:00", "import_price": 4.54},
                {"name": "夏月半尖峰(晚)", "months": SUMMER, "weekdays": WEEKDAYS,
                 "start": "22:00", "end": "24:00", "import_price": 4.54},
                {"name": "夏月週六半尖峰", "months": SUMMER, "weekdays": SATURDAY,
                 "start": "09:00", "end": "24:00", "import_price": 2.14},
                {"name": "夏月離峰", "months": SUMMER,
                 "start": "00:00", "end": "24:00", "import_price": 1.96},
                {"name": "非夏月半尖峰(早)", "months": NON_SUMMER, "weekdays": WEEKDAYS,
                 "start": "06:00", "end": "11:00", "import_price": 4.28},
                {"name": "非夏月半尖峰(午後)", "months": NON_SUMMER, "weekdays": WEEKDAYS,
                 "start": "14:00", "end": "24:00", "import_price": 4.28},
                {"name": "非夏月週六半尖峰(早)", "months": NON_SUMMER, "weekdays": SATURDAY,
                 "start": "06:00", "end": "11:00", "import_price": 2.07},
                {"name": "非夏月週六半尖峰(午後)", "months": NON_SUMMER, "weekdays": SATURDAY,
                 "start": "14:00", "end": "24:00", "import_price": 2.07},
                {"name": "非夏月離峰", "months": NON_SUMMER,
                 "start": "00:00", "end": "24:00", "import_price": 1.89},
            ],
        },
    },
    {
        "key": "taipower-lv-power-2tier",
        "name": "台電 低壓電力時間電價（二段式）",
        "description": (
            "生產性質低壓用電二段式。含基本電費(經常契約，此處以夏月費率 "
            "236.2 元/kW/月填入 demand charge，非夏月為 173.2，請自行調整)。"
        ),
        "tariff": {
            "kind": "tou",
            "currency": "TWD",
            "timezone_name": "Asia/Taipei",
            "demand_charge_per_kw": 236.2,
            "default_import_price": 2.36,
            "default_export_price": 0.0,
            "periods": [
                {"name": "夏月尖峰", "months": SUMMER, "weekdays": WEEKDAYS,
                 "start": "09:00", "end": "24:00", "import_price": 5.85},
                {"name": "夏月離峰", "months": SUMMER,
                 "start": "00:00", "end": "24:00", "import_price": 2.44},
                {"name": "非夏月尖峰(早)", "months": NON_SUMMER, "weekdays": WEEKDAYS,
                 "start": "06:00", "end": "11:00", "import_price": 5.63},
                {"name": "非夏月尖峰(午後)", "months": NON_SUMMER, "weekdays": WEEKDAYS,
                 "start": "14:00", "end": "24:00", "import_price": 5.63},
                {"name": "非夏月離峰", "months": NON_SUMMER,
                 "start": "00:00", "end": "24:00", "import_price": 2.36},
            ],
        },
    },
]


def presets() -> list[dict]:
    """The bundled presets, with the tariff year stamped on each."""
    return [
        {
            "key": preset["key"],
            "name": preset["name"],
            "description": preset["description"],
            "tariff_year": TARIFF_YEAR,
            "tariff": preset["tariff"],
        }
        for preset in PRESETS
    ]
