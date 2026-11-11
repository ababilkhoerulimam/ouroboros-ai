"""Enam tool yang diberikan ke model, dengan sandbox path dan verifikasi hash.

Batas keras:
- tidak ada shell, tidak ada akses jaringan, tidak ada filesystem bebas
- `data/` read-only: hash diperiksa sebelum dan sesudah setiap cell
- `write_file` hanya ke `evidence/`, `charts/`, `notes/`
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Settings
from .evidence import EvidenceStore
from .kernel import CellOutput, KernelSession, NotebookWriter
from .phases import PHASES, PhaseController
from .runtime import RunPaths, atomic_write_json, atomic_write_text, read_json

MAX_INTENT = 120
OUTPUT_LINES = 40
OUTPUT_CHARS = 8000
READ_LIMIT_BYTES = 200_000
WRITABLE_DIRS = ("evidence", "charts", "notes")


class ToolError(RuntimeError):
    """Panggilan tool yang tidak sah; dikembalikan ke model sebagai error."""


def _slug(text: str, limit: int = 40) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return (cleaned[:limit] or "cell").strip("_")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_tree(root: Path) -> dict[str, str]:
    """sha256 setiap berkas di bawah `root`, kunci relatif POSIX."""
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _truncate(text: str) -> tuple[str, bool]:
    truncated = False
    lines = text.splitlines()
    if len(lines) > OUTPUT_LINES:
        lines = lines[:OUTPUT_LINES]
        truncated = True
    text = "\n".join(lines)
    if len(text) > OUTPUT_CHARS:
        text = text[:OUTPUT_CHARS]
        truncated = True
    if truncated:
        text += f"\n[output dipotong: {OUTPUT_LINES} baris / {OUTPUT_CHARS} karakter]"
    return text, truncated


@dataclass
class ToolContext:
    paths: RunPaths
    settings: Settings
    store: EvidenceStore
    controller: PhaseController
    kernel: KernelSession
    notebook: NotebookWriter
    dataset_hash: dict[str, str]
    finished: bool = False
    finish_status: str | None = None
    finish_summary: str | None = None
    cells_run: int = 0
    charts: list[str] = field(default_factory=list)
    fatal: bool = False


class ToolBox:
    def __init__(self, context: ToolContext):
        self.ctx = context

    # -- skema --------------------------------------------------------------

    @staticmethod
    def schema() -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "run_cell",
                    "description": "Jalankan satu cell Python di kernel run ini dan kembalikan outputnya.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string", "description": "Kode Python satu pertanyaan."},
                            "intent": {
                                "type": "string",
                                "description": "Satu baris, maksimal 120 karakter, bahasa Indonesia.",
                            },
                        },
                        "required": ["code", "intent"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Baca berkas di dalam direktori run.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "limit": {"type": "integer", "minimum": 1, "maximum": 2000},
                        },
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_files",
                    "description": "Daftar berkas dan ukuran di dalam direktori run.",
                    "parameters": {
                        "type": "object",
                        "properties": {"dir": {"type": "string"}},
                        "required": ["dir"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": "Tulis berkas ke evidence/, charts/, atau notes/.",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                        "required": ["path", "content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "advance_phase",
                    "description": "Pindah fase analisis; controller memeriksa prasyarat.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "target": {"type": "string", "enum": list(PHASES)},
                            "reason": {"type": "string"},
                        },
                        "required": ["target", "reason"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "finish",
                    "description": "Tutup run dengan status dan ringkasan singkat.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "status": {
                                "type": "string",
                                "enum": ["ok", "partial", "blocked", "failed"],
                            },
                            "summary": {"type": "string"},
                        },
                        "required": ["status", "summary"],
                    },
                },
            },
        ]

    # -- dispatch -----------------------------------------------------------

    def dispatch(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handlers = {
            "run_cell": self.run_cell,
            "read_file": self.read_file,
            "list_files": self.list_files,
            "write_file": self.write_file,
            "advance_phase": self.advance_phase,
            "finish": self.finish,
        }
        handler = handlers.get(name)
        if handler is None:
            return {"error": f"tool tidak dikenal: {name}"}
        try:
            return handler(**arguments)
        except ToolError as exc:
            return {"error": str(exc)}
        except TypeError as exc:
            return {"error": f"argumen tidak sah untuk {name}: {exc}"}

    # -- run_cell -----------------------------------------------------------

    def run_cell(self, code: str, intent: str) -> dict[str, Any]:
        if not isinstance(code, str) or not code.strip():
            raise ToolError("code kosong")
        intent = (intent or "").strip()
        if not intent:
            raise ToolError("intent wajib diisi")
        if len(intent) > MAX_INTENT:
            raise ToolError(f"intent maksimal {MAX_INTENT} karakter, diterima {len(intent)}")
        if self.ctx.cells_run >= self.ctx.settings.max_cells:
            raise ToolError(
                f"batas cell tercapai ({self.ctx.settings.max_cells}); panggil finish sekarang"
            )

        self._verify_data("sebelum cell")
        n = self.ctx.cells_run + 1
        phase = self.ctx.controller.current or "F1"
        output = self.ctx.kernel.execute(code, timeout_s=self.ctx.settings.cell_timeout_s)

        stdout, truncated_out = _truncate(output.stdout)
        stderr, truncated_err = _truncate(output.stderr)
        error = output.error
        if error:
            error, _ = _truncate(error)

        code_path = self.ctx.paths.cells_dir / f"{n:03d}.py"
        atomic_write_text(code_path, code.rstrip("\n") + "\n")
        artifact = self.ctx.paths.cells_dir / f"{n:03d}.out.txt"
        artifact.write_text(
            self._artifact_text(stdout, stderr, error), encoding="utf-8", newline="\n"
        )

        chart_paths = self._save_images(output, phase, n, intent)
        self.ctx.notebook.add_code(code, intent, output)
        self.ctx.notebook.save()

        entry = {
            "n": n,
            "phase": phase,
            "intent": intent,
            "status": output.status,
            "duration_ms": output.duration_ms,
            "evidence": [],
            "charts": chart_paths,
        }
        self._append_cell_index(entry)
        self.ctx.cells_run = n
        if chart_paths:
            self.ctx.charts.extend(chart_paths)

        # Verifikasi "sesudah" berjalan setelah cell tercatat: cell yang merusak
        # data/ tetap masuk audit trail, lalu run dihentikan sebagai fatal.
        self._verify_data("sesudah cell")

        return {
            "cell": n,
            "status": output.status,
            "stdout": stdout,
            "stderr": stderr,
            "error": error,
            "images": chart_paths,
            "duration_ms": output.duration_ms,
            "truncated": truncated_out or truncated_err,
        }

    def _artifact_text(self, stdout: str, stderr: str, error: str | None) -> str:
        parts = [stdout.rstrip("\n")]
        if stderr.strip():
            parts.append("[stderr]\n" + stderr.rstrip("\n"))
        if error:
            parts.append("[error]\n" + error.rstrip("\n"))
        return "\n".join(part for part in parts if part) + "\n"

    def _save_images(self, output: CellOutput, phase: str, n: int, intent: str) -> list[str]:
        saved: list[str] = []
        for index, png in enumerate(output.images, start=1):
            suffix = f"_{index}" if index > 1 else ""
            name = f"{phase}_{n:03d}_{_slug(intent)}{suffix}.png"
            path = self.ctx.paths.charts_dir / name
            path.write_bytes(png)
            saved.append(f"charts/{name}")
        return saved

    def _append_cell_index(self, entry: dict[str, Any]) -> None:
        index_file = self.ctx.paths.cells_dir / "index.json"
        data = read_json(index_file, {"cells": []}) or {"cells": []}
        cells = [cell for cell in data.get("cells", []) if cell.get("n") != entry["n"]]
        cells.append(entry)
        data["cells"] = sorted(cells, key=lambda cell: cell["n"])
        atomic_write_json(index_file, data)

    def _verify_data(self, when: str) -> None:
        current = hash_tree(self.ctx.paths.data_dir)
        if current != self.ctx.dataset_hash:
            changed = sorted(set(current) ^ set(self.ctx.dataset_hash)) or [
                name
                for name in current
                if current.get(name) != self.ctx.dataset_hash.get(name)
            ]
            # `data/` adalah salinan kanonik yang mendasari semua angka; kalau
            # berubah, run tidak boleh lanjut dan tidak boleh berakhir "ok".
            self.ctx.fatal = True
            raise ToolError(
                f"data/ berubah {when}: {', '.join(changed)}; run dihentikan karena data mentah "
                "harus read-only"
            )

    # -- files --------------------------------------------------------------

    def read_file(self, path: str, limit: int | None = None) -> dict[str, Any]:
        target = self._resolve(path)
        if not target.is_file():
            raise ToolError(f"berkas tidak ada: {path}")
        size = target.stat().st_size
        if size > READ_LIMIT_BYTES:
            raise ToolError(f"berkas terlalu besar ({size} byte); pakai kode di run_cell")
        text = target.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        cap = min(int(limit or 200), 2000)
        return {
            "path": self.ctx.paths.relative(target),
            "lines": len(lines),
            "truncated": len(lines) > cap,
            "content": "\n".join(lines[:cap]),
        }

    def list_files(self, dir: str = ".") -> dict[str, Any]:
        target = self._resolve(dir)
        if not target.exists():
            raise ToolError(f"direktori tidak ada: {dir}")
        if not target.is_dir():
            raise ToolError(f"bukan direktori: {dir}")
        entries = []
        for item in sorted(target.iterdir()):
            entries.append(
                {
                    "name": item.name,
                    "type": "dir" if item.is_dir() else "file",
                    "bytes": 0 if item.is_dir() else item.stat().st_size,
                }
            )
        return {"dir": self.ctx.paths.relative(target), "entries": entries[:200]}

    def write_file(self, path: str, content: str) -> dict[str, Any]:
        if not isinstance(content, str):
            raise ToolError("content harus string")
        target = self._resolve(path, allow_missing=True)
        relative = self.ctx.paths.relative(target)
        top = relative.split("/", 1)[0]
        if top not in WRITABLE_DIRS:
            raise ToolError(
                f"write_file hanya boleh ke {', '.join(WRITABLE_DIRS)}/; ditolak: {relative}"
            )
        if target.suffix.lower() not in {".json", ".md", ".txt", ".csv"}:
            raise ToolError(f"ekstensi tidak diizinkan: {target.suffix}")
        atomic_write_text(target, content if content.endswith("\n") else content + "\n")
        if target.suffix.lower() == ".json":
            try:
                json.loads(target.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ToolError(f"JSON tidak valid setelah ditulis: {exc}") from exc
        return {"ok": True, "path": relative, "bytes": len(content.encode("utf-8"))}

    # -- fase ---------------------------------------------------------------

    def advance_phase(self, target: str, reason: str = "") -> dict[str, Any]:
        controller = self.ctx.controller
        current = controller.current
        not_applicable = "tidak berlaku" in (reason or "").lower()

        # Fase hanya boleh ditutup kalau ada bukti kerja nyata. Tanpa ini model
        # bisa mengklaim F1 selesai tanpa satu cell pun, lalu F2 lolos prasyarat.
        if current not in ("", "F7") and not not_applicable and not self._phase_has_work(current):
            return {
                "error": (
                    f"{current} belum punya bukti kerja: butuh minimal satu cell berstatus ok "
                    f"di fase itu atau entri di evidence/{current}.json"
                ),
                "allowed": controller.allowed_targets(),
                "hint": "jalankan cell yang menjawab pertanyaan fase ini sebelum pindah",
            }

        # Penutupan fase dilakukan controller di dalam transisi yang sama:
        # penolakan tidak boleh memutasi state, dan langkah mundur tidak menutup
        # fase yang ditinggal.
        close_current: bool | None = None
        if current not in ("", "F7") and target in PHASES:
            forward = PHASES.index(target) > PHASES.index(current)
            if forward or not_applicable:
                close_current = not not_applicable

        result = controller.advance(target, reason or "", close_current=close_current)
        if not result.ok:
            return {
                "error": result.reason,
                "allowed": result.allowed,
                "hint": "pilih dari allowed; jangan ulangi target yang sama",
            }
        return {"ok": True, "phase": result.target, "allowed": result.allowed}

    def _phase_has_work(self, phase: str) -> bool:
        """Ada cell ok di fase itu, atau entri bukti yang ditulis untuk fase itu."""
        data = read_json(self.ctx.paths.cells_dir / "index.json", {"cells": []}) or {"cells": []}
        for cell in data.get("cells", []):
            if not isinstance(cell, dict):
                continue
            if cell.get("phase") == phase and cell.get("status") == "ok":
                return True
        evidence = self.ctx.store.load(phase)
        if evidence.get("audit_complete") is True:
            return True
        return any(evidence.get(section) for section in ("findings", "hypotheses", "anomalies"))

    def finish(self, status: str, summary: str) -> dict[str, Any]:
        if status not in {"ok", "partial", "blocked", "failed"}:
            raise ToolError(f"status tidak sah: {status}")
        if not (summary or "").strip():
            raise ToolError("summary wajib diisi")
        self.ctx.finished = True
        self.ctx.finish_status = status
        self.ctx.finish_summary = summary.strip()
        return {"ok": True, "status": status}

    # -- sandbox ------------------------------------------------------------

    def _resolve(self, path: str, *, allow_missing: bool = False) -> Path:
        raw = (path or "").replace("\\", "/").strip()
        if not raw:
            raw = "."
        if raw.startswith("/") or re.match(r"^[a-zA-Z]:", raw):
            raise ToolError(f"path absolut tidak diizinkan: {path}")
        candidate = (self.ctx.paths.dir / raw).resolve()
        root = self.ctx.paths.dir.resolve()
        if candidate != root and root not in candidate.parents:
            raise ToolError(f"path keluar dari direktori run: {path}")
        if not allow_missing and not candidate.exists():
            raise ToolError(f"path tidak ada: {path}")
        return candidate
