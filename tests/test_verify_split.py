"""Tes pembagian kasus dan replikasi.

Aturan yang dijaga: `sealed` tidak pernah bisa dipilih lewat API, setiap kasus
hanya ada di satu split, dan `splits.json` tidak boleh berbeda dari `split`
yang tertulis di truth masing-masing kasus.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarmfold_verify import cases, split


@pytest.fixture
def root(tmp_path: Path) -> Path:
    cases.build_all(tmp_path)
    return tmp_path


def test_load_matches_catalog(root: Path) -> None:
    assert split.load(root) == cases.splits()


def test_sealed_never_selected(root: Path) -> None:
    with pytest.raises(split.SplitError, match="sealed"):
        split.cases_for(root, "sealed")


def test_unknown_split_rejected(root: Path) -> None:
    with pytest.raises(split.SplitError, match="tidak dikenal"):
        split.cases_for(root, "validasi")


def test_tune_and_heldout_are_selectable(root: Path) -> None:
    assert split.cases_for(root, "tune") == cases.splits()["tune"]
    assert split.cases_for(root, "heldout") == cases.splits()["heldout"]


def test_expand_three_replicas(root: Path) -> None:
    hasil = split.expand(["trend-01", "gap-01"], 3)

    assert len(hasil) == 6
    assert hasil[:3] == [("trend-01", 0), ("trend-01", 1), ("trend-01", 2)]


def test_expand_rejects_zero_replicas(root: Path) -> None:
    with pytest.raises(split.SplitError):
        split.expand(["trend-01"], 0)


def test_missing_splits_file(tmp_path: Path) -> None:
    with pytest.raises(split.SplitError, match="build"):
        split.load(tmp_path)


def test_case_in_two_splits_rejected(root: Path) -> None:
    path = root / split.SPLITS_FILE
    data = json.loads(path.read_text(encoding="utf-8"))
    data["heldout"].append(data["tune"][0])
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(split.SplitError, match="dua split"):
        split.load(root)


def test_verify_clean_fixtures(root: Path) -> None:
    assert split.verify(root) == []


def test_verify_flags_mismatched_truth(root: Path) -> None:
    path = root / "truth" / "trend-01.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["split"] = "heldout"
    path.write_text(json.dumps(data), encoding="utf-8")

    assert split.verify(root) == ["trend-01: terdaftar di tune, truth menulis heldout"]


def test_verify_flags_truth_without_split(root: Path) -> None:
    path = root / "truth" / "trend-02.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    (root / "truth" / "yatim.json").write_text(json.dumps(data), encoding="utf-8")

    assert "yatim: truth tanpa split" in split.verify(root)
