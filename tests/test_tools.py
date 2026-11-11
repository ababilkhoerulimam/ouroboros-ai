from __future__ import annotations

import json

import pytest

from swarmfold.evidence import EvidenceStore
from swarmfold.kernel import KernelSession, NotebookWriter
from swarmfold.phases import PhaseController
from swarmfold.runtime import RunPaths
from swarmfold.tools import ToolBox, ToolContext, hash_tree


@pytest.fixture
def toolbox(run: RunPaths, settings):
    store = EvidenceStore(run)
    controller = PhaseController(run, store)
    controller.force("F1", "test")
    kernel = KernelSession(run.dir, timeout_s=30)
    kernel.start()
    context = ToolContext(
        paths=run,
        settings=settings,
        store=store,
        controller=controller,
        kernel=kernel,
        notebook=NotebookWriter(run.notebook_file),
        dataset_hash=hash_tree(run.data_dir),
    )
    box = ToolBox(context)
    yield box
    kernel.shutdown()


def test_run_cell_writes_artifacts_and_index(toolbox: ToolBox, run: RunPaths) -> None:
    result = toolbox.dispatch("run_cell", {"code": "print(6 * 7)", "intent": "uji aritmetika"})
    assert result["status"] == "ok"
    assert "42" in result["stdout"]
    assert (run.cells_dir / "001.py").exists()
    assert "42" in (run.cells_dir / "001.out.txt").read_text(encoding="utf-8")
    index = json.loads((run.cells_dir / "index.json").read_text(encoding="utf-8"))
    assert index["cells"][0]["status"] == "ok"
    assert index["cells"][0]["phase"] == "F1"


def test_intent_limits(toolbox: ToolBox) -> None:
    assert "error" in toolbox.dispatch("run_cell", {"code": "print(1)", "intent": ""})
    long_intent = "x" * 121
    result = toolbox.dispatch("run_cell", {"code": "print(1)", "intent": long_intent})
    assert "error" in result and "120" in result["error"]


def test_write_file_sandbox(toolbox: ToolBox) -> None:
    blocked = toolbox.dispatch("write_file", {"path": "data/x.csv", "content": "a,b\n1,2\n"})
    assert "error" in blocked
    absolute = toolbox.dispatch("write_file", {"path": "/tmp/x.json", "content": "{}"})
    assert "error" in absolute
    escape = toolbox.dispatch("write_file", {"path": "../x.json", "content": "{}"})
    assert "error" in escape
    allowed = toolbox.dispatch(
        "write_file", {"path": "notes/catatan.md", "content": "catatan\n"}
    )
    assert allowed.get("ok") is True


def test_cell_cannot_write_to_data(toolbox: ToolBox, run: RunPaths) -> None:
    before = hash_tree(run.data_dir)
    data_file = next(run.data_dir.iterdir())
    code = f"open({str(data_file)!r}, 'w').write('dirusak')\nprint(1)"
    result = toolbox.dispatch("run_cell", {"code": code, "intent": "coba merusak data"})
    assert result.get("status") == "error" or "error" in result
    assert hash_tree(run.data_dir) == before, "data/ berubah setelah cell"


def test_output_truncated_to_budget(toolbox: ToolBox) -> None:
    code = "print('\\n'.join(str(i) for i in range(100)))"
    result = toolbox.dispatch("run_cell", {"code": code, "intent": "uji potong output"})
    assert result["truncated"] is True
    assert len(result["stdout"].splitlines()) <= 41


def test_chart_saved_and_indexed(toolbox: ToolBox, run: RunPaths) -> None:
    code = (
        "import matplotlib.pyplot as plt\n"
        "print('nilai=7')\n"
        "fig, ax = plt.subplots(figsize=(3, 2))\n"
        "ax.plot([1, 2, 3], [1, 4, 2])\n"
        "fig.savefig('charts/tmp.png', dpi=80)\n"
        "plt.show()\n"
        "plt.close(fig)\n"
    )
    result = toolbox.dispatch("run_cell", {"code": code, "intent": "uji tangkap gambar"})
    assert result["status"] == "ok"
    assert result["images"], "gambar tidak tertangkap"
    assert (run.dir / result["images"][0]).exists()


def test_advance_phase_marks_previous_complete(toolbox: ToolBox) -> None:
    result = toolbox.dispatch("advance_phase", {"target": "F2", "reason": "profil data selesai"})
    assert result.get("ok") is True
    assert toolbox.ctx.controller.is_completed("F1") is True


def test_finish_sets_flags(toolbox: ToolBox) -> None:
    result = toolbox.dispatch("finish", {"status": "ok", "summary": "selesai"})
    assert result.get("ok") is True
    assert toolbox.ctx.finished is True
    assert "error" in toolbox.dispatch("finish", {"status": "aneh", "summary": "x"})
