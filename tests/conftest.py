from __future__ import annotations

from pathlib import Path

import pytest
from synthetic import tulis_pelanggan, tulis_penjualan

from swarmfold.config import Settings
from swarmfold.ingest import ingest
from swarmfold.llm import ModelTurn, ToolCall
from swarmfold.runtime import RunPaths


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        api_key=None,
        base_url=None,
        model="test/model",
        max_cells=30,
        cell_timeout_s=30,
        stall_cells=3,
        deepdive_every=10,
        data_root=tmp_path / "runs",
    )


@pytest.fixture
def run(settings: Settings, tmp_path: Path) -> RunPaths:
    paths = RunPaths(settings.data_root, "2026-01-01-test").ensure()
    ingest([tulis_penjualan(tmp_path / "penjualan.csv")], paths)
    return paths


@pytest.fixture
def run_dua_berkas(settings: Settings, tmp_path: Path) -> RunPaths:
    """Dua CSV tanpa kunci bersama: kelompok data yang terpisah."""
    paths = RunPaths(settings.data_root, "2026-01-01-dua").ensure()
    ingest(
        [
            tulis_penjualan(tmp_path / "penjualan.csv"),
            tulis_pelanggan(tmp_path / "pelanggan.csv"),
        ],
        paths,
    )
    return paths


def tool_turn(*calls: tuple[str, dict], content: str = "") -> ModelTurn:
    return ModelTurn(
        content=content,
        reasoning_content=None,
        tool_calls=[
            ToolCall(id=f"call_{index}", name=name, arguments=arguments)
            for index, (name, arguments) in enumerate(calls)
        ],
        usage={"prompt_tokens": 10, "completion_tokens": 5},
        latency_ms=5,
        model_requested="test/model",
        finish_reason="tool_calls",
    )


def run_cell(code: str, intent: str = "coba satu angka") -> tuple[str, dict]:
    return ("run_cell", {"code": code, "intent": intent})


def finish(status: str = "ok", summary: str = "selesai") -> tuple[str, dict]:
    return ("finish", {"status": status, "summary": summary})


class ScriptedModel:
    """Model palsu: memutar daftar giliran, lalu menutup run."""

    def __init__(self, turns: list[ModelTurn]):
        self.turns = list(turns)
        self.calls = 0

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> ModelTurn:
        self.calls += 1
        if self.turns:
            return self.turns.pop(0)
        return tool_turn(finish("partial", "skrip habis"))
