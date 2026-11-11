"""Tes controller fase dan pemuat prompt."""

from __future__ import annotations

import json

import pytest

from swarmfold.evidence import EvidenceStore
from swarmfold.phases import PHASES, PhaseController, PromptLibrary
from swarmfold.runtime import RunPaths

DATASET_HASH = "sha256:abc123"


def _controller(tmp_path) -> tuple[PhaseController, EvidenceStore]:
    paths = RunPaths(root=tmp_path, run_id="2026-11-11-fase").ensure()
    store = EvidenceStore(paths)
    return PhaseController(paths, store), store


def _add(store: EvidenceStore, phase: str, ident: str, **overrides) -> dict:
    entry = {
        "id": ident,
        "statement": "pendapatan kuartal ketiga turun 12,4 persen",
        "value": -0.124,
        "unit": "ratio",
        "cell": 3,
        "artifact": "cells/003.out.txt",
        "dataset_hash": DATASET_HASH,
        "verified": True,
        "confidence": "high",
    }
    entry.update(overrides)
    store.add(phase, entry)
    return entry


def _to_f2(controller: PhaseController) -> None:
    assert controller.advance("F1").ok
    controller.mark_completed("F1")
    assert controller.advance("F2").ok


def _to_f3(controller: PhaseController, store: EvidenceStore) -> None:
    _to_f2(controller)
    _add(store, "F2", "E-001")
    assert controller.advance("F3").ok


def _to_f5(controller: PhaseController, store: EvidenceStore) -> None:
    _to_f3(controller, store)
    _add(store, "F3", "E-002", meta={"residual": 0})
    assert controller.advance("F5").ok


def _to_f6(controller: PhaseController, store: EvidenceStore) -> None:
    _to_f5(controller, store)
    _add(store, "F5", "E-003", meta={"kind": "scenario"})
    assert controller.advance("F6").ok


def _write_f6(store: EvidenceStore, audit_complete: bool) -> None:
    path = store.file_for("F6")
    path.write_text(
        json.dumps({"phase": "F6", "audit_complete": audit_complete, "findings": []}),
        encoding="utf-8",
    )


def test_fresh_controller_allows_only_f1(tmp_path):
    controller, _ = _controller(tmp_path)

    assert controller.current == ""
    assert controller.allowed_targets() == ["F1"]

    blocked = controller.advance("F2")
    assert not blocked.ok
    assert blocked.allowed == ["F1"]


def test_f1_must_be_completed_ok_before_f2(tmp_path):
    controller, _ = _controller(tmp_path)
    assert controller.advance("F1").ok

    blocked = controller.advance("F2")
    assert not blocked.ok
    assert blocked.allowed == []
    assert "F1" in blocked.reason

    controller.mark_completed("F1", ok=False)
    assert not controller.advance("F2").ok

    controller.mark_completed("F1")
    assert controller.is_completed("F1")
    assert controller.allowed_targets() == ["F2"]
    assert controller.advance("F2").ok
    assert controller.current == "F2"


def test_phase_closed_as_not_applicable_is_not_completed(tmp_path):
    controller, _ = _controller(tmp_path)
    assert controller.advance("F1").ok

    controller.mark_completed("F4", ok=False)

    assert controller.is_closed("F4") is True
    assert controller.is_completed("F4") is False


def test_f2_needs_a_verified_finding(tmp_path):
    controller, store = _controller(tmp_path)
    _to_f2(controller)

    blocked = controller.advance("F3")
    assert not blocked.ok
    assert blocked.allowed == []
    assert "F2" in blocked.reason

    _add(store, "F2", "E-001")
    assert controller.allowed_targets() == ["F3", "F4"]
    assert controller.advance("F3").ok


def test_f3_needs_residual_zero(tmp_path):
    controller, store = _controller(tmp_path)
    _to_f3(controller, store)

    # Langkah mundur tetap sah walau prasyarat maju belum terpenuhi.
    assert controller.allowed_targets() == ["F2"]
    assert controller.advance("F2").ok
    assert controller.advance("F3").ok

    blocked = controller.advance("F5")
    assert not blocked.ok
    assert "residual" in blocked.reason

    _add(store, "F3", "E-002", meta={"residual": 0.001})
    blocked = controller.advance("F5")
    assert not blocked.ok
    assert "residual" in blocked.reason

    _add(store, "F3", "E-003", meta={"residual": 0})
    assert controller.allowed_targets() == ["F2", "F4", "F5"]
    assert controller.advance("F5").ok


def test_f5_needs_a_verified_scenario(tmp_path):
    controller, store = _controller(tmp_path)
    _to_f5(controller, store)

    blocked = controller.advance("F6")
    assert not blocked.ok
    assert "skenario" in blocked.reason

    _add(store, "F5", "E-004", meta={"kind": "scenario"}, verified=False)
    assert not controller.advance("F6").ok

    _add(store, "F5", "E-005", meta={"kind": "forecast"})
    assert not controller.advance("F6").ok

    _add(store, "F5", "E-006", meta={"kind": "scenario"})
    assert controller.allowed_targets() == ["F3", "F6"]
    assert controller.advance("F6").ok


def test_f6_needs_audit_complete_before_f7(tmp_path):
    controller, store = _controller(tmp_path)
    _to_f6(controller, store)

    _write_f6(store, audit_complete=False)
    blocked = controller.advance("F7")
    assert not blocked.ok
    assert "audit_complete" in blocked.reason

    _write_f6(store, audit_complete=True)
    assert controller.advance("F7").ok
    assert controller.allowed_targets() == []

    terminal = controller.advance("F3")
    assert not terminal.ok
    assert "terakhir" in terminal.reason


