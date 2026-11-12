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


def test_atomic_write_retries_replace_when_target_is_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Docker Desktop Windows mengembalikan PermissionError dari os.replace selama
    # berkas tujuan dibuka proses host (pemantau, editor). Satu pembaca tidak boleh
    # mematikan run: run 2026-11-12-0c2282 berhenti di F1 karena ini.
    target = tmp_path / "status.json"
    atomic_write_json(target, {"a": 1})

    real_replace = os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError(13, "Permission denied")
        return real_replace(src, dst)

    monkeypatch.setattr(runtime.os, "replace", flaky_replace)
    atomic_write_json(target, {"a": 2})

    assert calls["n"] == 3
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


def test_relative_works_when_root_is_relative(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    paths = runtime.RunPaths(root=Path("runs"), run_id="2026-01-01-rel").ensure()
    target = paths.dir / "evidence" / "F1.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{}", encoding="utf-8")

    assert paths.relative(target.resolve()) == "evidence/F1.json"
