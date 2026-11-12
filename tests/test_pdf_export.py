"""Tes ekspor laporan markdown ke `.pdf`."""

from __future__ import annotations

import base64
import re

from swarmfold.pdf_export import export_pdf

#: PNG 1x1 transparan; cukup untuk menguji jalur gambar tanpa matplotlib plot.
_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGA"
    "hKmMIQAAAABJRU5ErkJggg=="
)

_MARKDOWN = """# Laporan penjualan

## Ringkasan

Penjualan turun **-16,64%** sebesar -Rp 50.154.662, jadi `fokus` tiga SKU.

- butir satu
- butir dua

| SKU | Turun |
|---|---|
| HAMUG | 12,4% |
| HAMPERS | 27,7% |

![Waterfall dekomposisi](charts/air.png)
"""


def test_pdf_berhalaman_dengan_tabel_dan_gambar(tmp_path):
    charts = tmp_path / "charts"
    charts.mkdir()
    (charts / "air.png").write_bytes(base64.b64decode(_PNG))
    target = tmp_path / "laporan.pdf"

    export_pdf(_MARKDOWN, target, base_dir=tmp_path)

    data = target.read_bytes()
    assert data.startswith(b"%PDF")
    assert len(data) > 2000, "PDF harus memuat font dan tabel, bukan halaman kosong"
    assert len(re.findall(rb"/Type\s*/Page(?![s])", data)) == 1


def test_tabel_panjang_terpecah_ke_halaman_berikutnya(tmp_path):
    rows = ["| SKU | Nilai |", "|---|---|"]
    rows += [f"| SKU-{index:03d} | {index},5% |" for index in range(120)]
    target = tmp_path / "panjang.pdf"

    export_pdf("\n".join(rows) + "\n", target, base_dir=tmp_path)

    data = target.read_bytes()
    assert len(re.findall(rb"/Type\s*/Page(?![s])", data)) >= 2, "tabel panjang harus berlanjut"


def test_gambar_hilang_ditandai_tanpa_menggagalkan_pdf(tmp_path):
    target = tmp_path / "laporan.pdf"

    export_pdf("![Grafik hilang](charts/tidak-ada.png)\n", target, base_dir=tmp_path)

    assert target.read_bytes().startswith(b"%PDF")
