from __future__ import annotations

import json
from dataclasses import replace

from conftest import ScriptedModel, finish, run_cell, tool_turn

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
