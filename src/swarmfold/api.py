"""FastAPI: unggah, antrean satu worker, progres, dan unduhan paket."""

from __future__ import annotations

import logging
import os
import queue
import shutil
import threading
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from . import __version__
from .config import Settings
from .ingest import ingest
from .loop import AgentLoop, Brief, build_client
from .runtime import (
    RunPaths,
    StatusStore,
    atomic_write_json,
    new_run_id,
    read_json,
    utc_now,
)

#: Batas keras per berkas unggahan.
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
#: Batas jumlah berkas per unggahan.
MAX_UPLOAD_FILES = 10
#: Ukuran potongan baca saat menyimpan unggahan.
_CHUNK_BYTES = 1024 * 1024

#: State yang berarti proses masih berjalan saat aplikasi berhenti.
_SWEEP_STATES = ("queued", "running", "verifying", "packaging")
_INTERRUPTED_SUMMARY = "run terputus: proses berhenti sebelum selesai"

#: Deliverable wajib sebelum paket boleh terbit (CONTRACTS.md §9).
_REQUIRED_DELIVERABLES = (("notebook", "analysis.ipynb"), ("report_md", "laporan.md"))

_log = logging.getLogger(__name__)


class JobRunner:
    """Satu worker FIFO: satu run aktif pada satu waktu."""

    def __init__(self, settings: Settings, client_factory: Callable[[Settings], Any] = build_client):
        self.settings = settings
        self.client_factory = client_factory
        self._queue: queue.Queue[tuple[RunPaths, Brief]] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._work, name="swarmfold-worker", daemon=True)
            self._thread.start()

    def submit(self, paths: RunPaths, brief: Brief) -> None:
        self.start()
        self._queue.put((paths, brief))

    def pending(self) -> int:
        return self._queue.qsize()

    def _work(self) -> None:
        while True:
            paths, brief = self._queue.get()
            try:
                self._run_one(paths, brief)
            finally:
                self._queue.task_done()

    def _run_one(self, paths: RunPaths, brief: Brief) -> None:
        status = StatusStore(paths)
        try:
            ingest(_uploaded(paths), paths)
            client = self.client_factory(self.settings)
            AgentLoop(paths, self.settings, client, brief).run()
        except Exception as exc:  # noqa: BLE001 - kegagalan harus tercatat, bukan hilang
            message = f"{type(exc).__name__}: {exc}"
            try:
                status.warn(message)
                status.update(state="failed")
            except Exception:  # noqa: BLE001
                pass
            read_json(paths.done_file, {})
            _write_failure(paths, message)


def _uploaded(paths: RunPaths) -> list[Path]:
    return sorted(path for path in paths.input_dir.iterdir() if path.is_file())


def _done_payload(summary: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "phases_completed": [],
        "phases_skipped": [],
        "deliverables": {},
        "verification": {"rerun": "skipped", "mismatches": []},
        "summary": summary,
        "finished_at": utc_now(),
    }


def _write_failure(paths: RunPaths, message: str) -> None:
    atomic_write_json(paths.done_file, _done_payload(message))


def sweep_interrupted(data_root: Path) -> list[str]:
    """Tandai run yang tertinggal agar `/paket` tidak 409 selamanya.

    Dipanggil sekali saat aplikasi dibuat, bukan per request. Run tanpa
    `status.json` atau dengan status rusak dilewati.
    """
    root = Path(data_root)
    swept: list[str] = []
    if not root.is_dir():
        return swept
    for status_file in sorted(root.glob("*/status.json")):
        status = read_json(status_file)
        if not isinstance(status, dict) or status.get("state") not in _SWEEP_STATES:
            continue
        paths = RunPaths(root, status_file.parent.name)
        try:
            atomic_write_json(paths.done_file, _done_payload(_INTERRUPTED_SUMMARY))
            StatusStore(paths).update(state="interrupted")
        except Exception:  # noqa: BLE001 - satu run rusak tidak boleh menggagalkan sweep
            _log.warning("sweep run %s gagal", paths.run_id)
            continue
        swept.append(paths.run_id)
    return swept


def _reserve_name(name: str, used: set[str]) -> str:
    """Nama unik di dalam `input/`: `name`, `name_2.csv`, `name_3.csv`, ..."""
    stem, suffix = os.path.splitext(name)
    candidate = name
    counter = 2
    while candidate.casefold() in used:
        candidate = f"{stem}_{counter}{suffix}"
        counter += 1
    used.add(candidate.casefold())
    return candidate


def _save_upload(upload: UploadFile, destination: Path) -> None:
    """Simpan unggahan potongan per 1 MB dengan batas keras per berkas."""
    total = 0
    try:
        with destination.open("wb") as handle:
            while chunk := upload.file.read(_CHUNK_BYTES):
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="berkas melebihi 200 MB")
                handle.write(chunk)
    except HTTPException:
        destination.unlink(missing_ok=True)
        raise


