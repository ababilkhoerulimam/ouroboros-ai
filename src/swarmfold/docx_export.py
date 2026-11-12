"""Ekspor laporan markdown ke `.docx`.

Laporan tetap ditulis sebagai markdown berslot (`laporan.md`) karena itu format
yang bisa diaudit dan dirender ulang. `.docx` adalah salinan untuk pembaca yang
membutuhkan berkas Word: tabel tetap tabel, gambar tetap gambar.

Blok diurai oleh `markdown_blocks`, modul yang sama yang dipakai ekspor PDF,
supaya kedua salinan tidak pernah berbeda tafsir.
"""

from __future__ import annotations

import os
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Inches, Pt

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

#: Lebar gambar maksimum di halaman A4 dengan margin 2,2 cm.
_IMAGE_WIDTH = Inches(6.3)


def export_docx(markdown: str, target: Path, *, base_dir: Path) -> Path:
    """Tulis `markdown` sebagai `.docx` di `target`; kembalikan path-nya.

    `base_dir` dipakai untuk mencari gambar yang dirujuk secara relatif. Gambar
    yang tidak ada ditandai di dokumen, bukan menggagalkan seluruh dokumen:
    laporan yang kehilangan satu grafik masih terbaca, laporan yang tidak terbit
    sama sekali tidak.
    """
    document = Document()
    _setup(document)
    for block in parse_blocks(markdown):
        _add_block(document, block, base_dir)

    target.parent.mkdir(parents=True, exist_ok=True)
    # Simpan ke berkas sementara lalu ganti, supaya pembaca tidak pernah
    # melihat .docx setengah jadi saat ada proses lain membaca direktori run.
    temporary = target.with_name(target.name + ".tmp")
    document.save(temporary)
    os.replace(temporary, target)
    return target


def _add_block(document: Document, block: Block, base_dir: Path) -> None:
    if block.kind == HEADING:
        document.add_heading(block.text, level=block.level)
    elif block.kind == PARAGRAPH:
        _add_inline(document.add_paragraph(), block.text)
    elif block.kind == BULLET:
        _add_inline(document.add_paragraph(style="List Bullet"), block.text)
    elif block.kind == NUMBERED:
        _add_inline(document.add_paragraph(style="List Number"), block.text)
    elif block.kind == QUOTE:
        _add_inline(document.add_paragraph(style="Intense Quote"), block.text)
    elif block.kind == CODE:
        run = document.add_paragraph().add_run(block.text)
        run.font.name = "Consolas"
        run.font.size = Pt(9.5)
    elif block.kind == IMAGE:
        _add_image(document, block.alt, block.source, base_dir)
    elif block.kind == TABLE:
        _add_table(document, block.rows)


def _setup(document: Document) -> None:
    style = document.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)
    style.paragraph_format.space_after = Pt(6)
    for section in document.sections:
        section.top_margin = Cm(2.2)
        section.bottom_margin = Cm(2.2)
        section.left_margin = Cm(2.2)
        section.right_margin = Cm(2.2)


def _add_inline(paragraph, text: str) -> None:
    """Isi paragraf dengan run tebal/miring/kode sesuai penanda markdown."""
    for style, chunk in inline_runs(text):
        if style == "bold":
            paragraph.add_run(chunk).bold = True
        elif style == "italic":
            paragraph.add_run(chunk).italic = True
        elif style == "code":
            run = paragraph.add_run(chunk)
            run.font.name = "Consolas"
            run.font.size = Pt(9.5)
        else:
            paragraph.add_run(chunk)


def _add_image(document: Document, alt: str, source: str, base_dir: Path) -> None:
    path = Path(source)
    if not path.is_absolute():
        path = base_dir / path
    if not path.is_file():
        note = document.add_paragraph(f"[grafik tidak ditemukan: {source}]")
        note.runs[0].italic = True
        return
    document.add_picture(str(path), width=_IMAGE_WIDTH)
    document.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    if alt:
        caption = document.add_paragraph()
        caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = caption.add_run(alt)
        run.italic = True
        run.font.size = Pt(9)


def _add_table(document: Document, rows: list[list[str]]) -> None:
    if not rows:
        return
    columns = max(len(row) for row in rows)
    table = document.add_table(rows=len(rows), cols=columns)
    table.style = "Table Grid"
    for row_index, row in enumerate(rows):
        for column_index in range(columns):
            cell = table.cell(row_index, column_index)
            cell.text = row[column_index] if column_index < len(row) else ""
            if row_index == 0:
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        run.bold = True
    document.add_paragraph()
