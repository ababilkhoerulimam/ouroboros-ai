"""Tes berkas bukti: skema `evidence/F{n}.json` dan pemicu deep-dive."""

from __future__ import annotations

import json

import pytest

from swarmfold.evidence import (
    EvidenceError,
    EvidenceStore,
    deepdive_due,
    next_deepdive_path,
)
from swarmfold.runtime import RunPaths

DATASET_HASH = "sha256:aaa111"


def _paths(tmp_path) -> RunPaths:
    return RunPaths(root=tmp_path, run_id="2026-11-11-test").ensure()


def _store(tmp_path) -> EvidenceStore:
    return EvidenceStore(_paths(tmp_path))


def _cells(*statuses: str, phase: str = "F3") -> dict:
    return {
        "cells": [
            {"n": number, "phase": phase, "intent": "hitung", "status": status}
            for number, status in enumerate(statuses, start=1)
        ]
    }


def _artifact(tmp_path, relative: str, text: str) -> None:
    path = _paths(tmp_path).dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _finding(**overrides) -> dict:
    entry = {
        "id": "E-001",
        "pillar": "fact",
        "statement": "pendapatan Q3 2025 turun 12,4% dibanding Q2 2025",
        "value": -0.124,
        "unit": "ratio",
        "display": "-12,4%",
        "cell": 1,
        "artifact": "cells/001.out.txt",
        "dataset_hash": DATASET_HASH,
        "confidence": "high",
        "verified": True,
    }
    entry.update(overrides)
    return entry


def _ok_setup(tmp_path, text: str = "delta pendapatan -0.124 (-12,4%)\n") -> EvidenceStore:
    _artifact(tmp_path, "cells/001.out.txt", text)
    return _store(tmp_path)


def test_valid_entry_persists_and_reloads(tmp_path):
    store = _ok_setup(tmp_path)
    entry = _finding()
    returned = store.add("F3", entry, question="kenapa pendapatan turun di Q3")

    assert returned["id"] == "E-001"

    data = store.load("F3")
    assert data["phase"] == "F3"
    assert data["question"] == "kenapa pendapatan turun di Q3"
    assert data["findings"] == [entry]
    assert data["hypotheses"] == []
    assert data["anomalies"] == []
    assert data["cannot_answer"] == []

    # question lama dipertahankan saat entri berikutnya menambah tanpa question
    store.add("F3", _finding(id="E-002", value=3320, unit="count", display="3.320 pesanan"))
    assert store.load("F3")["question"] == "kenapa pendapatan turun di Q3"
    assert [f["id"] for f in store.load("F3")["findings"]] == ["E-001", "E-002"]


def test_missing_artifact_is_reported(tmp_path):
    store = _store(tmp_path)
    store.add("F3", _finding())

    errors = store.validate("F3", cells_index=_cells("ok"), dataset_hash=DATASET_HASH)

    assert any("cells/001.out.txt" in message for message in errors)


def test_artifact_without_display_is_reported(tmp_path):
    store = _ok_setup(tmp_path, text="total pendapatan 5.000.000\n")
    store.add("F3", _finding(value=0.124, display="12,4%"))

    errors = store.validate("F3", cells_index=_cells("ok"), dataset_hash=DATASET_HASH)

    assert len(errors) == 1
    assert "cells/001.out.txt" in errors[0]
    assert "12,4%" in errors[0]


def test_numeric_artifact_rendering_is_accepted(tmp_path):
    # CONTRACTS.md §4: artefak harus memuat `display` **atau nilai numerik
    # setara**. Cell mencetak `key=value` gaya Python (-0.124), `display` memakai
    # bentuk Indonesia (-12,4%); keduanya angka yang sama.
    store = _ok_setup(tmp_path, text="revenue_q3=-0.124\n")
    store.add("F3", _finding(display="-12,4%"))

    assert store.validate("F3", cells_index=_cells("ok"), dataset_hash=DATASET_HASH) == []


def test_rupiah_display_matches_raw_integer_rendering(tmp_path):
    # Bentuk yang muncul di run 2026-11-11-eec3dc: `Rp 19.204.513` untuk
    # `range_spread=19204513`.
    store = _ok_setup(tmp_path, text="anchor=251212191 | range_spread=19204513\n")
    store.add(
        "F3",
        _finding(value=19204513, unit="IDR", display="Rp 19.204.513"),
    )

    assert store.validate("F3", cells_index=_cells("ok"), dataset_hash=DATASET_HASH) == []


def test_rounded_display_matches_printed_ratio(tmp_path):
    # `-8,62%` adalah bentuk terbulatkan dari p50=-0.086196.
    store = _ok_setup(tmp_path, text="n=2 | p50=-0.086196\n")
    store.add("F3", _finding(value=-0.086196, display="-8,62%"))

    assert store.validate("F3", cells_index=_cells("ok"), dataset_hash=DATASET_HASH) == []