def test_third_return_is_rejected(tmp_path):
    controller, store = _controller(tmp_path)
    _to_f3(controller, store)
    _add(store, "F3", "E-002", meta={"residual": 0})

    assert controller.advance("F2").ok
    assert controller.advance("F3").ok
    assert controller.advance("F2").ok
    assert controller.advance("F3").ok

    blocked = controller.advance("F2")
    assert not blocked.ok
    assert "maksimum 2" in blocked.reason
    assert "F2" in blocked.reason
    assert controller.returns_used("F2") == 2
    assert controller.current == "F3"

    reloaded = PhaseController(controller.paths, store)
    assert reloaded.current == "F3"
    assert reloaded.returns_used("F2") == 2
    assert reloaded.is_completed("F1")


def test_unknown_and_same_phase_are_rejected(tmp_path):
    controller, _ = _controller(tmp_path)

    unknown = controller.advance("F9")
    assert not unknown.ok
    assert "tidak dikenal" in unknown.reason

    assert controller.advance("F1").ok
    same = controller.advance("F1")
    assert not same.ok
    assert "sudah fase aktif" in same.reason
    assert same.allowed == []


def test_state_block_shape(tmp_path):
    block = PromptLibrary().state_block(
        phase="F3",
        cell=27,
        evidence_count=11,
        allowed=["F2", "F4", "F5"],
        phase_completed=["F1", "F2"],
    )

    assert block == (
        "## State\n"
        "phase=F3\n"
        "cells_used=27\n"
        "cells_in_phase=27\n"
        "evidence_total=11\n"
        "evidence_in_phase=11\n"
        "checkpoint_in=0\n"
        "legal_next=F2,F4,F5\n"
        "stalls=0\n"
        "phases_done=F1,F2"
    )
    assert "http" not in block.lower()
    assert str(tmp_path) not in block


def test_default_prompt_library_uses_business_pack():
    library = PromptLibrary()

    assert library.pack == "business"
    assert library.audience == "pemilik usaha kecil"
    assert library.system().strip()


def test_audience_slot_reaches_business_prompts():
    default = PromptLibrary(pack="business")
    assert "pemilik usaha kecil" in default.system()
    assert "pemilik usaha kecil" in default.module("report")

    override = PromptLibrary(
        pack="business", audience="analis laboratorium", domain="laboratorium"
    )
    assert "analis laboratorium" in override.system()
    assert "analis laboratorium" in override.module("report")
    assert "shop" not in override.system()
    assert "shop" not in override.module("report")


def test_generic_pack_overrides_phases_and_falls_back():
    library = PromptLibrary(pack="generic")

    assert library.pack == "generic"
    assert library.audience == "pembaca tanpa latar statistik"
    assert library.domain == "data umum"
    assert "tabular dataset" in library.system()
    assert "small-business" not in library.system()
    assert "pembaca tanpa latar statistik" in library.system()
    assert "What Is in the Data" in library.phase("F2")
    assert "Penantang" in library.phase("F6"), "F6 generik mewarisi prompt dasar"
    assert "Nine sections, in this order" not in library.phase("F7"), (
        "brief F7 tidak boleh mengulang aturan report.md"
    )
    report = library.module("report")
    assert "Apa yang ada di data" in report
    assert "pembaca tanpa latar statistik" in report, "audience pack dirender di report.md"


def test_pack_overrides_files_and_renders_variables(tmp_path):
    base = tmp_path / "prompts"
    (base / "phases").mkdir(parents=True)
    (base / "system.md").write_text("Sistem untuk {{audience}} di {{domain}}.\n", encoding="utf-8")
    pack = base / "packs" / "uji"
    (pack / "phases").mkdir(parents=True)
    (pack / "pack.json").write_text('{"audience": "analis data"}', encoding="utf-8")
    (pack / "phases" / "F2.md").write_text("# F2 untuk {{audience}}\n", encoding="utf-8")

    library = PromptLibrary(base, pack="uji", domain="riset")

    assert library.audience == "analis data"
    assert library.domain == "riset"
    assert library.system() == "Sistem untuk analis data di riset.\n"
    assert library.phase("F2") == "# F2 untuk analis data\n"
    with pytest.raises(FileNotFoundError):
        library.phase("F3")


def test_unknown_pack_is_rejected(tmp_path):
    with pytest.raises(ValueError) as exc:
        PromptLibrary(tmp_path, pack="tidak-ada")

    assert "tidak-ada" in str(exc.value)


def test_prompt_library_loads_and_raises_for_missing(tmp_path):
    library = PromptLibrary()
    assert (library.dir / "system.md").is_file()
    assert library.system().lstrip().startswith("<!--")
    assert "# F4" in library.phase("F4")
    assert library.module("style").strip()

    with pytest.raises(ValueError):
        library.module("../../.env")
    with pytest.raises(ValueError):
        library.phase("F9")

    partial = tmp_path / "prompts"
    partial.mkdir()
    (partial / "system.md").write_text("# System\n", encoding="utf-8")
    sparse = PromptLibrary(partial)
    assert sparse.system() == "# System\n"

    with pytest.raises(FileNotFoundError) as missing_module:
        sparse.module("style")
    assert "style.md" in str(missing_module.value)

    with pytest.raises(FileNotFoundError) as missing_phase:
        sparse.phase("F4")
    assert "F4.md" in str(missing_phase.value)


def test_phases_constant_is_complete():
    assert PHASES == ("F1", "F2", "F3", "F4", "F5", "F6", "F7")
