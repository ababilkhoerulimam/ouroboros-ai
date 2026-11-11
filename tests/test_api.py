from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from swarmfold import api
from swarmfold.api import create_app
from swarmfold.config import Settings
from swarmfold.loop import Brief
from swarmfold.runtime import RunPaths, StatusStore, read_json


class FakeRunner:
    def __init__(self) -> None:
        self.submitted: list[tuple[RunPaths, Brief]] = []

    def submit(self, paths: RunPaths, brief: Brief) -> None:
        self.submitted.append((paths, brief))

    def pending(self) -> int:
        return len(self.submitted)


def _client(tmp_path: Path) -> tuple[TestClient, FakeRunner, Settings]:
    settings = Settings(
        api_key=None,
        base_url=None,
        model="test/model",
        max_cells=10,
        cell_timeout_s=30,
        stall_cells=3,
        deepdive_every=10,
        data_root=tmp_path / "runs",
    )
    runner = FakeRunner()
    return TestClient(create_app(settings, runner)), runner, settings


def test_health_without_model_credentials(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["model_configured"] is False


def test_upload_creates_run_and_enqueues(tmp_path: Path) -> None:
    client, runner, settings = _client(tmp_path)
    response = client.post(
        "/api/runs",
        files={"files": ("penjualan.csv", b"tanggal,total\n2025-01-01,1000\n", "text/csv")},
        data={"business_type": "toko", "main_kpi": "omzet", "period": "2025", "decision": "harga"},
    )
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    assert (settings.data_root / run_id / "input" / "penjualan.csv").exists()
    assert len(runner.submitted) == 1
    assert runner.submitted[0][1].business_type == "toko"


def test_unknown_run_is_404(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)
    assert client.get("/api/runs/tidak-ada").status_code == 404


def test_package_before_finish_is_409(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)
    response = client.post(
        "/api/runs",
        files={"files": ("a.csv", b"a,b\n1,2\n", "text/csv")},
    )
    run_id = response.json()["run_id"]
    assert client.get(f"/api/runs/{run_id}/paket").status_code == 409


def test_package_excludes_input(tmp_path: Path) -> None:
    client, _, settings = _client(tmp_path)
    response = client.post("/api/runs", files={"files": ("a.csv", b"a,b\n1,2\n", "text/csv")})
    run_id = response.json()["run_id"]
    run_dir = settings.data_root / run_id
    (run_dir / "done.json").write_text('{"status": "ok"}', encoding="utf-8")
    package = client.get(f"/api/runs/{run_id}/paket")
    assert package.status_code == 200

    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        names = archive.namelist()
    assert "input/a.csv" not in names
    assert "done.json" in names


def test_upload_over_size_cap_is_413(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, runner, settings = _client(tmp_path)
    monkeypatch.setattr(api, "MAX_UPLOAD_BYTES", 1024)
    response = client.post(
        "/api/runs",
        files={"files": ("besar.csv", b"x" * 4096, "text/csv")},
    )
    assert response.status_code == 413
    assert response.json()["detail"] == "berkas melebihi 200 MB"
    assert runner.submitted == []
    assert not list(settings.data_root.glob("*/input/*"))


def test_upload_over_file_count_cap_is_400(tmp_path: Path) -> None:
    client, runner, _ = _client(tmp_path)
    files = [("files", (f"f{index}.csv", b"a\n1\n", "text/csv")) for index in range(11)]
    response = client.post("/api/runs", files=files)
    assert response.status_code == 400
    assert runner.submitted == []


def test_duplicate_upload_names_are_reserved(tmp_path: Path) -> None:
    client, _, settings = _client(tmp_path)
    response = client.post(
        "/api/runs",
        files=[
            ("files", ("data.csv", b"a,b\n1,2\n", "text/csv")),
            ("files", ("data.csv", b"a,b\n3,4\n", "text/csv")),
        ],
    )
    assert response.status_code == 202
    run_dir = settings.data_root / response.json()["run_id"]
    first = (run_dir / "input" / "data.csv").read_bytes()
    second = (run_dir / "input" / "data_2.csv").read_bytes()
    assert first != second
    assert b"3,4" in second
    warnings = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))["warnings"]
    assert any("data_2.csv" in warning for warning in warnings)


def test_package_skips_symlinks_and_tmp_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, settings = _client(tmp_path)
    response = client.post("/api/runs", files={"files": ("a.csv", b"a,b\n1,2\n", "text/csv")})
    run_id = response.json()["run_id"]
    run_dir = settings.data_root / run_id
    (run_dir / "done.json").write_text('{"status": "ok"}', encoding="utf-8")
    (run_dir / "catatan.tmp").write_text("sisa", encoding="utf-8")
    outside = tmp_path / "rahasia.txt"
    outside.write_text("jangan ikut", encoding="utf-8")
    tautan = run_dir / "tautan.txt"
    try:
        os.symlink(outside, tautan)
    except OSError:
        # Windows tanpa Developer Mode: tandai berkas biasa sebagai symlink.
        tautan.write_text("palsu", encoding="utf-8")
        real_is_symlink = Path.is_symlink
        monkeypatch.setattr(
            Path, "is_symlink", lambda self: self == tautan or real_is_symlink(self)
        )

    package = client.get(f"/api/runs/{run_id}/paket")
    assert package.status_code == 200
    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        names = archive.namelist()
    assert "tautan.txt" not in names
    assert "catatan.tmp" not in names
    assert "done.json" in names


def test_corrupt_status_is_404(tmp_path: Path) -> None:
    client, _, settings = _client(tmp_path)
    run_dir = settings.data_root / "rusak"
    run_dir.mkdir(parents=True)
    (run_dir / "status.json").write_text("{bukan json", encoding="utf-8")
    assert client.get("/api/runs/rusak").status_code == 404


def test_sweep_interrupted_frees_package(tmp_path: Path) -> None:
    client, _, settings = _client(tmp_path)
    stale = RunPaths(settings.data_root, "2026-01-01-stale").ensure()
    StatusStore(stale).create()
    StatusStore(stale).update(state="running")
    finished = RunPaths(settings.data_root, "2026-01-01-done").ensure()
    StatusStore(finished).create()
    StatusStore(finished).update(state="done")

    swept = api.sweep_interrupted(settings.data_root)

    assert swept == ["2026-01-01-stale"]
    assert read_json(stale.status_file)["state"] == "interrupted"
    done = read_json(stale.done_file)
    assert done["status"] == "failed"
    assert done["summary"] == "run terputus: proses berhenti sebelum selesai"
    assert read_json(finished.status_file)["state"] == "done"
    assert client.get("/api/runs/2026-01-01-stale/paket").status_code == 200
