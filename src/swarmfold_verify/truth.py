"""Skema `truth.json` untuk benchmark ber-ground-truth.

Satu kasus punya beberapa *anchor*: angka yang pasti benar karena ditanam saat
data dibuat. Scorer mencocokkan temuan run ke anchor, bukan ke prosa laporan,
supaya penilaian tidak bergantung pada pilihan kata model.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SPLITS = ("tune", "heldout", "sealed")
KINDS = ("trend", "simpson", "tail", "join", "missing", "gap")


@dataclass(frozen=True)
class Anchor:
    """Angka yang ditanam dan harus ditemukan run."""

    id: str
    kind: str
    value: float
    unit: str
    tol_rel: float
    note: str = ""

    def matches(self, value: float) -> bool:
        """True bila `value` berada dalam toleransi relatif anchor ini."""
        if self.tol_rel <= 0:
            return False
        return abs(value - self.value) <= abs(self.value) * self.tol_rel + 1e-12

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "value": self.value,
            "unit": self.unit,
            "tol_rel": self.tol_rel,
            "note": self.note,
        }


def _anchor(item: dict[str, Any]) -> Anchor:
    """Baca satu anchor, menolak angka yang membuat pencocokan tak berarti.

    `tol_rel` nol membuat anchor tidak pernah cocok, dan `value` yang hilang
    berubah jadi nol sehingga temuan nol apa pun dianggap benar. Keduanya
    kesalahan penulisan truth, bukan hasil analisis yang buruk, jadi ditolak
    di sini alih-alih menjadi skor yang diam-diam salah.
    """
    ident = str(item.get("id") or "")
    if not ident:
        raise ValueError("anchor tanpa id")
    kind = str(item.get("kind") or "")
    if kind not in KINDS:
        raise ValueError(f"{ident}: kind tidak dikenal: {kind!r}; pilih {KINDS}")
    value = item.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{ident}: value wajib angka, bukan {value!r}")
    if not math.isfinite(float(value)):
        raise ValueError(f"{ident}: value harus berhingga, bukan {value!r}")
    tol_rel = item.get("tol_rel")
    if isinstance(tol_rel, bool) or not isinstance(tol_rel, (int, float)):
        raise ValueError(f"{ident}: tol_rel wajib angka, bukan {tol_rel!r}")
    if not math.isfinite(float(tol_rel)) or float(tol_rel) <= 0:
        raise ValueError(f"{ident}: tol_rel harus > 0, bukan {tol_rel!r}")
    unit = str(item.get("unit") or "")
    if not unit:
        raise ValueError(f"{ident}: unit wajib diisi")
    return Anchor(
        id=ident,
        kind=kind,
        value=float(value),
        unit=unit,
        tol_rel=float(tol_rel),
        note=str(item.get("note") or ""),
    )


def _reject_overlap(anchors: tuple[Anchor, ...]) -> None:
    """Dua anchor yang jendela toleransinya bertumpuk tidak bisa dibedakan.

    Satu temuan akan memenuhi keduanya, sehingga recall naik tanpa ada temuan
    tambahan — persis yang membuat skor bisa dimainkan.
    """
    for index, kiri in enumerate(anchors):
        for kanan in anchors[index + 1 :]:
            if kiri.unit != kanan.unit:
                continue
            skala = max(abs(kiri.value), abs(kanan.value), 1.0)
            jendela = max(kiri.tol_rel, kanan.tol_rel) * skala
            if abs(kiri.value - kanan.value) <= jendela:
                raise ValueError(
                    f"anchor {kiri.id} dan {kanan.id} bertumpuk "
                    f"({kiri.value} vs {kanan.value}, jendela {jendela:.6f})"
                )


@dataclass(frozen=True)
class Case:
    case_id: str
    split: str
    seed: int
    anchors: tuple[Anchor, ...]
    defects: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Case:
        case_id = str(data.get("case_id") or "")
        if not case_id:
            raise ValueError("truth tanpa case_id")
        split = str(data.get("split") or "")
        if split not in SPLITS:
            raise ValueError(f"split tidak dikenal: {split!r}; pilih {SPLITS}")
        anchors = tuple(_anchor(item) for item in data.get("anchors") or [])
        _reject_overlap(anchors)
        return cls(
            case_id=case_id,
            split=split,
            seed=int(data.get("seed") or 0),
            anchors=anchors,
            defects=tuple(data.get("defects") or ()),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": 1,
            "case_id": self.case_id,
            "split": self.split,
            "seed": self.seed,
            "anchors": [anchor.as_dict() for anchor in self.anchors],
            "defects": list(self.defects),
        }


def load(path: Path) -> Case:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"truth bukan objek: {path}")
    return Case.from_dict(data)


def write(case: Case, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(case.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path
