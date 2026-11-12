"""Provenance run: versi kebijakan, model, dan input yang benar-benar dipakai.

Tanpa berkas ini dua run tidak bisa dibandingkan: perbaikan tidak bisa
diatribusikan ke patch prompt, ke perubahan kode, ke model yang berbeda, atau ke
keberuntungan sampling. Ditulis idempoten supaya bisa dipanggil dari jalur
normal (`_finalize`) maupun dari jalur gagal (`api._run_one`).
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

from .config import Settings
from .runtime import RunPaths, atomic_write_json, read_json, utc_now

SCHEMA = 1
#: Nama berkas di direktori run. Dipakai juga oleh `api._package` untuk
#: mengecualikannya dari paket unduhan klien.
PROVENANCE_FILE = "provenance.json"


def _git(*args: str) -> str:
    """Jalankan git dengan batas waktu; kosong bila git tidak tersedia."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _build() -> dict[str, Any]:
    """Identitas image dan commit. Di container `.git` tidak ada, jadi build
    arg yang menjadi sumber utama; git hanya pelengkap saat run dari host.

    ``git_dirty`` bernilai None bila commit tidak diketahui: "tidak bisa
    dibuktikan bersih" bukan "bersih".
    """
    git_sha = os.environ.get("SWARMFOLD_GIT_SHA", "") or _git("rev-parse", "HEAD")
    dirty = _git("status", "--porcelain") if git_sha else ""
    return {
        "image": os.environ.get("SWARMFOLD_IMAGE", ""),
        "build_sha": os.environ.get("SWARMFOLD_BUILD_SHA", ""),
        "git_sha": git_sha,
        "git_dirty": bool(dirty) if git_sha else None,
    }


def write_provenance(
    paths: RunPaths,
    settings: Settings,
    *,
    prompt_fingerprint: str = "",
    pack: str = "",
    prompt_files: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Tulis `<run>/provenance.json` dan kembalikan isinya."""
    status = read_json(paths.status_file, {})
    status = status if isinstance(status, dict) else {}
    data: dict[str, Any] = {
        "schema": SCHEMA,
        "run_id": paths.run_id,
        "created_at": utc_now(),
        "build": _build(),
        "prompts": {
            "fingerprint": prompt_fingerprint or str(status.get("prompt_fingerprint") or ""),
            "pack": pack or str(status.get("pack") or ""),
            "files": dict(prompt_files or {}),
        },
        "model": dict(status.get("model") or {}),
        "settings": settings.public_dict(),
        "inputs": list(status.get("inputs") or []),
        "dataset_hash": status.get("dataset_hash") or "",
        "env": dict(status.get("env") or {}),
    }
    atomic_write_json(paths.dir / PROVENANCE_FILE, data)
    return data
