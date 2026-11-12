"""Tes pin verifier.

Pin harus membuktikan dua hal sekaligus: snapshot tidak berubah sejak dibekukan,
dan skor yang dipakai gate benar-benar dihitung dari snapshot itu — bukan dari
`src/` yang boleh disentuh patch.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from swarmfold_verify import pins
from swarmfold_verify.truth import Anchor, Case, write

SRC = Path(__file__).resolve().parents[1] / "src" / "swarmfold_verify"
STORE = Path(__file__).resolve().parents[1] / "evals" / "pins"


def test_committed_pin_matches_source() -> None:
    """Mengubah verifier tanpa mem-pin ulang harus gagal di sini, bukan di gate."""
    lock = pins.read_lock(STORE / pins.LOCK_NAME)

    assert pins.verify(SRC, lock) == []
    assert pins.verify(pins.snapshot_dir(STORE, lock), lock) == []


def _lock(tmp_path: Path) -> dict:
    return pins.pin(SRC, tmp_path / "pins")


def test_compute_lists_every_module() -> None:
    lock = pins.compute(SRC)
    assert {"scorer.py", "checks.py", "cli.py"} <= set(lock["files"])
    assert lock["digest"].startswith("sha256:")


def test_pin_writes_snapshot_and_lock(tmp_path: Path) -> None:
    lock = _lock(tmp_path)
    assert (tmp_path / "pins" / pins.LOCK_NAME).is_file()
    assert pins.verify(pins.snapshot_dir(tmp_path / "pins", lock), lock) == []


def test_pins_detect_tamper(tmp_path: Path) -> None:
    lock = _lock(tmp_path)
    folder = pins.snapshot_dir(tmp_path / "pins", lock)
    target = folder / "scorer.py"
    target.write_text(target.read_text(encoding="utf-8") + "\n# suntikan\n", encoding="utf-8")

    assert pins.verify(folder, lock) == ["berubah: scorer.py"]


def test_verify_flags_unpinned_file(tmp_path: Path) -> None:
    lock = _lock(tmp_path)
    folder = pins.snapshot_dir(tmp_path / "pins", lock)
    (folder / "baru.py").write_text("x = 1\n", encoding="utf-8")
    (folder / "sub").mkdir()
    (folder / "sub" / "dalam.py").write_text("y = 2\n", encoding="utf-8")

    assert pins.verify(folder, lock) == ["tak terpin: baru.py", "tak terpin: sub/dalam.py"]


def test_verify_flags_missing_file(tmp_path: Path) -> None:
    lock = _lock(tmp_path)
    folder = pins.snapshot_dir(tmp_path / "pins", lock)
    (folder / "cases.py").unlink()

    assert pins.verify(folder, lock) == ["hilang: cases.py"]


def test_materialize_copies_snapshot(tmp_path: Path) -> None:
    lock = _lock(tmp_path)
    dest = pins.materialize(tmp_path / "pins", lock, tmp_path / "jalankan")

    assert (dest / "swarmfold_verify" / "scorer.py").is_file()
    assert pins.verify(dest / "swarmfold_verify", lock) == []


def test_materialize_refuses_missing_snapshot(tmp_path: Path) -> None:
    lock = _lock(tmp_path)
    hilang = {**lock, "digest": "sha256:000000000000"}
    with pytest.raises(pins.PinError):
        pins.materialize(tmp_path / "pins", hilang, tmp_path / "x")


def _run(tmp_path: Path) -> tuple[Path, Path]:
    run = tmp_path / "run"
    (run / "evidence").mkdir(parents=True)
    (run / "cells").mkdir()
    finding = {
        "id": "E-001",
        "statement": "turun 8%",
        "value": 0.08,
        "unit": "ratio",
        "cell": 1,
        "artifact": "cells/1.txt",
        "dataset_hash": "h",
        "verified": True,
        "confidence": "high",
        "display": "8,00%",
    }
    (run / "evidence" / "F2.json").write_text(
        json.dumps({"phase": "F2", "findings": [finding]}), encoding="utf-8"
    )
    (run / "cells" / "1.txt").write_text("8,00%", encoding="utf-8")
    (run / "laporan.md").write_text("# Laporan\n", encoding="utf-8")
    (run / "done.json").write_text(json.dumps({"phases_completed": ["F2"]}), encoding="utf-8")
    root = tmp_path / "evals"
    truth = Case("uji-01", "tune", 1, (Anchor("A1", "trend", 0.08, "ratio", 0.02),))
    write(truth, root / "truth" / "uji-01.json")
    return run, root


def _score_via(pin_root: Path, run: Path, root: Path) -> dict:
    env = {**os.environ, "PYTHONPATH": str(pin_root)}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "swarmfold_verify.cli",
            "score",
            "--run",
            str(run),
            "--case",
            "uji-01",
            "--root",
            str(root),
        ],
        cwd=pin_root,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_pinned_copy_is_imported_first(tmp_path: Path) -> None:
    """Bukti bahwa proses scoring benar-benar memuat modul dari pin."""
    lock = _lock(tmp_path)
    pin_root = pins.materialize(tmp_path / "pins", lock, tmp_path / "pinroot")
    env = {**os.environ, "PYTHONPATH": str(pin_root)}

    hasil = subprocess.run(
        [sys.executable, "-c", "import swarmfold_verify; print(swarmfold_verify.__file__)"],
        cwd=pin_root,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )

    assert hasil.returncode == 0, hasil.stderr
    assert Path(hasil.stdout.strip()).resolve().is_relative_to(pin_root.resolve())


def test_score_uses_pinned_copy(tmp_path: Path) -> None:
    """Mengubah salinan hidup tidak mengubah skor yang dihitung dari pin."""
    hidup = tmp_path / "hidup" / "swarmfold_verify"
    shutil.copytree(SRC, hidup)
    lock = pins.pin(hidup, tmp_path / "pins")
    pin_root = pins.materialize(tmp_path / "pins", lock, tmp_path / "pinroot")
    run, root = _run(tmp_path)

    asli = _score_via(pin_root, run, root)
    assert asli["recall"] == 1.0

    (hidup / "scorer.py").write_text(
        "def score(run_dir, case):\n    return {'recall': 0.0}\n", encoding="utf-8"
    )

    assert _score_via(pin_root, run, root) == asli
