"""Ekspor laporan markdown ke `.docx`.

Laporan tetap ditulis sebagai markdown berslot (`laporan.md`) karena itu format
yang bisa diaudit dan dirender ulang. `.docx` adalah salinan untuk pembaca yang
membutuhkan berkas Word: tabel tetap tabel, gambar tetap gambar.

Yang didukung: heading `#`..`######`, paragraf, daftar `-`/`1.`, tabel pipa,
gambar `![alt](path)`, dan teks tebal/miring/`kode` sebaris. Yang tidak
didukung sengaja: HTML mentah, catatan kaki, dan blok kutipan bertingkat -
laporan tidak memakainya, dan menebak artinya lebih berbahaya daripada
membiarkannya sebagai teks biasa.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Inches, Pt

#: Lebar gambar maksimum di halaman A4 dengan margin 2,2 cm.
_IMAGE_WIDTH = Inches(6.3)

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_IMAGE = re.compile(r"^!\[(.*?)\]\((.+?)\)\s*$")
_BULLET = re.compile(r"^[-*]\s+(.*)$")
_NUMBERED = re.compile(r"^\d+[.)]\s+(.*)$")
_TABLE_SEPARATOR = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
#: `**tebal**`, `` `kode` ``, `*miring*`, `_miring_` - urutan penting, tebal dulu.
_INLINE = re.compile(r"(\*\*.+?\*\*|`[^`]+?`|\*[^*\n]+?\*|_[^_\n]+?_)")


def export_docx(markdown: str, target: Path, *, base_dir: Path) -> Path:
    """Tulis `markdown` sebagai `.docx` di `target`; kembalikan path-nya.

    `base_dir` dipakai untuk mencari gambar yang dirujuk secara relatif. Gambar
    yang tidak ada ditandai di dokumen, bukan menggagalkan seluruh dokumen:
    laporan yang kehilangan satu grafik masih terbaca, laporan yang tidak terbit
    sama sekali tidak.
    """
    document = Document()
    _setup(document)
    lines = markdown.replace("\r\n", "\n").split("\n")
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()

        if not stripped:
            index += 1
            continue

        if stripped.startswith("```"):
            index = _add_code(document, lines, index)
            continue

        heading = _HEADING.match(stripped)
        if heading:
            document.add_heading(_plain(heading.group(2)), level=len(heading.group(1)))
            index += 1
            continue

        image = _IMAGE.match(stripped)
        if image:
            _add_image(document, image.group(1), image.group(2), base_dir)
            index += 1
            continue

        if stripped.startswith("|"):
            index = _add_table(document, lines, index)
            continue

        bullet = _BULLET.match(stripped)
        if bullet:
            _add_inline(document.add_paragraph(style="List Bullet"), bullet.group(1))
            index += 1
            continue

        numbered = _NUMBERED.match(stripped)
        if numbered:
            _add_inline(document.add_paragraph(style="List Number"), numbered.group(1))
            index += 1
            continue

        if stripped.startswith(">"):
            paragraph = document.add_paragraph(style="Intense Quote")
            _add_inline(paragraph, stripped.lstrip("> ").strip())
            index += 1
            continue

        if set(stripped) <= {"-", "*", "_"} and len(stripped) >= 3:
            index += 1
            continue

        _add_inline(document.add_paragraph(), stripped)
        index += 1

    target.parent.mkdir(parents=True, exist_ok=True)
    # Simpan ke berkas sementara lalu ganti, supaya pembaca tidak pernah
    # melihat .docx setengah jadi saat ada proses lain membaca direktori run.
    temporary = target.with_name(target.name + ".tmp")
    document.save(temporary)
    os.replace(temporary, target)
    return target


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


def _plain(text: str) -> str:
    """Buang penanda inline; dipakai untuk heading dan sel tabel."""
    text = _LINK.sub(r"\1", text)
    return text.replace("**", "").replace("`", "").strip()


def _add_inline(paragraph, text: str) -> None:
    """Isi paragraf dengan run tebal/miring/kode sesuai penanda markdown."""
    text = _LINK.sub(r"\1", text)
    position = 0
    for match in _INLINE.finditer(text):
        if match.start() > position:
            paragraph.add_run(text[position : match.start()])
        token = match.group(0)
        if token.startswith("**"):
            paragraph.add_run(token[2:-2]).bold = True
        elif token.startswith("`"):
            run = paragraph.add_run(token[1:-1])
            run.font.name = "Consolas"
            run.font.size = Pt(9.5)
        else:
            paragraph.add_run(token[1:-1]).italic = True
        position = match.end()
    if position < len(text):
        paragraph.add_run(text[position:])


def _add_code(document: Document, lines: list[str], index: int) -> int:
    index += 1
    block: list[str] = []
    while index < len(lines) and not lines[index].strip().startswith("```"):
        block.append(lines[index])
        index += 1
    paragraph = document.add_paragraph()
    run = paragraph.add_run("\n".join(block))
    run.font.name = "Consolas"
    run.font.size = Pt(9.5)
    return index + 1


def _add_image(document: Document, alt: str, source: str, base_dir: Path) -> None:
    path = Path(source.strip())
    if not path.is_absolute():
        path = base_dir / path
    if not path.is_file():
        note = document.add_paragraph(f"[grafik tidak ditemukan: {source.strip()}]")
        note.runs[0].italic = True
        return
    document.add_picture(str(path), width=_IMAGE_WIDTH)
    document.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    if alt.strip():
        caption = document.add_paragraph()
        caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = caption.add_run(_plain(alt))
        run.italic = True
        run.font.size = Pt(9)


def _add_table(document: Document, lines: list[str], index: int) -> int:
    rows: list[list[str]] = []
    while index < len(lines) and lines[index].strip().startswith("|"):
        stripped = lines[index].strip()
        if not _TABLE_SEPARATOR.match(stripped):
            rows.append([_plain(cell) for cell in _split_row(stripped)])
        index += 1
    if not rows:
        return index
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
    return index


def _split_row(line: str) -> list[str]:
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    return [cell.strip() for cell in text.split("|")]
