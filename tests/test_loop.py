from __future__ import annotations

import json
from dataclasses import replace

from conftest import ScriptedModel, empty_turn, finish, run_cell, tool_turn
from synthetic import tulis_catatan, tulis_pengukuran

from swarmfold.ingest import ingest
from swarmfold.loop import AgentLoop, Brief
from swarmfold.runtime import RunPaths, read_json


def _deepdive_payload() -> dict:
    return {
        "checkpoint": 1,
        "after_cell": 10,
        "trigger": "every_10",
        "reconstruction": [
            {"cell": 10, "intent": "coba satu angka", "numbers": ["10"], "status": "established"}
        ],
        "candidates": [],
        "decision": "continue",
        "next_intent": "lanjut ke fase berikutnya",
        "cap_cells": 3,
        "contested": [],
        "not_proposed": [],
    }


def test_deepdive_fires_at_tenth_cell(run: RunPaths, settings) -> None:
    turns = [tool_turn(run_cell(f"print({n})")) for n in range(1, 11)]
    turns.append(
        tool_turn(
            (
                "write_file",
                {
                    "path": "evidence/deepdive/01.json",
                    "content": json.dumps(_deepdive_payload()),
                },
            )
        )
    )
    turns.append(tool_turn(finish("partial", "uji deep-dive")))

    model = ScriptedModel(turns)
    loop = AgentLoop(run, settings, model, Brief())
    outcome = loop.run()

    deepdive = run.deepdive_dir / "01.json"
    assert deepdive.exists(), "deep-dive tidak terpicu di cell ke-10"
    payload = json.loads(deepdive.read_text(encoding="utf-8"))
    assert payload["decision"] in {"continue", "insert", "pivot"}
    assert loop.checkpoint_pending is None
    assert outcome.cells == 10


def test_finish_before_f7_forces_writer(run: RunPaths, settings) -> None:
    model = ScriptedModel([tool_turn(finish("ok", "selesai cepat"))])
    loop = AgentLoop(run, settings, model, Brief())
    outcome = loop.run()
    assert loop.controller.current == "F7"
    done = read_json(run.done_file)
    assert done is not None
    assert outcome.status in {"ok", "partial"}


def test_state_block_is_replaced_not_appended(run: RunPaths, settings) -> None:
    class Capturing(ScriptedModel):
        def __init__(self) -> None:
            super().__init__([tool_turn(run_cell(f"print({n})")) for n in range(1, 5)])
            self.state_counts: list[int] = []

        def chat(self, messages, tools=None):
            self.state_counts.append(
                sum(
                    1
                    for message in messages
                    if str(message.get("content", "")).startswith("## State")
                )
            )
            return super().chat(messages, tools)

    model = Capturing()
    loop = AgentLoop(run, settings, model, Brief())
    loop.run()

    assert model.state_counts, "model tidak pernah dipanggil"
    assert max(model.state_counts) == 1, "blok state menumpuk tiap turn"


def test_report_rules_load_only_in_f7(run: RunPaths, settings) -> None:
    loop = AgentLoop(run, settings, ScriptedModel([]), Brief())

    loop.controller.force("F6")
    assert "You are not analysing anything" not in loop._state_text()

    loop.controller.force("F7")
    text = loop._state_text()
    assert "You are not analysing anything" in text, "report.md harus ikut dimuat di F7"
    assert text.count("Nine sections, in this order") == 1, "struktur laporan tidak boleh dobel"


def test_validator_rejects_evidence_without_artifact(run: RunPaths, settings) -> None:
    bad = {
        "phase": "F1",
        "question": "apakah data layak",
        "findings": [
            {
                "id": "E-001",
                "pillar": "fact",
                "statement": "terdapat 4 baris pada data penjualan",
                "value": 4,
                "unit": "count",
                "display": "4 baris",
                "cell": 1,
                "artifact": "cells/001.out.txt",
                "dataset_hash": "salah",
                "confidence": "high",
                "verified": True,
            }
        ],
        "hypotheses": [],
        "anomalies": [],
        "cannot_answer": [],
    }
    turns = [
        tool_turn(run_cell("print(4)", "hitung baris")),
        tool_turn(
            (
                "write_file",
                {"path": "evidence/F1.json", "content": json.dumps(bad)},
            )
        ),
        tool_turn(finish("ok", "uji validator")),
    ]
    loop = AgentLoop(run, settings, ScriptedModel(turns), Brief())
    outcome = loop.run()
    done = read_json(run.done_file)
    assert done is not None
    assert outcome.status == "failed", "validasi gagal harus menolak publish"
    assert done["status"] == "failed"
    assert done["verification"]["mismatches"], "masalah validasi harus tercatat"
    assert any("evidence" in error for error in outcome.errors)
    status = read_json(run.status_file)
    assert status["warnings"], "validator harus menulis peringatan ke status.json"


