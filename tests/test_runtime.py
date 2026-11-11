from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from swarmfold import runtime
from swarmfold.runtime import (
    RunPaths,
    StatusError,
    StatusStore,
    atomic_write_json,
    read_json,
)

_STATE_ORDER = ("queued", "running", "verifying", "packaging")


def _paths(tmp_path: Path) -> RunPaths:
    return RunPaths(tmp_path / "runs", "2026-01-01-test").ensure()


def test_atomic_writes_use_unique_tmp_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "status.json"
    seen: list[str] = []
    lock = threading.Lock()

    def recording_replace(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
        with lock:
            seen.append(Path(source).name)

    monkeypatch.setattr(runtime.os, "replace", recording_replace)
    barrier = threading.Barrier(4)
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            barrier.wait(timeout=5)
            atomic_write_json(target, {"n": index})
        except BaseException as exc:  # noqa: BLE001 - dikumpulkan untuk asersi
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(seen) == 4
    assert len(set(seen)) == 4
    assert all(name.endswith(".tmp") for name in seen)


def test_atomic_write_leaves_no_tmp_file(tmp_path: Path) -> None:
    target = tmp_path / "status.json"
    atomic_write_json(target, {"a": 1})
    atomic_write_json(target, {"a": 2})
    assert read_json(target) == {"a": 2}
    assert list(tmp_path.glob("*.tmp")) == []


def test_read_json_returns_default_on_corrupt_or_missing_file(tmp_path: Path) -> None:
    corrupt = tmp_path / "status.json"
    corrupt.write_text("{bukan json", encoding="utf-8")
    assert read_json(corrupt, {"cadangan": True}) == {"cadangan": True}
    assert read_json(tmp_path / "hilang.json", "default") == "default"


def test_status_store_rejects_backward_transition(tmp_path: Path) -> None:
    store = StatusStore(_paths(tmp_path))
    store.create()
    store.update(state="running")
    with pytest.raises(StatusError):
        store.update(state="queued")


@pytest.mark.parametrize("current", _STATE_ORDER)
def test_status_store_accepts_failed_from_any_state(tmp_path: Path, current: str) -> None:
    paths = _paths(tmp_path)
    store = StatusStore(paths)
    store.create()
    for state in _STATE_ORDER[1 : _STATE_ORDER.index(current) + 1]:
        store.update(state=state)
    store.update(state="failed")
    assert read_json(paths.status_file)["state"] == "failed"
