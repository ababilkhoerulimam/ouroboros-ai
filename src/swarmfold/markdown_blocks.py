"""Parser blok markdown untuk laporan.

`laporan.md` adalah sumber kebenaran; `.docx` dan `.pdf` hanyalah salinan untuk
pembaca. Supaya kedua salinan tidak pernah berbeda tafsir, keduanya membaca
blok yang sama dari modul ini, bukan masing-masing menebak sendiri.

Cakupan sengaja sempit, mengikuti apa yang benar-benar ditulis laporan: heading
`#`..`######`, paragraf, daftar `-`/`1.`, tabel pipa, gambar, blok kode, dan
kutipan. HTML mentah dan catatan kaki tidak didukung.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

HEADING = "heading"
PARAGRAPH = "paragraph"
BULLET = "bullet"
NUMBERED = "numbered"
TABLE = "table"
IMAGE = "image"
CODE = "code"
QUOTE = "quote"

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_IMAGE = re.compile(r"^!\[(.*?)\]\((.+?)\)\s*$")
_BULLET = re.compile(r"^[-*]\s+(.*)$")
_NUMBERED = re.compile(r"^\d+[.)]\s+(.*)$")
_TABLE_SEPARATOR = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
#: `**tebal**`, `` `kode` ``, `*miring*`, `_miring_` - tebal didahulukan.
_INLINE = re.compile(r"(\*\*.+?\*\*|`[^`]+?`|\*[^*\n]+?\*|_[^_\n]+?_)")


@dataclass
class Block:
    """Satu blok markdown yang sudah diurai."""

    kind: str
    text: str = ""
    level: int = 0
    rows: list[list[str]] = field(default_factory=list)
    alt: str = ""
    source: str = ""


def plain(text: str) -> str:
    """Buang penanda inline; dipakai untuk heading, sel tabel, dan nama grafik."""
    text = _LINK.sub(r"\1", text)
    return text.replace("**", "").replace("`", "").strip()


def inline_runs(text: str) -> list[tuple[str, str]]:
    """Pecah satu baris menjadi `(gaya, potongan)`; gaya: ``, bold, italic, code."""
    text = _LINK.sub(r"\1", text)
    runs: list[tuple[str, str]] = []
    position = 0
    for match in _INLINE.finditer(text):
        if match.start() > position:
            runs.append(("", text[position : match.start()]))
        token = match.group(0)
        if token.startswith("**"):
            runs.append(("bold", token[2:-2]))
        elif token.startswith("`"):
            runs.append(("code", token[1:-1]))
        else:
            runs.append(("italic", token[1:-1]))
        position = match.end()
    if position < len(text):
        runs.append(("", text[position:]))
    return runs


def parse_blocks(markdown: str) -> list[Block]:
    """Urai markdown menjadi daftar `Block` berurutan."""
    lines = markdown.replace("\r\n", "\n").split("\n")
    blocks: list[Block] = []
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()

        if not stripped:
            index += 1
            continue

        if stripped.startswith("```"):
            index, block = _code(lines, index)
            blocks.append(block)
            continue

        heading = _HEADING.match(stripped)
        if heading:
            blocks.append(
                Block(kind=HEADING, text=plain(heading.group(2)), level=len(heading.group(1)))
            )
            index += 1
            continue

        image = _IMAGE.match(stripped)
        if image:
            blocks.append(
                Block(kind=IMAGE, alt=plain(image.group(1)), source=image.group(2).strip())
            )
            index += 1
            continue

        if stripped.startswith("|"):
            index, block = _table(lines, index)
            blocks.append(block)
            continue

        bullet = _BULLET.match(stripped)
        if bullet:
            blocks.append(Block(kind=BULLET, text=bullet.group(1).strip()))
            index += 1
            continue

        numbered = _NUMBERED.match(stripped)
        if numbered:
            blocks.append(Block(kind=NUMBERED, text=numbered.group(1).strip()))
            index += 1
            continue

        if stripped.startswith(">"):
            blocks.append(Block(kind=QUOTE, text=stripped.lstrip("> ").strip()))
            index += 1
            continue

        if set(stripped) <= {"-", "*", "_"} and len(stripped) >= 3:
            index += 1
            continue

        index, text = _paragraph(lines, index)
        blocks.append(Block(kind=PARAGRAPH, text=text))

    return blocks


def _paragraph(lines: list[str], index: int) -> tuple[int, str]:
    """Gabungkan baris berurutan menjadi satu paragraf, seperti markdown."""
    parts: list[str] = []
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped or _starts_block(stripped):
            break
        parts.append(stripped)
        index += 1
    return index, " ".join(parts)


def _starts_block(stripped: str) -> bool:
    return bool(
        stripped.startswith(("|", "```", ">"))
        or _HEADING.match(stripped)
        or _IMAGE.match(stripped)
        or _BULLET.match(stripped)
        or _NUMBERED.match(stripped)
    )


def _code(lines: list[str], index: int) -> tuple[int, Block]:
    index += 1
    body: list[str] = []
    while index < len(lines) and not lines[index].strip().startswith("```"):
        body.append(lines[index])
        index += 1
    return index + 1, Block(kind=CODE, text="\n".join(body))


def _table(lines: list[str], index: int) -> tuple[int, Block]:
    rows: list[list[str]] = []
    while index < len(lines) and lines[index].strip().startswith("|"):
        stripped = lines[index].strip()
        if not _TABLE_SEPARATOR.match(stripped):
            rows.append([plain(cell) for cell in _split_row(stripped)])
        index += 1
    return index, Block(kind=TABLE, rows=rows)


def _split_row(line: str) -> list[str]:
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    return [cell.strip() for cell in text.split("|")]
