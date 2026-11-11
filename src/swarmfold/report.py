"""Renderer slot laporan, CONTRACTS.md §8.

Laporan ditulis model sebagai markdown berslot: `{{E-004}}` untuk nilai yang
dibaca, `{{E-004.chart}}` untuk gambar, `{{E-004.value}}` untuk angka mentah.
Renderer ini menggantinya dari `evidence/*.json`.

Aturan yang mengikat (CONTRACTS.md §8): bila satu slot gagal, **seluruh laporan
gagal terbit**. Tidak ada penggantian diam-diam dengan tanda "-" atau teks lain,
karena laporan yang kehilangan satu angka tetap terlihat selesai padahal tidak.
"""

from __future__ import annotations

import re
from typing import Any

from .evidence import PHASES, SECTIONS, EvidenceStore

#: `{{E-001}}`, `{{E-001.chart}}`, `{{E-001.value}}`. Hanya `E-###` yang bisa
#: dirender; hipotesis dan anomali tidak pernah muncul sebagai angka di laporan.
_SLOT = re.compile(r"\{\{(E-\d{3})(\.chart|\.value)?\}\}")


class ReportError(RuntimeError):
    """Satu slot tidak bisa dirender; laporan tidak boleh terbit."""


def _finding_index(store: EvidenceStore) -> dict[str, tuple[str, dict[str, Any]]]:
    index: dict[str, tuple[str, dict[str, Any]]] = {}
    for phase in PHASES:
        data = store.load(phase)
        for section in SECTIONS:
            bucket = data.get(section)
            if not isinstance(bucket, list):
                continue
            for entry in bucket:
                if not isinstance(entry, dict):
                    continue
                ident = entry.get("id")
                if isinstance(ident, str) and ident.startswith("E-"):
                    index[ident] = (phase, entry)
    return index


def render_slots(
    text: str,
    *,
    store: EvidenceStore,
    completed: list[str],
    audited: bool = False,
) -> str:
    """Ganti setiap slot dengan nilainya, atau gagal seluruhnya.

    `audited` menandai F6 sudah selesai. Temuan dari fase yang dilewati tetap
    boleh dikutip bila audit sudah jalan: pada run 2026-11-11-ecd0b9 F4 dilewati
    karena data tidak punya identifier pelanggan, dan dua temuannya
    (`0 kolom ditemukan`) justru satu-satunya cara laporan menjelaskan alasannya.
    Tanpa audit, temuan fase yang belum selesai tetap ditolak karena belum ada
    yang memeriksanya.
    """
    index = _finding_index(store)
    done = set(completed)

    def replace(match: re.Match[str]) -> str:
        ident, suffix = match.group(1), match.group(2) or ""
        found = index.get(ident)
        if found is None:
            raise ReportError(f"{ident}: id tidak ada di evidence")
        phase, entry = found
        if phase not in done and not audited:
            raise ReportError(f"{ident}: fase {phase} belum selesai")
        if entry.get("verified") is not True:
            raise ReportError(f"{ident}: verified bukan true")
        if suffix == ".chart":
            chart = entry.get("chart")
            if not isinstance(chart, str) or not chart.strip():
                raise ReportError(f"{ident}: finding tidak punya chart")
            return chart.strip()
        if suffix == ".value":
            unit = entry.get("unit")
            if not isinstance(unit, str) or not unit.strip():
                raise ReportError(f"{ident}: unit kosong")
            return f"{entry.get('value')} {unit.strip()}"
        display = entry.get("display")
        if not isinstance(display, str) or not display.strip():
            raise ReportError(f"{ident}: display kosong")
        return display.strip()

    return _SLOT.sub(replace, text)
