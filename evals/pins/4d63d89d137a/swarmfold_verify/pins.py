"""Pin verifier: skor dihitung dari salinan yang tidak bisa diubah patch.

Loop evolusi boleh mengubah prompt dan kode pipeline; ia tidak boleh mengubah
alat ukurnya. Pin ini yang menegakkan batas itu: berkas `swarmfold_verify`
disalin ke `evals/pins/<digest>/`, dan penilaian dijalankan dari salinan itu
dengan `PYTHONPATH` menunjuk ke sana — bukan dari `src/`.

`verify` membandingkan isi sebuah folder dengan lock. Dipakai dua kali dengan
arti berbeda: pada folder pin (apakah snapshot masih utuh) dan pada `src/`
(apakah kode yang diukur memang kode yang terpin).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

SCHEMA = 1
PACKAGE = "swarmfold_verify"
LOCK_NAME = "verify.lock.json"


class PinError(RuntimeError):
    """Pin tidak bisa dibuat atau isinya tidak lagi cocok dengan lock."""


def _hashes(folder: Path) -> dict[str, str]:
    """Hash seluruh isi paket, bukan hanya `*.py` di level atas.

    Subpaket dan berkas data ikut dihitung: berkas yang tidak di-hash adalah
    berkas yang bisa ditukar tanpa terdeteksi.
    """
    root = Path(folder)
    hasil: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        # Akhiran baris dinormalkan: checkout Windows (CRLF) dan Linux (LF)
        # harus menghasilkan digest yang sama, dan CRLF bukan perubahan isi.
        data = path.read_bytes().replace(b"\r\n", b"\n")
        hasil[path.relative_to(root).as_posix()] = "sha256:" + hashlib.sha256(data).hexdigest()
    return hasil


def _digest(files: dict[str, str]) -> str:
    bahan = "".join(f"{name}={sha}\n" for name, sha in sorted(files.items()))
    return "sha256:" + hashlib.sha256(bahan.encode()).hexdigest()


def compute(source: Path) -> dict[str, Any]:
    """Lock untuk isi folder paket saat ini."""
    files = _hashes(source)
    if not files:
        raise PinError(f"tidak ada berkas .py di {source}")
    return {"schema": SCHEMA, "package": PACKAGE, "digest": _digest(files), "files": files}


def write_lock(lock: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    return path


def read_lock(path: Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PinError(f"lock bukan objek: {path}")
    if data.get("schema") != SCHEMA or data.get("package") != PACKAGE:
        raise PinError(f"lock bukan milik {PACKAGE} skema {SCHEMA}: {path}")
    files = data.get("files")
    if not isinstance(files, dict) or not files:
        raise PinError(f"lock tanpa daftar berkas: {path}")
    if not all(isinstance(name, str) and isinstance(sha, str) for name, sha in files.items()):
        raise PinError(f"lock berisi entri tidak sah: {path}")
    if not isinstance(data.get("digest"), str):
        raise PinError(f"lock tanpa digest: {path}")
    return data


def verify(folder: Path, lock: dict[str, Any]) -> list[str]:
    """Daftar pelanggaran: berkas hilang, berubah, atau muncul tanpa terpin."""
    sekarang = _hashes(folder)
    masalah: list[str] = []
    for name, sha in lock["files"].items():
        if name not in sekarang:
            masalah.append(f"hilang: {name}")
        elif sekarang[name] != sha:
            masalah.append(f"berubah: {name}")
    for name in sorted(set(sekarang) - set(lock["files"])):
        masalah.append(f"tak terpin: {name}")
    if not masalah and _digest(sekarang) != lock["digest"]:
        masalah.append("digest lock tidak cocok dengan isi berkas")
    return masalah


def _short(digest: str) -> str:
    return digest.split(":", 1)[-1][:12]


def snapshot_dir(store: Path, lock: dict[str, Any]) -> Path:
    """Folder snapshot milik lock ini di dalam store."""
    return Path(store) / _short(lock["digest"]) / PACKAGE


def pin(source: Path, store: Path) -> dict[str, Any]:
    """Salin paket ke `store/<digest>/` dan tulis lock-nya."""
    lock = compute(source)
    target = snapshot_dir(store, lock)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for name in lock["files"]:
        shutil.copyfile(Path(source) / name, target / name)
    masalah = verify(target, lock)
    if masalah:
        raise PinError(f"pin tidak konsisten: {masalah}")
    write_lock(lock, Path(store) / LOCK_NAME)
    return lock


def materialize(store: Path, lock: dict[str, Any], dest: Path) -> Path:
    """Siapkan salinan pin di `dest` untuk dijalankan sebagai paket.

    Kembaliannya adalah `dest`: tambahkan ke `PYTHONPATH` (dan jadikan `cwd`)
    saat menjalankan `python -m swarmfold_verify.cli`.
    """
    asal = snapshot_dir(store, lock)
    if not asal.is_dir():
        raise PinError(f"snapshot pin tidak ada: {asal}")
    target = Path(dest) / PACKAGE
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(asal, target)
    masalah = verify(target, lock)
    if masalah:
        raise PinError(f"salinan pin rusak: {masalah}")
    return Path(dest)