def test_display_number_absent_from_artifact_is_rejected(tmp_path):
    # Angka yang tidak pernah dicetak tetap ditolak, walau formatnya benar.
    store = _ok_setup(tmp_path, text="anchor=251212191\n")
    store.add("F3", _finding(value=19204513, unit="IDR", display="Rp 19.204.513"))

    errors = store.validate("F3", cells_index=_cells("ok"), dataset_hash=DATASET_HASH)

    assert len(errors) == 1
    assert "Rp 19.204.513" in errors[0]


def test_artifact_must_be_the_cited_cell_output(tmp_path):
    # Berkas yang ditulis model sendiri (notes/x.txt) tidak boleh jadi artifact.
    store = _ok_setup(tmp_path)
    _artifact(tmp_path, "notes/x.txt", "delta -12,4%\n")
    store.add("F3", _finding(artifact="notes/x.txt"))

    errors = store.validate("F3", cells_index=_cells("ok"), dataset_hash=DATASET_HASH)

    assert len(errors) == 1
    assert "notes/x.txt" in errors[0]
    assert "cells/001.out.txt" in errors[0]


def test_artifact_backslash_path_is_normalised(tmp_path):
    store = _ok_setup(tmp_path)
    store.add("F3", _finding(artifact="cells\\001.out.txt"))

    assert store.validate("F3", cells_index=_cells("ok"), dataset_hash=DATASET_HASH) == []


def test_display_substring_of_longer_number_is_rejected(tmp_path):
    # `display: "3"` tidak boleh cocok dengan `rows=13`.
    store = _ok_setup(tmp_path, text="rows=13\n")
    store.add("F3", _finding(value=3, unit="count", display="3"))

    errors = store.validate("F3", cells_index=_cells("ok"), dataset_hash=DATASET_HASH)

    assert len(errors) == 1
    assert "display '3'" in errors[0]


def test_cell_from_another_phase_is_rejected(tmp_path):
    store = _ok_setup(tmp_path)
    store.add("F3", _finding())

    errors = store.validate(
        "F3", cells_index=_cells("ok", phase="F2"), dataset_hash=DATASET_HASH
    )

    assert len(errors) == 1
    assert "F2" in errors[0]
    assert "F3" in errors[0]


def test_composite_hash_tracks_every_data_file(tmp_path):
    paths = _paths(tmp_path)
    store = EvidenceStore(paths)
    (paths.data_dir / "a.csv").write_text("a\n1\n", encoding="utf-8")
    first = store.composite_hash()

    (paths.data_dir / "b.csv").write_text("b\n1\n", encoding="utf-8")
    second = store.composite_hash()
    assert second != first

    (paths.data_dir / "b.csv").write_text("b\n2\n", encoding="utf-8")
    assert store.composite_hash() != second


def test_string_value_is_rejected(tmp_path):
    store = _ok_setup(tmp_path)

    with pytest.raises(EvidenceError, match="value"):
        store.add("F3", _finding(value="-0.124"))

    assert store.load("F3")["findings"] == []


def test_duplicate_id_across_phases_is_rejected(tmp_path):
    store = _ok_setup(tmp_path)
    store.add("F3", _finding())

    with pytest.raises(EvidenceError, match="E-001"):
        store.add("F2", _finding())

    assert store.load("F2")["findings"] == []


def test_cell_not_ok_is_reported(tmp_path):
    store = _ok_setup(tmp_path)
    store.add("F3", _finding())

    errors = store.validate("F3", cells_index=_cells("error"), dataset_hash=DATASET_HASH)

    assert len(errors) == 1
    assert "E-001" in errors[0]
    assert "cell 1" in errors[0]


def test_dataset_hash_mismatch_is_reported(tmp_path):
    store = _ok_setup(tmp_path)
    store.add("F3", _finding())

    errors = store.validate("F3", cells_index=_cells("ok"), dataset_hash="sha256:bbb222")

    assert len(errors) == 1
    assert "dataset_hash" in errors[0]


def test_set_verified_false_keeps_entry_and_drops_count(tmp_path):
    store = _ok_setup(tmp_path)
    store.add("F3", _finding())
    assert store.count("F3") == 1
    assert store.count() == 1

    entry = store.set_verified("F3", "E-001", False)

    assert entry["verified"] is False
    findings = store.load("F3")["findings"]
    assert len(findings) == 1
    assert findings[0]["id"] == "E-001"
    assert store.count("F3") == 0
    assert store.count() == 0


