"""Tes generator kasus dan skema truth.

Yang dijaga di sini: kasus deterministik per seed, truth tidak bisa melenceng
dari CSV karena anchor dihitung dari data yang ditulis, dan split tidak
memakai kasus yang sama dua kali.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from swarmfold_verify import cases, generate
from swarmfold_verify.truth import KINDS, SPLITS, load

KIND_IDS = {
    "trend": "trend-01",
    "simpson": "simpson-01",
    "tail": "tail-01",
    "join": "join-01",
    "missing": "missing-01",
    "gap": "gap-01",
}


def _csv_rows(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle))


@pytest.mark.parametrize("kind", KINDS)
def test_generator_deterministic(kind: str) -> None:
    case_id = KIND_IDS[kind]
    pertama = generate.build(case_id, "tune", 7)
    kedua = generate.build(case_id, "tune", 7)
    assert pertama.case.as_dict() == kedua.case.as_dict()
    assert pertama.files == kedua.files


@pytest.mark.parametrize("kind", KINDS)
def test_seed_changes_data(kind: str) -> None:
    case_id = KIND_IDS[kind]
    assert generate.build(case_id, "tune", 7).files != generate.build(case_id, "tune", 8).files


def test_truth_matches_generated_total(tmp_path: Path) -> None:
    generate.write(generate.build("trend-01", "tune", 11), tmp_path)
    rows = _csv_rows(tmp_path / "cases" / "trend-01" / "input" / "penjualan.csv")
    total_2024 = sum(int(total) for bulan, total in rows[1:13] if bulan.startswith("2024"))
    truth = load(tmp_path / "truth" / "trend-01.json")
    n1 = next(anchor for anchor in truth.anchors if anchor.id == "N1")
    assert n1.matches(total_2024)
    assert n1.unit == "count"


def test_write_puts_truth_outside_input(tmp_path: Path) -> None:
    generate.write(generate.build("simpson-01", "tune", 12), tmp_path)
    case_dir = tmp_path / "cases" / "simpson-01"
    assert (case_dir / "input" / "klaim.csv").is_file()
    assert not list((case_dir / "input").glob("*truth*"))
    assert (tmp_path / "truth" / "simpson-01.json").is_file()


def test_truth_round_trip(tmp_path: Path) -> None:
    asli = generate.build("tail-01", "tune", 13).case
    path = tmp_path / "truth.json"
    path.write_text(json.dumps(asli.as_dict(), ensure_ascii=False), encoding="utf-8")
    assert load(path).as_dict() == asli.as_dict()


def test_truth_rejects_unknown_split(tmp_path: Path) -> None:
    path = tmp_path / "truth.json"
    path.write_text(json.dumps({"case_id": "x", "split": "validasi"}), encoding="utf-8")
    with pytest.raises(ValueError):
        load(path)


def test_truth_rejects_missing_tolerance(tmp_path: Path) -> None:
    """Tanpa `tol_rel`, anchor tak pernah cocok dan recall mentok tanpa sebab."""
    path = tmp_path / "truth.json"
    path.write_text(
        json.dumps(
            {
                "case_id": "x",
                "split": "tune",
                "anchors": [{"id": "P1", "kind": "trend", "value": 0.08, "unit": "ratio"}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="tol_rel"):
        load(path)


def test_truth_rejects_missing_value(tmp_path: Path) -> None:
    """`value` hilang tidak boleh diam-diam jadi nol dan cocok dengan apa pun."""
    path = tmp_path / "truth.json"
    path.write_text(
        json.dumps(
            {
                "case_id": "x",
                "split": "tune",
                "anchors": [{"id": "P1", "kind": "trend", "unit": "ratio", "tol_rel": 0.01}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="value"):
        load(path)


def test_truth_rejects_overlapping_anchors(tmp_path: Path) -> None:
    path = tmp_path / "truth.json"
    path.write_text(
        json.dumps(
            {
                "case_id": "x",
                "split": "tune",
                "anchors": [
                    {"id": "P1", "kind": "gap", "value": 1, "unit": "count", "tol_rel": 0.5},
                    {"id": "P2", "kind": "gap", "value": 1, "unit": "count", "tol_rel": 0.5},
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="bertumpuk"):
        load(path)


def test_anchor_matches_respects_tolerance() -> None:
    anchor = generate.build("tail-01", "tune", 13).case.anchors[0]
    assert anchor.matches(anchor.value)
    assert anchor.matches(anchor.value * (1 + anchor.tol_rel / 2))
    assert not anchor.matches(anchor.value * (1 + anchor.tol_rel * 10))


def test_catalog_splits_are_disjoint() -> None:
    pembagian = cases.splits()
    assert set(pembagian) == set(SPLITS)
    semua = [case_id for daftar in pembagian.values() for case_id in daftar]
    assert len(semua) == len(set(semua))
    assert set(semua) == {case_id for case_id, _, _ in cases.CATALOG}
    assert pembagian["sealed"]


def test_build_all_writes_every_case(tmp_path: Path) -> None:
    ringkasan = cases.build_all(tmp_path)
    assert len(ringkasan) == len(cases.CATALOG)
    for item in ringkasan:
        assert Path(item["truth"]).is_file()
        assert item["anchors"] >= 2
        assert cases.case_input_dir(item["case_id"], tmp_path).is_dir()
    splits = json.loads((tmp_path / "splits.json").read_text(encoding="utf-8"))
    assert splits == cases.splits()
