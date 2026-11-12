"""Pembagian kasus benchmark.

`tune` dipakai memilih patch, `heldout` menolak patch yang hanya menghafal satu
dataset, dan `sealed` tidak pernah dipakai seleksi sama sekali — ia hanya
dibuka untuk laporan akhir. Modul ini yang menjaga batas itu, karena skrip
pemanggil tidak boleh menentukan sendiri split mana yang dipakai.
"""

from __future__ import annotations

import json
from pathlib import Path

from .truth import load as load_truth

SPLITS = ("tune", "heldout", "sealed")
SPLITS_FILE = "splits.json"
#: Split yang boleh dipakai memilih varian. `sealed` sengaja tidak termasuk.
SELECTABLE = ("tune", "heldout")


class SplitError(RuntimeError):
    """Pembagian kasus tidak lengkap atau dipakai di luar aturan."""


def load(root: Path) -> dict[str, list[str]]:
    """Baca `evals/splits.json` dan periksa bentuknya."""
    path = Path(root) / SPLITS_FILE
    if not path.is_file():
        raise SplitError(f"belum ada {path}; jalankan `swarmfold-verify build`")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SplitError(f"{path} bukan objek")
    hasil: dict[str, list[str]] = {}
    terlihat: set[str] = set()
    for split in SPLITS:
        kasus = data.get(split, [])
        if not isinstance(kasus, list) or not all(isinstance(item, str) for item in kasus):
            raise SplitError(f"{split} harus daftar id kasus")
        tumpang = terlihat & set(kasus)
        if tumpang:
            raise SplitError(f"kasus di dua split: {sorted(tumpang)}")
        terlihat |= set(kasus)
        hasil[split] = list(kasus)
    return hasil


def cases_for(root: Path, split: str) -> list[str]:
    """Kasus untuk satu split; `sealed` ditolak karena tidak boleh dipakai seleksi."""
    if split not in SPLITS:
        raise SplitError(f"split tidak dikenal: {split!r}; pilih {SPLITS}")
    if split not in SELECTABLE:
        raise SplitError(f"split {split!r} tidak boleh dipakai seleksi")
    return load(root)[split]


def expand(cases: list[str], replicas: int) -> list[tuple[str, int]]:
    """Setiap kasus dijalankan `replicas` kali; indeks replika ikut dicatat."""
    if replicas < 1:
        raise SplitError("replicas minimal 1")
    return [(case, index) for case in cases for index in range(replicas)]


def verify(root: Path) -> list[str]:
    """Cocokkan `splits.json` dengan `truth/*.json`; kembalikan pelanggaran."""
    root = Path(root)
    try:
        pembagian = load(root)
    except (SplitError, json.JSONDecodeError) as error:
        return [str(error)]

    masalah: list[str] = []
    terdaftar = {case for daftar in pembagian.values() for case in daftar}
    for split, daftar in pembagian.items():
        for case_id in daftar:
            path = root / "truth" / f"{case_id}.json"
            if not path.is_file():
                masalah.append(f"{case_id}: truth tidak ada")
                continue
            try:
                asli = load_truth(path).split
            except ValueError as error:
                masalah.append(f"{case_id}: truth cacat ({error})")
                continue
            if asli != split:
                masalah.append(f"{case_id}: terdaftar di {split}, truth menulis {asli}")
    for path in sorted((root / "truth").glob("*.json")):
        if path.stem not in terdaftar:
            masalah.append(f"{path.stem}: truth tanpa split")
    return masalah