def test_model_without_tool_calls_is_nudged_then_fails(run: RunPaths, settings) -> None:
    prose = tool_turn(finish("ok", "x"))
    prose.tool_calls = []
    model = ScriptedModel([prose, prose, prose, prose])
    loop = AgentLoop(run, settings, model, Brief())
    outcome = loop.run()
    assert any("tanpa memanggil tool" in error for error in outcome.errors)


class SelaluRunCell:
    """Model yang terus meminta run_cell walau permintaannya sudah ditolak."""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages: list[dict], tools: list[dict] | None = None):
        self.calls += 1
        return tool_turn(run_cell("print(1)"))


def test_runaway_loop_is_stopped(run: RunPaths, settings) -> None:
    model = SelaluRunCell()
    loop = AgentLoop(run, replace(settings, max_cells=1), model, Brief())
    outcome = loop.run()

    assert model.calls <= 10, "loop harus berhenti, bukan berputar tanpa batas"
    assert any("tidak membuat kemajuan" in error for error in outcome.errors)
    assert read_json(run.done_file) is not None


def test_data_mutation_is_fatal(run: RunPaths, settings) -> None:
    data_file = next(run.data_dir.iterdir())
    data_file.chmod(0o666)
    turns = [
        tool_turn(run_cell(f"open({str(data_file)!r}, 'a').write('x')", "tambah data"))
    ]
    loop = AgentLoop(run, settings, ScriptedModel(turns), Brief())
    outcome = loop.run()

    assert outcome.status == "failed"
    assert any("data/" in error for error in outcome.errors)
    index = json.loads((run.cells_dir / "index.json").read_text(encoding="utf-8"))
    assert [cell["n"] for cell in index["cells"]] == [1]


def test_status_records_composite_dataset_hash(run: RunPaths, settings) -> None:
    model = ScriptedModel([tool_turn(finish("partial", "cukup"))])
    loop = AgentLoop(run, settings, model, Brief())
    loop.run()

    status = read_json(run.status_file)
    assert status["dataset_hash"] == loop.dataset_hash
    assert len(loop.dataset_hash) == 64


def _run_dari(tmp_path, settings, sources: list, run_id: str) -> RunPaths:
    paths = RunPaths(settings.data_root, run_id).ensure()
    ingest(sources, paths)
    return paths


def test_business_profile_records_full_mode(run: RunPaths, settings) -> None:
    model = ScriptedModel([tool_turn(finish("blocked", "uji triage"))])
    loop = AgentLoop(run, settings, model, Brief())
    loop.run()

    assert loop.mode == "full"
    assert loop.pack == "business"
    assert read_json(run.profile_file)["triage"]["mode"] == "full"
    assert read_json(run.profile_file)["triage"]["pack"] == "business"
    assert read_json(run.status_file)["mode"] == "full"
    assert read_json(run.status_file)["pack"] == "business"


def test_generic_data_selects_generic_pack(tmp_path, settings) -> None:
    class Capturing(ScriptedModel):
        def __init__(self) -> None:
            super().__init__([tool_turn(finish("blocked", "uji pack"))])
            self.seen: list[dict] = []

        def chat(self, messages, tools=None):
            self.seen = list(messages)
            return super().chat(messages, tools)

    paths = _run_dari(
        tmp_path, settings, [tulis_pengukuran(tmp_path / "ukur.csv")], "2026-01-01-ukur"
    )
    model = Capturing()
    loop = AgentLoop(paths, settings, model, Brief())
    loop.run()

    assert loop.mode == "full"
    assert loop.pack == "generic"
    assert loop.prompts.audience == "pembaca tanpa latar statistik"
    assert read_json(paths.profile_file)["triage"]["pack"] == "generic"
    assert read_json(paths.status_file)["pack"] == "generic"
    assert read_json(paths.done_file)["pack"] == "generic"
    system = model.seen[0]["content"]
    assert "tabular dataset" in system
    assert "small-business" not in system


def test_generic_pack_keeps_operator_persona(tmp_path, settings) -> None:
    paths = _run_dari(
        tmp_path, settings, [tulis_pengukuran(tmp_path / "ukur.csv")], "2026-01-01-persona"
    )
    custom = replace(settings, audience="analis laboratorium", domain="laboratorium")
    loop = AgentLoop(
        paths, custom, ScriptedModel([tool_turn(finish("blocked", "uji"))]), Brief()
    )
    loop.run()

    assert loop.pack == "generic"
    assert loop.prompts.audience == "analis laboratorium"
    assert loop.prompts.domain == "laboratorium"


def test_forced_pack_wins_over_triage(tmp_path, settings) -> None:
    paths = _run_dari(
        tmp_path, settings, [tulis_pengukuran(tmp_path / "ukur.csv")], "2026-01-01-paksa"
    )
    forced = replace(settings, pack="business", pack_forced=True)
    loop = AgentLoop(
        paths, forced, ScriptedModel([tool_turn(finish("blocked", "uji"))]), Brief()
    )
    loop.run()

    assert loop.pack == "business"
    assert read_json(paths.done_file)["pack"] == "business"


