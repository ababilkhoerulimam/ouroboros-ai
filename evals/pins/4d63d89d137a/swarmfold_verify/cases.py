"""Katalog kasus benchmark dan pembagian split.

`tune` dipakai untuk memilih patch, `heldout` untuk menolak patch yang hanya
menghafal satu dataset, dan `sealed` tidak pernah dipakai seleksi sama sekali.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import generate
from .truth import SPLITS, Case

#: (case_id, split, seed). Enam famili cacat, dua kasus per famili.
CATALOG: tuple[tuple[str, str, int], ...] = (
    ("trend-01", "tune", 11),
    ("simpson-01", "tune", 12),
    ("tail-01", "tune", 13),
    ("join-01", "tune", 14),
    ("missing-01", "tune", 15),
    ("gap-01", "tune", 16),
    ("trend-02", "heldout", 21),
    ("simpson-02", "heldout", 22),
    ("tail-02", "heldout", 23),
    ("join-02", "heldout", 24),
    ("missing-02", "sealed", 31),
    ("gap-02", "sealed", 32),
)


def splits() -> dict[str, list[str]]:
    hasil: dict[str, list[str]] = {split: [] for split in SPLITS}
    for case_id, split, _ in CATALOG:
        hasil[split].append(case_id)
    return hasil


def build_all(root: Path) -> list[dict[str, Any]]:
    """Tulis semua kasus + `splits.json`; kembalikan ringkasan per kasus."""
    ringkasan = []
    for case_id, split, seed in CATALOG:
        generated = generate.build(case_id, split, seed)
        ringkasan.append(generate.write(generated, Path(root)))
    path = Path(root) / "splits.json"
    path.write_text(json.dumps(splits(), indent=2) + "\n", encoding="utf-8")
    return ringkasan


def load_truth(case_id: str, root: Path) -> Case:
    from .truth import load

    return load(Path(root) / "truth" / f"{case_id}.json")


def case_input_dir(case_id: str, root: Path) -> Path:
    return Path(root) / "cases" / case_id / "input"
