from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cellforge import yamlio


def test_yaml_parser_is_serialized_across_server_threads(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "sample.yaml"
    yamlio.dump_yaml(source, {"modules": [{"id": "sample"}]})
    original_load = yamlio._yaml.load
    active_calls = 0
    state_lock = threading.Lock()

    def concurrency_guard(stream):
        nonlocal active_calls
        with state_lock:
            active_calls += 1
            if active_calls > 1:
                raise RuntimeError("YAML parser 被並行呼叫")
        try:
            time.sleep(0.01)
            return original_load(stream)
        finally:
            with state_lock:
                active_calls -= 1

    monkeypatch.setattr(yamlio._yaml, "load", concurrency_guard)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(yamlio.load_yaml, [source] * 8))

    assert all(result["modules"][0]["id"] == "sample" for result in results)
