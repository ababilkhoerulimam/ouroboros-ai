"""Tes ekspor laporan markdown ke `.docx`."""

from __future__ import annotations

import base64

from docx import Document

from swarmfold.docx_export import export_docx

#: PNG 1x1 transparan; cukup untuk menguji jalur gambar tanpa matplotlib.
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

```python
print(1)
```
"""


def test_heading_paragraf_tabel_dan_gambar(tmp_path):
    charts = tmp_path / "charts"
    charts.mkdir()
    (charts / "air.png").write_bytes(base64.b64decode(_PNG))
    target = tmp_path / "laporan.docx"

    export_docx(_MARKDOWN, target, base_dir=tmp_path)

    document = Document(str(target))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "Laporan penjualan" in text
    assert "Ringkasan" in text
    assert "-16,64%" in text
    assert "print(1)" in text
    assert any(run.bold for paragraph in document.paragraphs for run in paragraph.runs), (
        "teks **tebal** harus jadi run bold"
    )
    assert len(document.tables) == 1
    table = document.tables[0]
    assert table.cell(0, 0).text == "SKU"
    assert table.cell(1, 0).text == "HAMUG"
    assert table.cell(2, 1).text == "27,7%", "baris pemisah tidak boleh jadi data"
    assert len(document.inline_shapes) == 1


def test_gambar_hilang_ditandai_tanpa_menggagalkan_dokumen(tmp_path):
    target = tmp_path / "laporan.docx"

    export_docx("![Grafik hilang](charts/tidak-ada.png)\n", target, base_dir=tmp_path)

    document = Document(str(target))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "grafik tidak ditemukan" in text
    assert not document.inline_shapes


def test_tabel_dengan_jumlah_kolom_tidak_rata(tmp_path):
    markdown = "| a | b | c |\n|---|---|---|\n| 1 | 2 |\n"
    target = tmp_path / "laporan.docx"

    export_docx(markdown, target, base_dir=tmp_path)

    table = Document(str(target)).tables[0]
    assert table.cell(1, 2).text == "", "sel yang tidak diisi tetap ada dan kosong"
