"""檢測模組介面、配方檢查與擴充機制"""
import pytest

from xrayvision.core import plugin
from xrayvision.core.pipeline import Recipe, RecipeError, analyze_image


def test_builtin_module_registered():
    mods = plugin.available()
    assert "bump_alignment" in mods
    d = mods["bump_alignment"].describe()
    assert d["names"]["zh-TW"] and d["names"]["en"]
    assert all(p["label"].get("zh-TW") and p["label"].get("en") for p in d["params"])


def test_resolve_params_defaults_and_validation():
    cls = plugin.get("bump_alignment")
    p = cls.resolve_params({"bump_level": 0.8, "min_array_size": 10})
    assert p["bump_level"] == 0.8 and p["min_array_size"] == 10 and p["pad_level"] == 0.25
    with pytest.raises(plugin.ParamError) as e:
        cls.resolve_params({"bump_levle": 0.8})
    assert e.value.code == "unknown_param"
    with pytest.raises(plugin.ParamError) as e:
        cls.resolve_params({"bump_level": 1.5})
    assert e.value.code == "above_max"
    with pytest.raises(plugin.ParamError) as e:
        cls.resolve_params({"lobe_mode": "maybe"})
    assert e.value.code == "not_in_choices"


def test_recipe_validation_errors():
    with pytest.raises(RecipeError) as e:
        Recipe.from_dict({"recipe_id": "x", "version": 1, "modules": [{"module_id": "nope"}]})
    assert e.value.code == "unknown_module"
    with pytest.raises(RecipeError) as e:
        Recipe.from_dict({"recipe_id": "x", "version": 1,
                          "modules": [{"module_id": "bump_alignment", "params": {"pad_level": -1}}]})
    assert e.value.code == "invalid_param"
    with pytest.raises(RecipeError):
        Recipe.from_dict({"version": 1, "modules": []})


class _MeanIntensity(plugin.InspectionModule):
    """測試用擴充模組：回報影像平均吸收量，驗證新模組不需修改平台即可掛載執行"""
    module_id = "test_mean"
    version = "0.1.0"
    names = {"zh-TW": "測試", "en": "Test"}
    supported_kinds = ("raw16",)
    params = (plugin.Param("scale", "float", 1.0, {"zh-TW": "倍率", "en": "Scale"}, min=0.0),)

    def run(self, ctx, params):
        m = float(ctx.prepared.absorption.mean()) * params["scale"]
        return plugin.ModuleResult(self.module_id, self.version, plugin.STATUS_OK, params, summary={"mean": m},
                                   findings=[plugin.Finding(1, "dot", {"c": {"type": "circle", "x": 5, "y": 5, "r": 3}})])


class _Broken(plugin.InspectionModule):
    module_id = "test_broken"
    version = "0.1.0"
    names = {"zh-TW": "錯誤", "en": "Broken"}
    supported_kinds = ("raw16",)

    def run(self, ctx, params):
        raise RuntimeError("boom")


def test_extension_module_runs_and_errors_are_isolated(synth):
    plugin.register(_MeanIntensity)
    plugin.register(_Broken)
    try:
        path = synth(size=(300, 300))
        r = Recipe.from_dict({"recipe_id": "ext", "version": 1, "modules": [
            {"module_id": "test_broken"}, {"module_id": "test_mean", "params": {"scale": 2.0}}]})
        res, _ = analyze_image(path, r)
        broken, mean = res.modules
        assert broken.status == plugin.STATUS_ERROR and broken.reasons == ["module_exception"]
        assert mean.status == plugin.STATUS_OK and mean.summary["mean"] > 0
        assert res.image["kind"] == "raw16" and len(res.image["sha256"]) == 64
        assert not res.reference_only
    finally:
        plugin._REGISTRY.pop("test_mean", None)
        plugin._REGISTRY.pop("test_broken", None)
