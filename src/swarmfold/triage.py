"""Triage deterministik: layak dianalisis penuh, hanya dibersihkan, atau belum siap.

Berjalan tanpa model, tepat setelah ingest. Tujuannya mencegah dua kegagalan
mahal: (a) model menjalankan seluruh F1-F7 pada CSV yang tidak punya sinyal
bisnis, lalu mengarang narasi; (b) model menghabiskan cell untuk menyimpulkan
bahwa data kosong.

Verdict yang dihasilkan:

- ``full`` — ada sinyal bisnis (nominal + tanggal/entitas); jalankan F1-F7.
- ``cleaning_only`` — data bisa dirapikan tetapi tidak cukup untuk analisis;
  F1 lalu laporan kualitas data, tanpa F2-F6.
- ``insufficient`` — baris/kolom terlalu sedikit atau kosong; laporan
  "data belum siap" tanpa menjalankan kernel.

Pack doktrin belum dipilih di sini: versi ini selalu memakai pack dari
``Settings`` (default ``business``). Pemilihan pack generic menyusul bersama
pack-nya, supaya tidak ada pack yang dirujuk tetapi belum ada.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import Any

MODE_FULL = "full"
MODE_CLEANING = "cleaning_only"
MODE_INSUFFICIENT = "insufficient"

MIN_ROWS = 3
MIN_COLS = 2
NOMINAL_MEDIAN = 100.0

_DATE_HINTS = (
    "tanggal",
    "date",
    "tgl",
    "waktu",
    "time",
    "periode",
    "period",
    "bulan",
    "month",
    "tahun",
    "year",
)
_NOMINAL_HINTS = (
    "total",
    "harga",
    "price",
    "amount",
    "omzet",
    "revenue",
    "nilai",
    "biaya",
    "cost",
    "pendapatan",
    "sales",
    "penjualan",
    "gaji",
    "salary",
    "diskon",
    "discount",
)
_ENTITY_HINTS = (
    "pelanggan",
    "customer",
    "produk",
    "product",
    "barang",
    "item",
    "sku",
    "kode",
    "code",
    "transaksi",
    "invoice",
    "order",
    "pesanan",
)
_ID_TOKEN = re.compile(r"(^|_)id($|_)")
_DATE_VALUE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")
_NUMBER = re.compile(r"-?\d+(?:[.,]\d+)?")


@dataclass(frozen=True)
class Triage:
    """Hasil triage satu run, siap ditulis ke ``profile.json``."""

    mode: str
    reasons: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "reasons": list(self.reasons), "missing": list(self.missing)}


def _norm(name: Any) -> str:
    return re.sub(r"[\s_-]+", "_", str(name).lower()).strip("_")


def _is_numeric(column: dict[str, Any]) -> bool:
    return str(column.get("dtype", "")).startswith(("int", "float", "Int", "Float"))


def _numbers(column: dict[str, Any]) -> list[float]:
    values: list[float] = []
    for sample in column.get("samples") or []:
        match = _NUMBER.search(str(sample).replace("Rp", "").strip())
        if match:
            try:
                values.append(float(match.group(0).replace(",", ".")))
            except ValueError:
                continue
    return values


def _has_nominal(column: dict[str, Any]) -> bool:
    name = _norm(column.get("name"))
    if any(hint in name for hint in _NOMINAL_HINTS):
        return True
    if not _is_numeric(column):
        return False
    values = _numbers(column)
    return bool(values) and statistics.median(values) >= NOMINAL_MEDIAN


def _has_date(column: dict[str, Any]) -> bool:
    name = _norm(column.get("name"))
    if any(hint in name for hint in _DATE_HINTS):
        return True
    return any(_DATE_VALUE.search(str(sample)) for sample in column.get("samples") or [])


def _has_entity(column: dict[str, Any]) -> bool:
    name = _norm(column.get("name"))
    if _ID_TOKEN.search(name):
        return True
    return any(hint in name for hint in _ENTITY_HINTS)


def triage_profile(profile: dict[str, Any]) -> Triage:
    """Nilai satu profile ingest; tidak pernah melempar untuk input wajar."""
    files = profile.get("files") if isinstance(profile, dict) else None
    files = [item for item in files or [] if isinstance(item, dict)]
    rows = sum(int(item.get("rows") or 0) for item in files)
    cols = max((int(item.get("cols") or 0) for item in files), default=0)
    columns = [
        column
        for item in files
        for column in (item.get("columns") or [])
        if isinstance(column, dict)
    ]

    if rows < MIN_ROWS or cols < MIN_COLS or not columns:
        return Triage(
            MODE_INSUFFICIENT,
            [f"data terlalu kecil: {rows} baris, {cols} kolom (minimum {MIN_ROWS} x {MIN_COLS})"],
            ["minimal 3 baris data dan 2 kolom"],
        )

    nominal = [column for column in columns if _has_nominal(column)]
    dated = [column for column in columns if _has_date(column)]
    entity = [column for column in columns if _has_entity(column)]

    missing: list[str] = []
    if not nominal:
        missing.append("kolom nominal (harga, total, omzet, atau nilai)")
    if not dated:
        missing.append("kolom tanggal agar tren bisa dihitung")
    if not entity:
        missing.append("identifier pelanggan/produk agar segmen bisa dihitung")

    if nominal and (dated or entity):
        reasons = [
            f"nominal: {', '.join(_names(nominal))}",
            f"tanggal: {', '.join(_names(dated)) or 'tidak ada'}",
            f"entitas: {', '.join(_names(entity)) or 'tidak ada'}",
        ]
        return Triage(MODE_FULL, reasons, [])

    if nominal or dated or entity:
        reasons = ["sinyal bisnis tidak lengkap untuk analisis penuh"]
        reasons.extend(missing)
        return Triage(MODE_CLEANING, reasons, missing)

    return Triage(
        MODE_CLEANING,
        ["tidak ada sinyal bisnis (nominal, tanggal, atau entitas)"],
        missing,
    )


def _names(columns: list[dict[str, Any]]) -> list[str]:
    return [str(column.get("name")) for column in columns]