def test_set_verified_unknown_id_raises(tmp_path):
    store = _ok_setup(tmp_path)

    with pytest.raises(EvidenceError, match="E-404"):
        store.set_verified("F3", "E-404", False)


def test_deepdive_due():
    common = {"stall_limit": 3, "every": 10}

    assert deepdive_due(cells_since_checkpoint=10, stall_streak=0, **common) == "every"
    assert deepdive_due(cells_since_checkpoint=9, stall_streak=0, **common) is None
    assert deepdive_due(cells_since_checkpoint=2, stall_streak=3, **common) == "stall"
    # stagnasi menang atas jadwal
    assert deepdive_due(cells_since_checkpoint=10, stall_streak=3, **common) == "stall"


def test_next_deepdive_path_increments(tmp_path):
    paths = _paths(tmp_path)

    first = next_deepdive_path(paths)
    assert first.name == "01.json"

    first.parent.mkdir(parents=True, exist_ok=True)
    first.write_text(json.dumps({"decision": "continue"}), encoding="utf-8")

    assert next_deepdive_path(paths).name == "02.json"


def test_validate_all_prefixes_phase(tmp_path):
    store = _store(tmp_path)
    store.add("F3", _finding())

    errors = store.validate_all(cells_index=_cells("ok"), dataset_hash=DATASET_HASH)

    assert len(errors) == 1
    assert errors[0].startswith("F3: ")


def test_point_display_matches_pp_suffix_rendering(tmp_path):
    # Cell mencetak `vol_pct_points=-8.70pp`; display menulis
    # `-8,70 poin persentase`. Satuan yang menempel pada angka tidak boleh
    # membuat angka itu dianggap bagian dari identifier.
    store = _ok_setup(tmp_path, text="vol_pct_points=-8.70pp\n")
    store.add("F3", _finding(value=-8.7, unit="pp", display="-8,70 poin persentase"))

    assert store.validate("F3", cells_index=_cells("ok"), dataset_hash=DATASET_HASH) == []


def test_number_inside_identifier_is_not_counted(tmp_path):
    # `sku_induk_3m=816449942` tidak boleh menyediakan angka 3 untuk `value: 3`.
    store = _ok_setup(tmp_path, text="sku_induk_3m=816449942\n")
    store.add("F3", _finding(value=3, unit="count", display="3 produk"))

    errors = store.validate("F3", cells_index=_cells("ok"), dataset_hash=DATASET_HASH)

    assert len(errors) == 1


def test_rounded_rupiah_display_matches_decimal_rendering(tmp_path):
    # `Rp 272.149.981` adalah pembulatan dari `avg_sales_baseline=272149980.7`.
    store = _ok_setup(tmp_path, text="avg_sales_baseline=272149980.7\n")
    store.add(
        "F3",
        _finding(value=272149981, unit="IDR", display="Rp 272.149.981/bulan"),
    )

    assert store.validate("F3", cells_index=_cells("ok"), dataset_hash=DATASET_HASH) == []


def test_next_ids_counts_every_phase(tmp_path):
    store = _ok_setup(tmp_path)
    store.add("F2", _finding(id="E-001", cell=1))
    store.add("F3", _finding(id="E-002", cell=1))
    store.add("F2", {"id": "H-001", "pillar": "hypothesis", "statement": "kenaikan musiman", "status": "unresolved", "value": 1, "unit": "count", "display": "1", "cell": 1, "artifact": "cells/001.out.txt", "dataset_hash": DATASET_HASH, "confidence": "low", "verified": False})

    # E-002 sudah dipakai di F3, H-001 sudah dipakai di F2: nomor bebasnya 3 dan 2.
    assert store.next_ids() == (3, 2)


def test_scientific_notation_artifact_matches_value(tmp_path):
    # Cell 014 pada run 2026-11-11-ecd0b9 mencetak `-1.378457e+07` dari
    # pandas, sementara model menulis value -13784572. Selisihnya derau
    # representasi, bukan angka yang berbeda.
    store = _ok_setup(tmp_path, text="diff_aug_vs_avg=-1.378457e+07\n")
    store.add(
        "F3",
        _finding(value=-13784572, unit="IDR", display="-Rp 13,78 juta (-57,04%)"),
    )

    assert store.validate("F3", cells_index=_cells("ok"), dataset_hash=DATASET_HASH) == []


def test_wrong_value_is_still_rejected(tmp_path):
    # Toleransi pembulatan setengah digit tidak boleh meloloskan angka lain.
    store = _ok_setup(tmp_path, text="value=7\n")
    store.add("F3", _finding(value=3, unit="count", display="3 pesanan"))

    errors = store.validate("F3", cells_index=_cells("ok"), dataset_hash=DATASET_HASH)

    assert len(errors) == 1
