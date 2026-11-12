"""Pembangkit data sintetis dengan efek yang ditanam.

Setiap kasus dibuat deterministik dari `seed`, dan anchor dihitung dari data
yang benar-benar ditulis — bukan dari angka yang diketik terpisah. Jadi
`truth.json` tidak bisa melenceng dari CSV-nya.
"""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .truth import Anchor, Case
from .truth import write as write_truth

#: Bulan 2024 dan 2025 untuk kasus deret waktu.
_MONTHS = tuple(f"2024-{month:02d}" for month in range(1, 13)) + tuple(
    f"2025-{month:02d}" for month in range(1, 13)
)


@dataclass(frozen=True)
class Generated:
    case: Case
    files: dict[str, list[list[str]]]


def _anchor(ident: str, kind: str, value: float, unit: str, tol: float, note: str = "") -> Anchor:
    return Anchor(id=ident, kind=kind, value=round(value, 6), unit=unit, tol_rel=tol, note=note)


# -- trend ---------------------------------------------------------------


def _trend(case_id: str, split: str, seed: int) -> Generated:
    """YoY turun 8%, tetapi penurunan itu bertumpu pada Januari."""
    base = [1010 + 10 * index for index in range(12)]
    acak = random.Random(seed)
    # Jitter per bulan: dua kasus dengan seed berbeda punya angka berbeda,
    # tetapi efek yang ditanam tetap sama.
    values_2024 = [2600] + [nilai + acak.randint(-15, 15) for nilai in base[1:]]  # Januari 2024 lonjakan
    total_2024 = sum(values_2024)

    target_2025 = round(total_2024 * 0.92)
    januari_2025 = 900
    sisa = target_2025 - januari_2025
    bobot = values_2024[1:]
    skala = sisa / sum(bobot)
    values_2025 = [januari_2025] + [round(nilai * skala) for nilai in bobot]

    rows: list[list[str]] = [["bulan", "total"]]
    for bulan, nilai in zip(_MONTHS, values_2024 + values_2025, strict=True):
        rows.append([bulan, str(nilai)])

    total_2025 = sum(values_2025)
    tanpa_januari_2024 = sum(values_2024[1:])
    tanpa_januari_2025 = sum(values_2025[1:])
    anchors = (
        _anchor("P1", "trend", total_2025 / total_2024 - 1, "ratio", 0.02, "YoY total"),
        _anchor(
            "P2",
            "trend",
            tanpa_januari_2025 / tanpa_januari_2024 - 1,
            "ratio",
            0.02,
            "YoY tanpa Januari",
        ),
        _anchor("N1", "trend", total_2024, "count", 0.001, "total 2024"),
    )
    case = Case(case_id=case_id, split=split, seed=seed, anchors=anchors)
    return Generated(case=case, files={"penjualan.csv": rows})


# -- simpson -------------------------------------------------------------


