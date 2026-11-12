"""Tata letak run, penulisan atomik, dan status.json.

Semua berkas ditulis atomik (`.tmp` lalu `os.replace`) sesuai CONTRACTS.md.
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Urutan maju. `failed` dan `interrupted` boleh dari state mana pun.
_STATE_ORDER = ("queued", "running", "verifying", "packaging", "done")
_TERMINAL_ANY = ("failed", "interrupted")


class StatusError(RuntimeError):
    """Transisi status yang tidak sah."""


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_run_id() -> str:
    return f"{datetime.now(UTC):%Y-%m-%d}-{secrets.token_hex(3)}"


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
        return default


@dataclass(frozen=True)
class RunPaths:
    root: Path
    run_id: str

    @property
    def dir(self) -> Path:
        return self.root / self.run_id

    @property
    def input_dir(self) -> Path:
        return self.dir / "input"

    @property
    def data_dir(self) -> Path:
        return self.dir / "data"

    @property
    def derived_dir(self) -> Path:
        return self.dir / "derived"

    @property
    def cells_dir(self) -> Path:
        return self.dir / "cells"

    @property
    def charts_dir(self) -> Path:
        return self.dir / "charts"

    @property
    def evidence_dir(self) -> Path:
        return self.dir / "evidence"

    @property
    def deepdive_dir(self) -> Path:
        return self.evidence_dir / "deepdive"

    @property
    def notes_dir(self) -> Path:
        return self.dir / "notes"

    @property
    def profile_file(self) -> Path:
        return self.dir / "profile.json"

    @property
    def status_file(self) -> Path:
        return self.dir / "status.json"

    @property
    def done_file(self) -> Path:
        return self.dir / "done.json"

    @property
    def notebook_file(self) -> Path:
        return self.dir / "analysis.ipynb"

    @property
    def report_file(self) -> Path:
        return self.dir / "laporan.md"

    @property
    def report_template_file(self) -> Path:
        """Laporan sebelum slot dirender; disimpan supaya bisa diaudit."""
        return self.dir / "laporan.template.md"

    @property
    def report_docx_file(self) -> Path:
        """Salinan Word dari laporan yang sudah dirender."""
        return self.dir / "laporan.docx"

    @property
    def clean_data_file(self) -> Path:
        return self.derived_dir / "01_clean.csv"

    def child(self, name: str) -> RunPaths:
        """Sub-run untuk satu kelompok data: ``<run>/datasets/<name>``.

        Tata letaknya sama persis dengan run biasa, sehingga prompt, validator,
        dan packager tidak perlu tahu apakah ia bekerja di run akar atau unit.
        """
        return RunPaths(self.dir / "datasets", name)

    def ensure(self) -> RunPaths:
        for directory in (
            self.dir,
            self.input_dir,
            self.data_dir,
            self.derived_dir,
            self.cells_dir,
            self.charts_dir,
            self.evidence_dir,
            self.deepdive_dir,
            self.notes_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        return self

    def relative(self, path: Path) -> str:
        # Kedua sisi di-resolve: `dir` bisa relatif ("./runs/<id>") sementara
        # pemanggil membawa path absolut. Tanpa ini relative_to gagal, fungsi
        # mengembalikan path absolut, dan write_file menolak karena direktori
        # pertamanya menjadi "C:" alih-alih "evidence".
        target = Path(path).resolve()
        try:
            return target.relative_to(self.dir.resolve()).as_posix()
        except ValueError:
            return target.as_posix()


class StatusStore:
    """Membaca dan memperbarui status.json dengan transisi yang dijaga."""

    def __init__(self, paths: RunPaths):
        self.paths = paths

    def create(
        self,
        *,
        inputs: list[dict[str, Any]] | None = None,
        env: dict[str, str] | None = None,
        model: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        data = {
            "run_id": self.paths.run_id,
            "state": "queued",
            "phase": None,
            "cell": 0,
            "started_at": now,
            "updated_at": now,
            "inputs": inputs or [],
            "env": env or {},
            "model": model or {},
            "usage": {"tokens_in": 0, "tokens_out": 0, "cost_estimate": 0.0},
            "counts": {"cells": 0, "evidence": 0, "charts": 0},
            "warnings": [],
        }
        atomic_write_json(self.paths.status_file, data)
        return data

    def read(self) -> dict[str, Any]:
        data = read_json(self.paths.status_file)
        if not isinstance(data, dict):
            raise StatusError(f"status.json tidak ada atau rusak: {self.paths.status_file}")
        return data

    def update(self, **fields: Any) -> dict[str, Any]:
        data = self.read()
        new_state = fields.get("state")
        if new_state is not None:
            self._check_state(str(data.get("state")), str(new_state))
        data.update(fields)
        data["updated_at"] = utc_now()
        atomic_write_json(self.paths.status_file, data)
        return data

    def warn(self, message: str) -> dict[str, Any]:
        data = self.read()
        warnings = list(data.get("warnings") or [])
        if message not in warnings:
            warnings.append(message)
        return self.update(warnings=warnings)

    def bump_usage(self, tokens_in: int, tokens_out: int) -> dict[str, Any]:
        data = self.read()
        usage = dict(data.get("usage") or {})
        usage["tokens_in"] = int(usage.get("tokens_in", 0)) + int(tokens_in)
        usage["tokens_out"] = int(usage.get("tokens_out", 0)) + int(tokens_out)
        return self.update(usage=usage)

    @staticmethod
    def _check_state(current: str, target: str) -> None:
        if target in _TERMINAL_ANY:
            return
        if current in _TERMINAL_ANY:
            raise StatusError(f"status {current} sudah terminal, tidak bisa menjadi {target}")
        if target not in _STATE_ORDER:
            raise StatusError(f"state tidak dikenal: {target}")
        if _STATE_ORDER.index(target) < _STATE_ORDER.index(current):
            raise StatusError(f"status tidak boleh mundur: {current} -> {target}")
