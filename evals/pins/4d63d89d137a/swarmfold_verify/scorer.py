"""Skor sebuah run terhadap ground truth yang ditanam.

Penilaian tidak membaca prosa laporan dan tidak memakai model: satu-satunya
bukti adalah `evidence/F*.json`, dan satu-satunya kebenaran adalah `truth.json`
milik kasus. Karena itu skor bisa dihitung ulang dan dibandingkan antar-varian.

Masukan fungsi `score` hanya `run_dir` dan objek `Case`; truth tidak pernah
dibaca dari dalam run tree, sehingga run tidak bisa menyelundupkan jawabannya
sendiri. `sources` mencatat berkas run yang benar-benar dibaca supaya batas itu
bisa diuji.
"""

from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any

from .checks import artifact_path, check_all, load_findings
from .truth import Anchor, Case

SCHEMA = 1
#: Peluang benar yang diklaim tiap tingkat keyakinan, dipakai untuk Brier score.
CONFIDENCE_P = {"high": 0.9, "medium": 0.6, "low": 0.3}
#: Keyakinan tak dikenal dinilai seperti tebakan jujur, bukan seperti keyakinan tinggi.
_UNKNOWN_P = 0.5


def _value(finding: dict[str, Any]) -> float | None:
    value = finding.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _rel_error(value: float, anchor: Anchor) -> float:
    """Galat relatif terhadap besar anchor; anchor nol memakai galat absolut."""
    if anchor.value == 0:
        return abs(value)
    return abs(value - anchor.value) / abs(anchor.value)


def _comparable(finding: dict[str, Any], anchor: Anchor) -> float | None:
    """Nilai finding bila satuannya sama dengan anchor, selain itu `None`."""
    if str(finding.get("unit") or "") != anchor.unit:
        return None
    return _value(finding)


def _pairs(
    findings: list[dict[str, Any]], anchors: tuple[Anchor, ...]
) -> list[tuple[int, Anchor, float]]:
    hasil: list[tuple[int, Anchor, float]] = []
    for index, finding in enumerate(findings):
        for anchor in anchors:
            value = _comparable(finding, anchor)
            if value is not None and anchor.matches(value):
                hasil.append((index, anchor, _rel_error(value, anchor)))
    return hasil


def _contradictions(
    findings: list[dict[str, Any]], anchors: tuple[Anchor, ...], matched: set[str]
) -> list[dict[str, Any]]:
    """Anchor yang tidak ditemukan tetapi justru dibantah dengan tanda terbalik."""
    hasil: list[dict[str, Any]] = []
    for anchor in anchors:
        if anchor.id in matched or anchor.value == 0:
            continue
        for finding in findings:
            value = _comparable(finding, anchor)
            if value is not None and anchor.matches(-value):
                hasil.append(
                    {
                        "anchor": anchor.id,
                        "finding": str(finding.get("id") or ""),
                        "value": value,
                    }
                )
                break
    return hasil


def _numeric_error(findings: list[dict[str, Any]], anchors: tuple[Anchor, ...]) -> dict[str, Any]:
    """Galat relatif pada anchor yang ditemukan, memakai temuan terdekat."""
    per_anchor: list[float] = []
    for anchor in anchors:
        errors = [
            _rel_error(value, anchor)
            for finding in findings
            if (value := _comparable(finding, anchor)) is not None and anchor.matches(value)
        ]
        if errors:
            per_anchor.append(min(errors))
    if not per_anchor:
        return {"median_rel": None, "worst_rel": None, "n": 0}
    return {
        "median_rel": round(statistics.median(per_anchor), 6),
        "worst_rel": round(max(per_anchor), 6),
        "n": len(per_anchor),
    }


def _calibration(findings: list[dict[str, Any]], supported: set[int]) -> dict[str, Any]:
    """Brier score: seberapa jujur `confidence` dibanding hasil pencocokan."""
    if not findings:
        return {"brier": None, "n": 0}
    total = 0.0
    for index, finding in enumerate(findings):
        p = CONFIDENCE_P.get(str(finding.get("confidence") or ""), _UNKNOWN_P)
        outcome = 1.0 if index in supported else 0.0
        total += (p - outcome) ** 2
    return {"brier": round(total / len(findings), 6), "n": len(findings)}


def _duplicate_rate(findings: list[dict[str, Any]]) -> float:
    """Pangsa temuan yang mengulang angka dan satuan yang sudah muncul.

    Bukan guardrail, tetapi dilaporkan: tanpa ini recall bisa dinaikkan hanya
    dengan menyalin satu angka benar berkali-kali.
    """
    seen: set[tuple[str, float]] = set()
    duplicates = 0
    for finding in findings:
        value = _value(finding)
        if value is None:
            continue
        key = (str(finding.get("unit") or ""), round(value, 6))
        if key in seen:
            duplicates += 1
        else:
            seen.add(key)
    return duplicates / len(findings) if findings else 0.0


def _sources(run_dir: Path, findings: list[dict[str, Any]]) -> list[str]:
    """Berkas run yang benar-benar dibaca scorer, sebagai path relatif.

    Artifact ikut dicatat karena `check_evidence` membacanya: tanpa itu,
    invarian "scorer hanya menyentuh run_dir" tidak bisa diuji dari luar.
    """
    root = run_dir.resolve()
    sources = {f"evidence/{path.name}" for path in run_dir.glob("evidence/F*.json")}
    for name in ("laporan.md", "done.json", "status.json"):
        if (run_dir / name).is_file():
            sources.add(name)
    for finding in findings:
        path = artifact_path(run_dir, str(finding.get("artifact") or ""))
        if path is not None:
            sources.add(path.relative_to(root).as_posix())
    return sorted(sources)


def score(run_dir: Path, case: Case) -> dict[str, Any]:
    """Hitung semua metrik untuk satu run terhadap satu kasus.

    `false_discovery` dan `defect_rate` bernilai `None` bila run tidak
    menghasilkan temuan sama sekali: keduanya pecahan dari jumlah temuan, dan
    run kosong tidak boleh terlihat sempurna hanya karena tidak ada yang bisa
    salah. Pemakai skor wajib memperlakukan `None` sebagai terburuk.
    """
    run = Path(run_dir)
    findings = load_findings(run)
    anchors = case.anchors
    pairs = _pairs(findings, anchors)

    matched_anchors = {anchor.id for _, anchor, _ in pairs}
    supported = {index for index, _, _ in pairs}
    contradictions = _contradictions(findings, anchors, matched_anchors)
    defects = check_all(run)

    finding_defects = [item for item in defects if item.get("scope") == "finding"]
    run_defects = [item for item in defects if item.get("scope") != "finding"]
    bad_findings = {str(item.get("subject") or "") for item in finding_defects}

    unmatched = len(findings) - len(supported)
    return {
        "schema": SCHEMA,
        "case_id": case.case_id,
        "split": case.split,
        "n_findings": len(findings),
        "n_anchors": len(anchors),
        "recall": round(len(matched_anchors) / len(anchors), 6) if anchors else 0.0,
        "false_discovery": round(unmatched / len(findings), 6) if findings else None,
        "contradictions": contradictions,
        "numeric_error": _numeric_error(findings, anchors),
        "calibration": _calibration(findings, supported),
        "defect_rate": round(len(bad_findings) / len(findings), 6) if findings else None,
        "duplicate_rate": round(_duplicate_rate(findings), 6),
        "defects": defects,
        "run_defects": run_defects,
        "matched": sorted(matched_anchors),
        "missed": sorted(anchor.id for anchor in anchors if anchor.id not in matched_anchors),
        "sources": _sources(run, findings),
    }
