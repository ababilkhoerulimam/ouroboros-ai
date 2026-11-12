"""Tes ledger varian.

Ledger adalah satu-satunya catatan mengapa sebuah varian dipromosikan, jadi
dua sifat yang diuji di sini menentukan nilainya: baris lama tidak pernah
berubah, dan setiap perubahan isi memutus rantai hash.
"""

from __future__ import annotations

import json
from pathlib import Path

from swarmfold_eval import ledger


def _entry(**ubah: object) -> dict:
    dasar = {
        "variant_id": "v001",
        "parent": "base",
        "hypothesis": "aturan rasio sebagai persen menaikkan recall",
        "layer": "prompt",
        "files": ["prompts/evidence.md"],
        "diff_sha": "sha256:abc",
        "expected": "recall naik >= 0.10",
        "split": "tune",
        "replicas": 3,
        "before": {"recall": [0.4, 0.42, 0.41]},
        "after": {"recall": [0.55, 0.6, 0.58]},
        "heldout": {"recall": [0.5, 0.52]},
        "verdict": "promoted",
        "branch": "eval/v001",
        "run_ids": ["run-1", "run-2"],
    }
    dasar.update(ubah)
    return dasar


def test_first_row_links_to_genesis(tmp_path: Path) -> None:
    path = tmp_path / ledger.LEDGER_FILE
    row = ledger.record(path, _entry())

    assert row["seq"] == 1
    assert row["prev_sha"] == ledger.GENESIS
    assert ledger.verify_chain(path) == []


def test_prev_sha_links_to_previous_row(tmp_path: Path) -> None:
    path = tmp_path / ledger.LEDGER_FILE
    pertama = ledger.record(path, _entry())
    kedua = ledger.record(path, _entry(variant_id="v002"))

    assert kedua["prev_sha"] == pertama["_sha"]
    assert [row["seq"] for row in ledger.read(path)] == [1, 2]


def test_append_only_preserves_first_line(tmp_path: Path) -> None:
    path = tmp_path / ledger.LEDGER_FILE
    ledger.record(path, _entry())
    sebelum = path.read_text(encoding="utf-8").splitlines()[0]

    ledger.record(path, _entry(variant_id="v002"))
    ledger.record(path, _entry(variant_id="v003"))

    assert path.read_text(encoding="utf-8").splitlines()[0] == sebelum


def test_chain_detects_edit(tmp_path: Path) -> None:
    path = tmp_path / ledger.LEDGER_FILE
    ledger.record(path, _entry())
    ledger.record(path, _entry(variant_id="v002"))

    baris = path.read_text(encoding="utf-8").splitlines()
    data = json.loads(baris[0])
    data["verdict"] = "rejected"
    baris[0] = json.dumps(data, ensure_ascii=False, sort_keys=True)
    path.write_text("\n".join(baris) + "\n", encoding="utf-8")

    assert any("berubah sejak ditulis" in item for item in ledger.verify_chain(path))


def test_chain_detects_rehashed_edit(tmp_path: Path) -> None:
    """Menyunting isi lalu menghitung ulang `_sha` tetap memutus baris berikutnya."""
    path = tmp_path / ledger.LEDGER_FILE
    ledger.record(path, _entry())
    ledger.record(path, _entry(variant_id="v002"))

    baris = path.read_text(encoding="utf-8").splitlines()
    data = json.loads(baris[0])
    data["verdict"] = "rejected"
    data["_sha"] = ledger._sha({k: v for k, v in data.items() if k != "_sha"})
    baris[0] = json.dumps(data, ensure_ascii=False, sort_keys=True)
    path.write_text("\n".join(baris) + "\n", encoding="utf-8")

    assert ledger.verify_chain(path) == ["baris 2: prev_sha tidak cocok"]


def test_chain_detects_deleted_row(tmp_path: Path) -> None:
    path = tmp_path / ledger.LEDGER_FILE
    ledger.record(path, _entry())
    ledger.record(path, _entry(variant_id="v002"))
    ledger.record(path, _entry(variant_id="v003"))

    baris = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join([baris[0], baris[2]]) + "\n", encoding="utf-8")

    assert any("seq" in item for item in ledger.verify_chain(path))


def test_record_without_expected_is_schema_rejected(tmp_path: Path) -> None:
    path = tmp_path / ledger.LEDGER_FILE
    entry = _entry()
    del entry["expected"]

    row = ledger.record(path, entry)

    assert row["verdict"] == "schema_rejected"
    assert any("expected" in item for item in row["errors"])
    assert ledger.last(path) == row


def test_record_with_unknown_verdict_is_schema_rejected(tmp_path: Path) -> None:
    row = ledger.record(tmp_path / ledger.LEDGER_FILE, _entry(verdict="menang"))

    assert row["verdict"] == "schema_rejected"
    assert any("verdict" in item for item in row["errors"])


def test_record_with_zero_replicas_is_schema_rejected(tmp_path: Path) -> None:
    row = ledger.record(tmp_path / ledger.LEDGER_FILE, _entry(replicas=0))

    assert row["verdict"] == "schema_rejected"


def test_last_of_empty_ledger_is_none(tmp_path: Path) -> None:
    assert ledger.last(tmp_path / "belum-ada.jsonl") is None
