"""Ekspor laporan markdown ke `.pdf`.

Laporan markdown tetap sumber kebenaran; PDF adalah salinan cetak. Blok diurai
oleh `markdown_blocks`, modul yang sama dengan ekspor `.docx`, sehingga isi
kedua salinan tidak bisa menyimpang.

Font memakai DejaVu Sans yang dibundel matplotlib: teks laporan berisi "Rp",
persen, dan tanda hubung tipografis, yang tidak semuanya ada di font inti PDF.
"""

from __future__ import annotations

import os
from pathlib import Path

from fpdf import FPDF
from fpdf.fonts import FontFace

from .markdown_blocks import (
    BULLET,
    CODE,
    HEADING,
    IMAGE,
    NUMBERED,
    PARAGRAPH,
    QUOTE,
    TABLE,
    Block,
    inline_runs,
    parse_blocks,
)

_BODY = 10.5
_LINE = 5.4
_MONO = 8.8
_HEADING_SIZE = {1: 17.0, 2: 13.0, 3: 11.5, 4: 10.5, 5: 10.5, 6: 10.5}
_HEADING_BEFORE = {1: 2.0, 2: 6.0, 3: 4.0, 4: 3.0, 5: 3.0, 6: 3.0}
_INK = (31, 45, 61)
_MUTED = (110, 118, 128)
_HEADER_FILL = (238, 240, 243)


def export_pdf(markdown: str, target: Path, *, base_dir: Path) -> Path:
    """Tulis `markdown` sebagai `.pdf` di `target`; kembalikan path-nya."""
    pdf = _Report()
    _register_fonts(pdf)
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(True, margin=18)
    pdf.set_margins(20, 18, 20)
    pdf.add_page()
    pdf.set_text_color(*_INK)

    for block in parse_blocks(markdown):
        _add_block(pdf, block, base_dir)

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    pdf.output(str(temporary))
    os.replace(temporary, target)
    return target


class _Report(FPDF):
    def footer(self) -> None:
        self.set_y(-14)
        self.set_font("Report", "", 8)
        self.set_text_color(*_MUTED)
        self.cell(0, 6, f"halaman {self.page_no()}/{{nb}}", align="C")
        self.set_text_color(*_INK)


def _font_dir() -> Path:
    import matplotlib

    return Path(matplotlib.__file__).parent / "mpl-data" / "fonts" / "ttf"


def _register_fonts(pdf: FPDF) -> None:
    directory = _font_dir()
    pdf.add_font("Report", "", directory / "DejaVuSans.ttf")
    pdf.add_font("Report", "B", directory / "DejaVuSans-Bold.ttf")
    pdf.add_font("Report", "I", directory / "DejaVuSans-Oblique.ttf")
    pdf.add_font("Report", "BI", directory / "DejaVuSans-BoldOblique.ttf")
    pdf.add_font("Mono", "", directory / "DejaVuSansMono.ttf")


def _content_width(pdf: FPDF) -> float:
    return pdf.w - pdf.l_margin - pdf.r_margin


def _add_block(pdf: FPDF, block: Block, base_dir: Path) -> None:
    if block.kind == HEADING:
        _add_heading(pdf, block.text, block.level)
    elif block.kind == PARAGRAPH:
        _write_runs(pdf, block.text)
    elif block.kind in {BULLET, NUMBERED}:
        marker = "•" if block.kind == BULLET else "–"
        pdf.set_x(pdf.l_margin + 3)
        _write_runs(pdf, f"{marker}  {block.text}", indent=3)
    elif block.kind == QUOTE:
        pdf.set_x(pdf.l_margin + 4)
        pdf.set_text_color(*_MUTED)
        _write_runs(pdf, block.text, size=_BODY - 0.5)
        pdf.set_text_color(*_INK)
    elif block.kind == CODE:
        pdf.set_font("Mono", "", _MONO)
        pdf.set_fill_color(*_HEADER_FILL)
        pdf.multi_cell(0, _LINE, block.text, fill=True)
        pdf.ln(2)
    elif block.kind == IMAGE:
        _add_image(pdf, block.alt, block.source, base_dir)
    elif block.kind == TABLE:
        _add_table(pdf, block.rows)


def _add_heading(pdf: FPDF, text: str, level: int) -> None:
    pdf.ln(_HEADING_BEFORE.get(level, 3.0))
    pdf.set_font("Report", "B", _HEADING_SIZE.get(level, _BODY))
    pdf.multi_cell(0, _LINE + 1.4, text)
    if level == 1:
        pdf.set_draw_color(*_HEADER_FILL)
        pdf.set_line_width(0.6)
        y = pdf.get_y() + 1.5
        pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
        pdf.ln(3)
    pdf.ln(1.2)


def _write_runs(pdf: FPDF, text: str, *, size: float = _BODY, indent: float = 0.0) -> None:
    """Tulis satu paragraf mengalir, ganti font per gaya inline."""
    if indent:
        pdf.set_x(pdf.l_margin + indent)
    for style, chunk in inline_runs(text):
        if style == "bold":
            pdf.set_font("Report", "B", size)
        elif style == "italic":
            pdf.set_font("Report", "I", size)
        elif style == "code":
            pdf.set_font("Mono", "", size - 1.7)
        else:
            pdf.set_font("Report", "", size)
        pdf.write(_LINE, chunk)
    pdf.ln(_LINE + 0.6)


def _add_image(pdf: FPDF, alt: str, source: str, base_dir: Path) -> None:
    path = Path(source)
    if not path.is_absolute():
        path = base_dir / path
    if not path.is_file():
        pdf.set_font("Report", "I", 9)
        pdf.multi_cell(0, _LINE, f"[grafik tidak ditemukan: {source}]")
        pdf.ln(2)
        return
    width = _content_width(pdf)
    pdf.image(str(path), x=pdf.l_margin, w=width)
    if alt:
        pdf.set_font("Report", "I", 8.5)
        pdf.set_text_color(*_MUTED)
        pdf.multi_cell(0, 4.6, alt, align="C")
        pdf.set_text_color(*_INK)
    pdf.ln(2)


def _add_table(pdf: FPDF, rows: list[list[str]]) -> None:
    if not rows:
        return
    pdf.set_font("Report", "", 9)
    widths = _column_widths(rows, _content_width(pdf))
    with pdf.table(
        col_widths=widths,
        text_align="LEFT",
        line_height=5.0,
        padding=1.6,
        headings_style=FontFace(emphasis="BOLD", fill_color=_HEADER_FILL),
    ) as table:
        for row in rows:
            line = table.row()
            for cell in row:
                line.cell(cell)
    pdf.ln(2.4)


def _column_widths(rows: list[list[str]], total: float) -> tuple[float, ...]:
    """Bagi lebar menurut panjang isi terpanjang, dengan lantai per kolom."""
    columns = max(len(row) for row in rows)
    weights: list[float] = []
    for column in range(columns):
        longest = max((len(row[column]) for row in rows if column < len(row)), default=0)
        weights.append(max(longest, 6) ** 0.7)
    scale = total / sum(weights)
    return tuple(round(weight * scale, 2) for weight in weights)