def _simpson(case_id: str, split: str, seed: int) -> Generated:
    """Agregat turun, tetapi setiap segmen naik: komposisi bergeser."""
    rows: list[list[str]] = [["periode", "segmen", "nilai"]]
    acak = random.Random(seed)
    besar = acak.randint(55, 65)
    kecil = 100 - besar
    komposisi = {
        ("2024", "besar"): (besar, 1000),
        ("2024", "kecil"): (kecil, 200),
        ("2025", "besar"): (besar // 3, 1200),
        ("2025", "kecil"): (100 - besar // 3, 250),
    }
    total: dict[str, int] = {"2024": 0, "2025": 0}
    for (periode, segmen), (jumlah, nilai) in komposisi.items():
        for _ in range(jumlah):
            rows.append([periode, segmen, str(nilai)])
        total[periode] += jumlah * nilai

    anchors = (
        _anchor("P1", "simpson", total["2025"] / total["2024"] - 1, "ratio", 0.01, "agregat"),
        _anchor("P2", "simpson", 1200 / 1000 - 1, "ratio", 0.01, "dalam segmen besar"),
        _anchor("P3", "simpson", 250 / 200 - 1, "ratio", 0.01, "dalam segmen kecil"),
    )
    case = Case(case_id=case_id, split=split, seed=seed, anchors=anchors)
    return Generated(case=case, files={"klaim.csv": rows})


# -- tail ----------------------------------------------------------------


def _tail(case_id: str, split: str, seed: int) -> Generated:
    """1% baris teratas memuat ~37% total: mean menyesatkan."""
    acak = random.Random(seed)
    # Nilai ikut di-jitter supaya dua kasus bersplit berbeda punya anchor
    # berbeda; kalau tidak, heldout tidak bisa membedakan hafalan dari analisis.
    nilai = [10 + acak.randint(0, 4) for _ in range(990)]
    nilai += [700 + acak.randint(-50, 50) for _ in range(10)]
    acak.shuffle(nilai)

    rows: list[list[str]] = [["klaim_id", "nilai"]]
    for index, angka in enumerate(nilai, start=1):
        rows.append([f"K-{index:04d}", str(angka)])

    total = sum(nilai)
    teratas = sum(sorted(nilai)[-10:])
    tengah = sorted(nilai)[len(nilai) // 2]
    anchors = (
        _anchor("P1", "tail", teratas / total, "ratio", 0.01, "pangsa 1% teratas"),
        _anchor("P2", "tail", total / len(nilai), "count", 0.01, "mean"),
        _anchor("P3", "tail", tengah, "count", 0.01, "median"),
    )
    case = Case(case_id=case_id, split=split, seed=seed, anchors=anchors)
    return Generated(case=case, files={"klaim.csv": rows})


# -- join ----------------------------------------------------------------


def _join(case_id: str, split: str, seed: int) -> Generated:
    """Dimensi pelanggan punya id ganda: join menggandakan baris pesanan."""
    pesanan: list[list[str]] = [["pesanan_id", "pelanggan_id", "total"]]
    jumlah_pesanan = random.Random(seed).randint(90, 110)
    for index in range(jumlah_pesanan):
        pelanggan = f"P{(index % 50) + 1:02d}"
        pesanan.append([f"O-{index + 1:03d}", pelanggan, str(1000 + index)])

    pelanggan_rows: list[list[str]] = [["pelanggan_id", "nama", "kota"]]
    for index in range(50):
        kode = f"P{index + 1:02d}"
        # Dua baris per id: inilah yang menggandakan hasil join.
        pelanggan_rows.append([kode, f"nama-{kode}", "Bandung"])
        pelanggan_rows.append([kode, f"nama-{kode}", "Bandung"])

    anchors = (
        _anchor("P1", "join", jumlah_pesanan, "count", 0.001, "baris pesanan"),
        _anchor("P2", "join", jumlah_pesanan * 2, "count", 0.001, "baris setelah join"),
        _anchor("P3", "join", 2.0, "ratio", 0.001, "inflasi join"),
    )
    case = Case(case_id=case_id, split=split, seed=seed, anchors=anchors)
    return Generated(case=case, files={"pesanan.csv": pesanan, "pelanggan.csv": pelanggan_rows})


# -- missing -------------------------------------------------------------


def _missing(case_id: str, split: str, seed: int) -> Generated:
    """Tanggal bayar hilang sistematis: hanya pada kategori Reimburse."""
    rows: list[list[str]] = [["klaim_id", "kategori", "tanggal_bayar", "nominal"]]
    jumlah_reimburse = random.Random(seed).randint(30, 40)
    for index in range(500):
        reimburse = index < jumlah_reimburse
        kategori = "Reimburse" if reimburse else "Reguler"
        tanggal = "" if reimburse else f"2025-{(index % 12) + 1:02d}-15"
        rows.append([f"C-{index + 1:04d}", kategori, tanggal, str(100000 + index)])

    hilang = sum(1 for row in rows[1:] if not row[2])
    reimburse_total = sum(1 for row in rows[1:] if row[1] == "Reimburse")
    reimburse_hilang = sum(1 for row in rows[1:] if row[1] == "Reimburse" and not row[2])
    anchors = (
        _anchor("P1", "missing", hilang / 500, "ratio", 0.02, "pangsa tanggal kosong"),
        _anchor(
            "P2",
            "missing",
            reimburse_hilang / max(1, reimburse_total),
            "ratio",
            0.02,
            "bagian Reimburse yang kosong",
        ),
    )
    case = Case(case_id=case_id, split=split, seed=seed, anchors=anchors)
    return Generated(case=case, files={"klaim.csv": rows})


# -- gap ----------------------------------------------------------------


def _gap(case_id: str, split: str, seed: int) -> Generated:
    """Satu bulan hilang di tengah dan satu bulan berjalan belum penuh."""
    rows: list[list[str]] = [["bulan", "hari_aktif", "total"]]
    hilang = random.Random(seed).randint(3, 7)
    for bulan in (f"2025-{month:02d}" for month in range(1, 13)):
        if bulan == f"2025-{hilang:02d}":
            continue
        hari = 5 if bulan == "2025-12" else 30
        rows.append([bulan, str(hari), str(1000 + hari * 10)])

    anchors = (
        _anchor("P1", "gap", len(rows) - 1, "count", 0.001, "bulan terisi"),
        _anchor("P2", "gap", 1, "count", 0.001, "bulan hilang"),
        # Hari aktif Desember, bukan "1": dua anchor bernilai sama tidak bisa
        # dibedakan oleh satu temuan dan membuat recall naik gratis.
        _anchor("P3", "gap", 5, "count", 0.001, "hari aktif bulan berjalan"),
    )
    case = Case(case_id=case_id, split=split, seed=seed, anchors=anchors)
    return Generated(case=case, files={"bulanan.csv": rows})


_BUILDERS = {
    "trend": _trend,
    "simpson": _simpson,
    "tail": _tail,
    "join": _join,
    "missing": _missing,
    "gap": _gap,
}


def build(case_id: str, split: str, seed: int) -> Generated:
    """Bangun satu kasus berdasarkan awalan `case_id` (`trend-01` → `trend`)."""
    kind = case_id.split("-")[0]
    builder = _BUILDERS.get(kind)
    if builder is None:
        raise ValueError(f"jenis kasus tidak dikenal: {kind!r}; pilih {sorted(_BUILDERS)}")
    return builder(case_id, split, seed)


def write(generated: Generated, root: Path) -> dict[str, Any]:
    """Tulis `input/*.csv` dan `truth/<id>.json`; kembalikan ringkasannya."""
    case_id = generated.case.case_id
    case_dir = Path(root) / "cases" / case_id
    input_dir = case_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in generated.files.items():
        with (input_dir / name).open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerows(rows)
    truth_path = write_truth(generated.case, Path(root) / "truth" / f"{case_id}.json")
    return {
        "case_id": case_id,
        "split": generated.case.split,
        "files": sorted(generated.files),
        "rows": {name: len(rows) - 1 for name, rows in generated.files.items()},
        "anchors": len(generated.case.anchors),
        "truth": truth_path.as_posix(),
    }