def test_cleaning_mode_stops_after_f1(tmp_path, settings) -> None:
    paths = _run_dari(
        tmp_path, settings, [tulis_catatan(tmp_path / "catatan.csv")], "2026-01-01-bersih"
    )
    turns = [
        tool_turn(run_cell("print(1)", "rapikan data")),
        tool_turn(("advance_phase", {"target": "F2", "reason": "F1 selesai"})),
    ]
    loop = AgentLoop(paths, settings, ScriptedModel(turns), Brief())
    outcome = loop.run()

    assert loop.mode == "cleaning_only"
    assert loop.controller.current == "F7", "mode cleaning harus melompat ke F7"
    assert outcome.cells == 1, "F2 tidak boleh menjalankan cell"
    done = read_json(paths.done_file)
    assert done["mode"] == "cleaning_only"
    assert "F2" not in done["phases_completed"]


def test_insufficient_data_writes_report_without_model(tmp_path, settings) -> None:
    source = tmp_path / "mini.csv"
    source.write_text("a,b\n1,2\n", encoding="utf-8")
    paths = _run_dari(tmp_path, settings, [source], "2026-01-01-mini")
    model = ScriptedModel([])

    outcome = AgentLoop(paths, settings, model, Brief()).run()

    assert model.calls == 0, "data terlalu kecil tidak perlu memanggil model"
    assert outcome.status == "failed"
    assert paths.report_file.is_file()
    done = read_json(paths.done_file)
    assert done["status"] == "failed"
    assert done["mode"] == "insufficient"
    assert "belum siap" in done["summary"]


def test_finish_blocked_stops_without_forcing_f7(run: RunPaths, settings) -> None:
    turns = [
        tool_turn(run_cell("print(4)", "hitung baris")),
        tool_turn(finish("blocked", "data belum siap")),
    ]
    loop = AgentLoop(run, settings, ScriptedModel(turns), Brief())
    outcome = loop.run()

    assert loop.controller.current == "F1", "blocked tidak boleh dipaksa ke F7"
    assert outcome.status == "blocked"


def test_two_groups_run_as_separate_units(run_dua_berkas: RunPaths, settings) -> None:
    class Capturing(ScriptedModel):
        def __init__(self) -> None:
            super().__init__([tool_turn(finish("partial", "cukup"))])
            self.seen: list[dict] = []

        def chat(self, messages: list[dict], tools: list[dict] | None = None):
            self.seen = list(messages)
            return super().chat(messages, tools)

    model = Capturing()
    AgentLoop(run_dua_berkas, settings, model, Brief()).run()

    # Pesan terakhir berasal dari unit terakhir (D2), yang hanya memuat
    # kelompoknya sendiri.
    opening = str(model.seen[1]["content"])
    assert "Lingkup unit" in opening
    assert "D2: pelanggan.csv" in opening
    assert "D1: penjualan.csv" not in opening
    assert (run_dua_berkas.dir / "datasets" / "D1" / "analysis.ipynb").is_file()
    assert (run_dua_berkas.dir / "datasets" / "D2" / "analysis.ipynb").is_file()


def test_giliran_kosong_di_nudge_lalu_lanjut(run: RunPaths, settings) -> None:
    # b7f451: gateway membalas kosong empat kali untuk prompt yang sama.
    # Giliran kosong harus memicu nudge, bukan menghentikan run.
    turns = [
        empty_turn(),
        tool_turn(run_cell("print(1)")),
        tool_turn(run_cell("print(2)")),
        tool_turn(finish("ok", "selesai")),
    ]
    model = ScriptedModel(turns)
    loop = AgentLoop(run, settings, model, Brief())

    outcome = loop.run()

    assert outcome.cells == 2, "dua cell setelah nudge harus benar-benar jalan"
    # Empat giliran skrip + satu `finish` bawaan ScriptedModel saat skrip habis.
    assert model.calls == 5
    assert not [error for error in outcome.errors if "tanpa memanggil tool" in error]


def test_tiga_giliran_kosong_berurutan_menghentikan_run(run: RunPaths, settings) -> None:
    model = ScriptedModel([empty_turn(), empty_turn(), empty_turn(), empty_turn()])
    loop = AgentLoop(run, settings, model, Brief())

    outcome = loop.run()

    assert outcome.cells == 0
    assert any("tanpa memanggil tool" in error for error in outcome.errors)


def test_nudge_direset_setelah_kemajuan(run: RunPaths, settings) -> None:
    # Satu giliran kosong di awal tidak boleh menghabiskan jatah nudge run.
    turns = [
        empty_turn(),
        tool_turn(run_cell("print(1)")),
        empty_turn(),
        tool_turn(run_cell("print(2)")),
        tool_turn(finish("ok", "selesai")),
    ]
    model = ScriptedModel(turns)
    loop = AgentLoop(run, settings, model, Brief())

    outcome = loop.run()

    assert outcome.cells == 2
    assert model.calls == 6