def _package(paths: RunPaths) -> Path:
    target = paths.dir / f"paket-{paths.run_id}.zip"
    target_resolved = target.resolve()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in sorted(paths.dir.rglob("*")):
            if item.is_symlink() or not item.is_file():
                continue
            if item.name.endswith(".tmp"):
                continue
            relative = item.relative_to(paths.dir)
            if relative.parts[0] == "input" or item.resolve() == target_resolved:
                continue
            archive.write(item, relative.as_posix())
    return target


def _missing_deliverables(paths: RunPaths, done: dict[str, Any]) -> list[str]:
    """Deliverable wajib yang belum ada di direktori run."""
    declared = done.get("deliverables")
    declared = declared if isinstance(declared, dict) else {}
    missing: list[str] = []
    for key, fallback in _REQUIRED_DELIVERABLES:
        name = str(declared.get(key) or fallback)
        if not (paths.dir / name).is_file():
            missing.append(name)
    return missing


def create_app(
    settings: Settings | None = None,
    runner: JobRunner | None = None,
) -> FastAPI:
    resolved = settings or Settings.from_env()
    app = FastAPI(title="agent-swarmfold", version=__version__)
    try:
        sweep_interrupted(resolved.data_root)
    except Exception:  # noqa: BLE001 - pemulihan bersifat best effort
        _log.warning("sweep_interrupted gagal saat create_app")
    jobs = runner or JobRunner(resolved)
    app.state.settings = resolved
    app.state.jobs = jobs

    @app.get("/health")
    def health() -> dict[str, object]:
        # Sengaja tidak menyentuh API model: health menjawab "proses hidup".
        return {
            "status": "ok",
            "version": __version__,
            "model_configured": bool(resolved.base_url and resolved.api_key),
            "queue": jobs.pending(),
        }

    @app.post("/api/runs", status_code=202)
    async def create_run(
        files: list[UploadFile] = File(...),
        business_type: str = Form(""),
        main_kpi: str = Form(""),
        period: str = Form(""),
        decision: str = Form(""),
    ) -> dict[str, Any]:
        if not files:
            raise HTTPException(status_code=400, detail="minimal satu berkas")
        if len(files) > MAX_UPLOAD_FILES:
            raise HTTPException(
                status_code=400,
                detail=f"maksimal {MAX_UPLOAD_FILES} berkas per unggahan",
            )
        run_id = new_run_id()
        paths = RunPaths(resolved.data_root, run_id).ensure()
        used: set[str] = set()
        stored: list[tuple[str, str]] = []
        try:
            for upload in files:
                original = Path(upload.filename or "data.csv").name
                name = _reserve_name(original, used)
                _save_upload(upload, paths.input_dir / name)
                stored.append((original, name))
        except Exception:  # noqa: BLE001 - unggahan gagal tidak meninggalkan run setengah jadi
            shutil.rmtree(paths.dir, ignore_errors=True)
            raise
        brief = Brief(
            business_type=business_type,
            main_kpi=main_kpi,
            period=period,
            decision=decision,
        )
        status = StatusStore(paths)
        status.create(model={"requested": resolved.model, "returned": ""})
        for original, name in stored:
            if original != name:
                status.warn(f"berkas '{original}' disimpan sebagai '{name}'")
        jobs.submit(paths, brief)
        return {"run_id": run_id, "state": "queued"}

    @app.get("/api/runs/{run_id}")
    def run_status(run_id: str) -> dict[str, Any]:
        paths = RunPaths(resolved.data_root, _safe_id(run_id))
        status = read_json(paths.status_file)
        if not isinstance(status, dict):
            raise HTTPException(status_code=404, detail="run tidak ada")
        index = read_json(paths.cells_dir / "index.json", {"cells": []})
        return {"status": status, "cells": index.get("cells", [])}

    @app.get("/api/runs/{run_id}/paket")
    def download(run_id: str) -> FileResponse:
        paths = RunPaths(resolved.data_root, _safe_id(run_id))
        if not paths.dir.exists():
            raise HTTPException(status_code=404, detail="run tidak ada")
        done = read_json(paths.done_file)
        if done is None:
            raise HTTPException(status_code=409, detail="run belum selesai")
        if str(done.get("status")) != "failed":
            missing = _missing_deliverables(paths, done)
            if missing:
                raise HTTPException(
                    status_code=409,
                    detail="deliverable wajib belum ada: " + ", ".join(missing),
                )
        package = _package(paths)
        return FileResponse(package, filename=package.name, media_type="application/zip")

    return app


def _safe_id(run_id: str) -> str:
    if not run_id or any(ch in run_id for ch in "/\\.."):
        raise HTTPException(status_code=400, detail="run_id tidak sah")
    return run_id


app = create_app()
