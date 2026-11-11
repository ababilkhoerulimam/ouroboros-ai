"""Agent loop: percakapan dengan model, dispatch tool, pencatatan state.

Satu run = satu kernel = satu notebook. Loop ini tidak menalar sendiri: ia
mengirim state, menjalankan tool, dan mencatat. Semua keputusan analisis milik model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .config import Settings
from .evidence import EvidenceStore, deepdive_due, next_deepdive_path
from .kernel import KernelSession, NotebookWriter
from .llm import ModelClient, ModelError, ModelTurn
from .phases import PHASES, PhaseController, PromptLibrary
from .runtime import RunPaths, StatusStore, atomic_write_json, utc_now
from .tools import ToolBox, ToolContext, hash_tree

MAX_NUDGES = 2


class ChatClient(Protocol):
    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> ModelTurn: ...


@dataclass
class Brief:
    business_type: str = ""
    main_kpi: str = ""
    period: str = ""
    decision: str = ""

    def as_text(self) -> str:
        rows = [
            ("jenis usaha", self.business_type),
            ("KPI utama", self.main_kpi),
            ("periode", self.period),
            ("keputusan yang ingin diambil", self.decision),
        ]
        filled = [f"- {label}: {value}" for label, value in rows if value]
        return "\n".join(filled) if filled else "- (tidak diisi; simpulkan dari data dan catat asumsinya)"


@dataclass
class RunOutcome:
    status: str
    summary: str
    cells: int
    evidence: int
    charts: int
    errors: list[str] = field(default_factory=list)
    report_written: bool = False


class AgentLoop:
    def __init__(
        self,
        paths: RunPaths,
        settings: Settings,
        client: ChatClient,
        brief: Brief | None = None,
        *,
        store: EvidenceStore | None = None,
        controller: PhaseController | None = None,
        prompts: PromptLibrary | None = None,
    ):
        self.paths = paths
        self.settings = settings
        self.client = client
        self.brief = brief or Brief()
        self.store = store or EvidenceStore(paths)
        self.controller = controller or PhaseController(paths, self.store)
        self.prompts = prompts or PromptLibrary()
        self.status = StatusStore(paths)
        self.cells_run = 0
        self.stalls = 0
        self.cells_since_checkpoint = 0
        self.checkpoint_pending: Path | None = None
        self.nudges = 0
        self.errors: list[str] = []
        self.phase_start_cell = 0

    # -- orkestrasi ---------------------------------------------------------

    def run(self) -> RunOutcome:
        self.paths.ensure()
        self._prepare_status()
        dataset_hash = hash_tree(self.paths.data_dir)
        if not dataset_hash:
            return self._fail("data/ kosong: ingest tidak menghasilkan berkas kerja")

        kernel = KernelSession(self.paths.dir, timeout_s=self.settings.cell_timeout_s)
        notebook = NotebookWriter(self.paths.notebook_file)
        toolbox = ToolBox(
            ToolContext(
                paths=self.paths,
                settings=self.settings,
                store=self.store,
                controller=self.controller,
                kernel=kernel,
                notebook=notebook,
                dataset_hash=dataset_hash,
            )
        )

        messages: list[dict[str, Any]] = [{"role": "system", "content": self._system_prompt()}]
        messages.append({"role": "user", "content": self._opening_message()})

        try:
            kernel.start()
            self._drive(messages, toolbox)
        except ModelError as exc:
            self.errors.append(f"model: {exc}")
        except Exception as exc:  # noqa: BLE001 - semua kegagalan harus tercatat
            self.errors.append(f"{type(exc).__name__}: {exc}")
        finally:
            kernel.shutdown()
            notebook.save()

        return self._finalize(toolbox)

    def _drive(self, messages: list[dict[str, Any]], toolbox: ToolBox) -> None:
        hard_limit = self.settings.max_cells + 10
        while self.cells_run <= hard_limit:
            self._maybe_checkpoint(messages)
            messages.append({"role": "user", "content": self._state_text()})

            turn = self.client.chat(messages, tools=ToolBox.schema())
            self._save_reasoning(turn)
            messages.append(self._assistant_message(turn))
            self._record_usage(turn)

            if not turn.tool_calls:
                self.nudges += 1
                if self.nudges > MAX_NUDGES:
                    self.errors.append("model berhenti tanpa memanggil tool")
                    return
                messages.append(
                    {
                        "role": "user",
                        "content": "Lanjutkan dengan memanggil satu tool. Jangan menjawab dengan prosa.",
                    }
                )
                continue

            for call in turn.tool_calls:
                result = toolbox.dispatch(call.name, dict(call.arguments or {}))
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.name,
                        "content": _json_text(result),
                    }
                )
                self._observe(call.name, call.arguments or {}, result, toolbox)

            if toolbox.ctx.finished:
                if self.controller.current != "F7":
                    self._force_f7(messages, toolbox)
                    toolbox.ctx.finished = False
                    continue
                return
            if self.controller.current == "F7" and self.paths.report_file.exists():
                toolbox.ctx.finished = True
                return

    # -- prompt -------------------------------------------------------------

    def _system_prompt(self) -> str:
        parts = [
            self.prompts.system(),
            self.prompts.module("loop"),
            self.prompts.module("style"),
            self.prompts.module("evidence"),
            self.prompts.module("tools"),
        ]
        return "\n\n---\n\n".join(parts)

    def _opening_message(self) -> str:
        lines = [
            "## Brief operator",
            self.brief.as_text(),
            "",
            "## Berkas masukan",
            self._profile_summary(),
            "",
            "Mulai dari F1. Baca profile.json lebih dulu dengan read_file.",
        ]
        return "\n".join(lines)

    def _profile_summary(self) -> str:
        import json

        profile = self.paths.profile_file
        if not profile.exists():
            return "- profile.json belum ada"
        data = json.loads(profile.read_text(encoding="utf-8"))
        rows = []
        for item in data.get("files", []):
            rows.append(
                f"- {item.get('name')}: {item.get('rows')} baris, {item.get('cols')} kolom, "
                f"format {item.get('format')}"
            )
        return "\n".join(rows) or "- tidak ada berkas"

    def _state_text(self) -> str:
        phase = self.controller.current or "F1"
        completed = [name for name in PHASES if self.controller.is_completed(name)]
        remaining = max(self.settings.deepdive_every - self.cells_since_checkpoint, 0)
        return "\n\n".join(
            [
                self.prompts.state_block(
                    phase=phase,
                    cell=self.cells_run,
                    evidence_count=self.store.count(),
                    allowed=self.controller.allowed_targets(),
                    phase_completed=completed,
                    cells_in_phase=self.cells_run - self.phase_start_cell,
                    evidence_in_phase=self.store.count(phase),
                    checkpoint_in=remaining,
                    stalls=self.stalls,
                ),
                self.prompts.phase(phase),
            ]
        )

    def _maybe_checkpoint(self, messages: list[dict[str, Any]]) -> None:
        if self.checkpoint_pending is not None:
            return
        trigger = deepdive_due(
            cells_since_checkpoint=self.cells_since_checkpoint,
            stall_streak=self.stalls,
            every=self.settings.deepdive_every,
            stall_limit=self.settings.stall_cells,
        )
        if trigger is None:
            return
        target = next_deepdive_path(self.paths)
        self.checkpoint_pending = target
        relative = self.paths.relative(target)
        messages.append(
            {
                "role": "user",
                "content": "\n".join(
                    [
                        f"## Checkpoint deep-dive ({trigger})",
                        self.prompts.module("deepdive"),
                        "",
                        f"Tulis keputusan ke `{relative}` dengan write_file, lalu lanjutkan. "
                        "Jangan menulis cell analisis baru sebelum berkas itu ada.",
                    ]
                ),
            }
        )

    # -- observasi ----------------------------------------------------------

    def _observe(
        self,
        name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        toolbox: ToolBox,
    ) -> None:
        if name == "write_file":
            path = str(result.get("path") or arguments.get("path") or "")
            if path.startswith("evidence/deepdive/"):
                self.checkpoint_pending = None
                self.cells_since_checkpoint = 0
                self.stalls = 0
            return

        if name != "run_cell":
            return

        self.cells_run = int(result.get("cell") or self.cells_run)
        self.cells_since_checkpoint += 1
        stdout = str(result.get("stdout") or "")
        status = str(result.get("status") or "")
        numeric = bool(re.search(r"\d", stdout)) and status == "ok"
        self.stalls = 0 if numeric else self.stalls + 1
        if status == "timeout":
            self.errors.append(f"cell {self.cells_run} timeout")
        self._sync_status(toolbox)

    def _sync_status(self, toolbox: ToolBox) -> None:
        self.status.update(
            phase=self.controller.current or "F1",
            cell=self.cells_run,
            counts={
                "cells": self.cells_run,
                "evidence": self.store.count(),
                "charts": len(toolbox.ctx.charts),
            },
        )

    def _record_usage(self, turn: ModelTurn) -> None:
        usage = turn.usage or {}
        self.status.bump_usage(
            int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
        )

    def _save_reasoning(self, turn: ModelTurn) -> None:
        if not turn.reasoning_content:
            return
        n = self.cells_run + 1
        path = self.paths.cells_dir / f"{n:03d}.reasoning.txt"
        path.write_text(turn.reasoning_content, encoding="utf-8", newline="\n")

    # -- F7 -----------------------------------------------------------------

    def _force_f7(self, messages: list[dict[str, Any]], toolbox: ToolBox) -> None:
        self.controller.force("F7", "finish dipanggil sebelum F7; laporan tetap wajib terbit")
        self.status.update(state="running", phase="F7")
        self.phase_start_cell = self.cells_run
        messages.append(
            {
                "role": "user",
                "content": (
                    "## F7 wajib\n"
                    "Run belum melewati F7. Tulis laporan sekarang mengikuti report.md: "
                    "hanya evidence terverifikasi, setiap angka lewat slot, tulis ke `laporan.md` "
                    "lalu panggil finish."
                ),
            }
        )

    # -- penutup ------------------------------------------------------------

    def _prepare_status(self) -> None:
        if self.paths.status_file.exists():
            self.status.update(state="running", phase="F1")
        else:
            self.status.create(
                inputs=self._inputs(),
                env=self._env(),
                model={"requested": self.settings.model, "returned": ""},
            )
            self.status.update(state="running", phase="F1")
        if not self.controller.current:
            self.controller.force("F1", "start")

    def _inputs(self) -> list[dict[str, Any]]:
        import json

        if not self.paths.profile_file.exists():
            return []
        data = json.loads(self.paths.profile_file.read_text(encoding="utf-8"))
        return [
            {"name": item.get("name"), "sha256": item.get("sha256"), "bytes": item.get("bytes")}
            for item in data.get("files", [])
        ]

    def _env(self) -> dict[str, str]:
        import platform

        import numpy
        import pandas

        return {
            "python": platform.python_version(),
            "pandas": pandas.__version__,
            "numpy": numpy.__version__,
        }

    def _finalize(self, toolbox: ToolBox) -> RunOutcome:
        index = self._cells_index()
        hashes = self._dataset_hashes()
        dataset_hash = hashes[0] if hashes else ""
        problems = self.store.validate_all(cells_index=index, dataset_hash=dataset_hash)
        for problem in problems:
            self.errors.append(f"evidence: {problem}")
            self.status.warn(problem)

        status = toolbox.ctx.finish_status or "partial"
        if problems or self.errors:
            status = "partial" if status == "ok" else status

        done = {
            "status": status,
            "phases_completed": [name for name in PHASES if self.controller.is_completed(name)],
            "phases_skipped": self._skipped(),
            "deliverables": {
                "notebook": "analysis.ipynb" if self.paths.notebook_file.exists() else "",
                "report_md": "laporan.md" if self.paths.report_file.exists() else "",
                "report_pdf": "",
                "clean_data": "derived/01_clean.csv" if self.paths.clean_data_file.exists() else "",
            },
            "verification": {"rerun": "skipped", "mismatches": []},
            "summary": toolbox.ctx.finish_summary or "run berhenti tanpa ringkasan model",
            "finished_at": utc_now(),
        }
        atomic_write_json(self.paths.done_file, done)
        self.status.update(
            state="done" if status in {"ok", "partial"} else "failed",
            counts={
                "cells": self.cells_run,
                "evidence": self.store.count(),
                "charts": len(toolbox.ctx.charts),
            },
        )
        return RunOutcome(
            status=status,
            summary=str(done["summary"]),
            cells=self.cells_run,
            evidence=self.store.count(),
            charts=len(toolbox.ctx.charts),
            errors=self.errors,
            report_written=self.paths.report_file.exists(),
        )

    def _skipped(self) -> list[dict[str, str]]:
        return [
            {"phase": name, "reason": "tidak ditandai selesai oleh model"}
            for name in ("F4", "F5")
            if not self.controller.is_completed(name)
        ]

    def _cells_index(self) -> dict[str, Any]:
        import json

        path = self.paths.cells_dir / "index.json"
        if not path.exists():
            return {"cells": []}
        return json.loads(path.read_text(encoding="utf-8"))

    def _dataset_hashes(self) -> list[str]:
        return list(hash_tree(self.paths.data_dir).values())

    def _assistant_message(self, turn: ModelTurn) -> dict[str, Any]:
        message: dict[str, Any] = {"role": "assistant", "content": turn.content or ""}
        if turn.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": _json_text(call.arguments or {}),
                    },
                }
                for call in turn.tool_calls
            ]
        return message

    def _fail(self, message: str) -> RunOutcome:
        self.errors.append(message)
        atomic_write_json(
            self.paths.done_file,
            {
                "status": "failed",
                "phases_completed": [],
                "phases_skipped": [],
                "deliverables": {},
                "verification": {"rerun": "skipped", "mismatches": []},
                "summary": message,
                "finished_at": utc_now(),
            },
        )
        return RunOutcome("failed", message, 0, 0, 0, errors=self.errors)


def _json_text(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def build_client(settings: Settings) -> ModelClient:
    base_url, api_key = settings.require_model()
    return ModelClient(base_url, api_key, settings.model)
