"""Data sintetis deterministik untuk tes.

Angka di sini fiktif dan tetap: total omzet 1.812.000, 12 transaksi, 6 pelanggan.
Tes memakai data ini supaya asersi menyebut angka nyata tanpa menyalin data
produksi atau membuat DataFrame ad-hoc di tiap berkas tes.
"""

from __future__ import annotations

import csv
from pathlib import Path

HARGA: dict[str, int] = {"Kopi": 18_000, "Teh": 12_000, "Roti": 9_000}

#: (tanggal, produk, qty) — urut kronologis, tanpa angka acak.
PENJUALAN: tuple[tuple[str, str, int], ...] = (
    ("2025-01-05", "Kopi", 10),
    ("2025-01-19", "Teh", 8),
    ("2025-02-02", "Roti", 12),
    ("2025-02-16", "Kopi", 15),
    ("2025-03-02", "Teh", 9),
    ("2025-03-16", "Roti", 20),
    ("2025-04-06", "Kopi", 7),
    ("2025-04-20", "Teh", 14),
    ("2025-05-04", "Roti", 11),
    ("2025-05-18", "Kopi", 18),
    ("2025-06-01", "Teh", 6),
    ("2025-06-15", "Roti", 9),
)

PELANGGAN: tuple[tuple[str, str, str, str], ...] = (
    ("P-01", "Ani", "Bandung", "reguler"),
    ("P-02", "Budi", "Bandung", "reguler"),
    ("P-03", "Citra", "Jakarta", "grosir"),
    ("P-04", "Dewi", "Jakarta", "reguler"),
    ("P-05", "Eko", "Surabaya", "grosir"),
    ("P-06", "Fajar", "Surabaya", "reguler"),
)


def total_omzet() -> int:
    """Total `qty * harga` seluruh baris sintetis."""
    return sum(qty * HARGA[produk] for _, produk, qty in PENJUALAN)


def tulis_penjualan(path: Path) -> Path:
    """Tulis `penjualan.csv`; `total` = qty * harga, tanpa pemisah ribuan."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["tanggal", "produk", "qty", "harga", "total"])
        for tanggal, produk, qty in PENJUALAN:
            harga = HARGA[produk]
            writer.writerow([tanggal, produk, qty, harga, qty * harga])
    return path


def tulis_pelanggan(path: Path) -> Path:
    """Tulis `pelanggan.csv` dengan identifier yang bisa di-join ke transaksi."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["pelanggan_id", "nama", "kota", "segmen"])
        writer.writerows(PELANGGAN)
    return path
