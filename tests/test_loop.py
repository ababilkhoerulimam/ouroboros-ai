from __future__ import annotations

import json

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
    assert outcome.status == "partial"
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
