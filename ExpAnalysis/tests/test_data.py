"""資料層測試：匯入驗證、設限寫法、schema。"""

from __future__ import annotations

import io

import pandas as pd
import pytest

from expanalysis.data.importer import import_dataframe, template_csv

BASE = {
    "batch_id": "IN-9001", "run_date": "2025-03-01", "ingot_len_mm": 500,
    "zone_len_mm": 50, "speed_mm_hr": 2.0, "temp_c": 180, "n_passes": 8,
    "atmosphere": "Ar", "head_crop_frac": 0.03, "analysis_method": "GDMS",
    "c0_ppm": 5.0,
}


def _df(rows):
    return pd.DataFrame([{**BASE, **r} for r in rows])


def _points(n=6, **over):
    return [{"x_norm": 0.05 + i * 0.15, "element": "Cu", "value_ppm": 0.1 * (i + 1),
             "lod_ppm": 0.01, **over} for i in range(n)]


def test_valid_import_passes():
    rep = import_dataframe(_df(_points()), None)
    assert rep.ok, rep.errors
    assert rep.batches == 1 and rep.measurements == 6


def test_missing_required_column_is_rejected():
    df = _df(_points()).drop(columns=["element"])
    rep = import_dataframe(df, None)
    assert not rep.ok
    assert any("element" in e for e in rep.errors)


def test_zero_ingot_length_is_not_silently_defaulted():
    """0 是 falsy，用 `float(x or 500)` 會靜默換成預設值——這條擋住那個 bug。"""
    rep = import_dataframe(_df(_points(ingot_len_mm=0)), None)
    assert not rep.ok
    assert any("錠長" in e for e in rep.errors)


def test_missing_temperature_is_rejected():
    df = _df(_points())
    df["temp_c"] = None
    rep = import_dataframe(df, None)
    assert not rep.ok
    assert any("溫度" in e for e in rep.errors)


@pytest.mark.parametrize("bad_temp", [0, 25, 1500])
def test_out_of_range_temperature_is_rejected(bad_temp):
    rep = import_dataframe(_df(_points(temp_c=bad_temp)), None)
    assert not rep.ok
    assert any("溫度" in e for e in rep.errors)


def test_zone_longer_than_ingot_is_rejected():
    rep = import_dataframe(_df(_points(zone_len_mm=800)), None)
    assert not rep.ok
    assert any("熔區長度" in e for e in rep.errors)


def test_x_norm_out_of_range_is_rejected():
    rows = _points()
    rows[0]["x_norm"] = 1.4
    rep = import_dataframe(_df(rows), None)
    assert not rep.ok
    assert any("歸一化位置" in e for e in rep.errors)


def test_duplicate_point_is_rejected():
    rows = _points()
    rows[1]["x_norm"] = rows[0]["x_norm"]
    rep = import_dataframe(_df(rows), None)
    assert not rep.ok
    assert any("重複" in e for e in rep.errors)


def test_inconsistent_batch_params_are_rejected():
    rows = _points()
    rows[2]["speed_mm_hr"] = 9.9
    rep = import_dataframe(_df(rows), None)
    assert not rep.ok
    assert any("不一致" in e for e in rep.errors)


@pytest.mark.parametrize("cell,expect_censored", [
    ("<0.05", True), ("< 0.05", True), (0.005, True), (0.5, False),
])
def test_three_censoring_notations(cell, expect_censored):
    """三種設限寫法都要能辨識：字串小於號、censored 旗標、value <= lod。"""
    rows = _points()
    rows[0]["value_ppm"] = cell
    rows[0]["lod_ppm"] = 0.05
    rep = import_dataframe(_df(rows), None)
    assert rep.ok, rep.errors
    assert (rep.censored > 0) is expect_censored


def test_explicit_censored_flag_is_honoured():
    rows = _points()
    rows[0]["value_ppm"] = 0.9
    rows[0]["censored"] = 1
    rep = import_dataframe(_df(rows), None)
    assert rep.ok and rep.censored == 1


def test_right_censored_notation_is_rejected_not_silently_accepted():
    """`>100` 若被當成精確值 100，k_eff 會被低估——必須擋下並說明。"""
    rows = _points()
    rows[0]["value_ppm"] = ">100"
    rep = import_dataframe(_df(rows), None)
    assert not rep.ok
    assert any("右設限" in e for e in rep.errors)


def test_x_mm_is_converted_using_ingot_length():
    rows = [{"x_mm": 25 + i * 60, "element": "Cu", "value_ppm": 0.2,
             "lod_ppm": 0.01} for i in range(6)]
    rep = import_dataframe(_df(rows), None)
    assert rep.ok, rep.errors


def test_chinese_column_names_are_recognised():
    df = pd.DataFrame([{
        "批次": "IN-9002", "錠長": 500, "熔區長度": 50, "速率": 2.0,
        "溫度": 180, "純化次數": 8, "歸一化位置": 0.05 + i * 0.15,
        "元素": "Fe", "濃度": 0.3, "檢測極限": 0.01, "進料濃度": 4.0,
    } for i in range(6)])
    rep = import_dataframe(df, None)
    assert rep.ok, rep.errors
    assert rep.elements == ["Fe"]


def test_missing_c0_produces_warning_not_error():
    df = _df(_points()).drop(columns=["c0_ppm"])
    rep = import_dataframe(df, None)
    assert rep.ok
    assert any("進料濃度" in w for w in rep.warnings)


def test_too_few_points_warns():
    rep = import_dataframe(_df(_points(n=2)), None)
    assert rep.ok
    assert any("取樣點" in w for w in rep.warnings)


def test_template_csv_is_importable():
    """自己產的範本必須自己能匯入，否則客戶第一步就卡住。"""
    rep = import_dataframe(pd.read_csv(io.StringIO(template_csv())), None)
    assert rep.ok, rep.errors
