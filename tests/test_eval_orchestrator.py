"""Tes orkestrator satu varian.

Yang dijaga: urutan pemeriksaan (ledger → pin/split → patch → run → skor →
keputusan), baseline terikat ke digest verifier, dan worktree/branch varian
yang tidak dipromosikan benar-benar dibuang.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from swarmfold_eval import cli, gate, ledger, orchestrator
from swarmfold_verify import cases, pins

SRC = Path(__file__).resolve().parents[1] / "src" / "swarmfold_verify"
SEMUA_KASUS = cases.splits()["tune"] + cases.splits()["heldout"]


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, timeout=60, check=False
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return result.stdout.decode("utf-8", "surrogateescape")


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "uji@contoh")
    _git(repo, "config", "user.name", "uji")
    _git(repo, "config", "core.autocrlf", "false")
    (repo / "prompts").mkdir()
    (repo / "prompts" / "style.md").write_bytes(b"lama\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "awal")
    _git(repo, "branch", "eval/base")
    return repo


def _patch(path: str = "prompts/style.md") -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1 +1 @@\n"
        "-lama\n"
        "+baru\n"
    )


class FakeBench:
    """Runner + scorer palsu; skor ditentukan per (nama worktree, kasus)."""

    def __init__(self, tmp_path: Path, skor: dict[tuple[str, str], dict]) -> None:
        self.tmp = tmp_path / "runs"
        self.skor = skor
        self.panggilan: list[tuple[str, str, int]] = []

    def run(self, worktree: Path, case_id: str, input_dir: Path, replica: int) -> Path:
        self.panggilan.append((worktree.name, case_id, replica))
        run = self.tmp / f"{worktree.name}-{case_id}-{replica}"
        run.mkdir(parents=True, exist_ok=True)
        (run / "score.json").write_text(
            json.dumps(self.skor[(worktree.name, case_id)]), encoding="utf-8"
        )
        return run

    def score(self, run_dir: Path, case_id: str) -> dict:
        return json.loads((Path(run_dir) / "score.json").read_text(encoding="utf-8"))


def _skor(nama: list[str], recall: float) -> dict[tuple[str, str], dict]:
    return {
        (worktree, case): {"recall": recall, "false_discovery": 0.0, "defect_rate": 0.0}
        for worktree in nama
        for case in SEMUA_KASUS
    }


@pytest.fixture
def siap(tmp_path: Path) -> tuple[Path, Path, dict]:
    root = tmp_path / "evals"
    cases.build_all(root)
    lock = pins.pin(SRC, root / "pins")
    return root, _repo(tmp_path), lock


def _orch(root: Path, repo: Path, bench: FakeBench) -> orchestrator.Orchestrator:
    return orchestrator.Orchestrator(root, repo, bench.run, bench.score, replicas=2)


def _variant(ident: str = "v001", diff: str | None = None) -> orchestrator.Variant:
    return orchestrator.Variant(
        variant_id=ident,
        hypothesis="aturan persen menaikkan recall",
        layer="prompt",
        expected="recall naik >= 0.10",
        diff=_patch() if diff is None else diff,
    )


def test_baseline_written_with_pin(siap: tuple[Path, Path, dict]) -> None:
    root, repo, lock = siap
    bench = FakeBench(root.parent, _skor(["repo"], 0.40))

    data = _orch(root, repo, bench).measure_baseline(repo)

    assert data["pin"] == lock["digest"]
    assert len(data["splits"]["tune"]) == len(cases.splits()["tune"]) * 2
    assert (root / orchestrator.BASELINE_FILE).is_file()


def test_promoted_keeps_branch(siap: tuple[Path, Path, dict]) -> None:
    root, repo, lock = siap
    bench = FakeBench(root.parent, {**_skor(["repo"], 0.40), **_skor(["v001"], 0.70)})
    orch = _orch(root, repo, bench)
    orch.measure_baseline(repo)

    hasil = orch.evaluate(_variant())

    assert hasil.verdict == "promoted"
    assert (root / "worktrees" / "v001").is_dir()
    assert "eval/v001" in _git(repo, "branch", "--list", "eval/v001")
    assert [row["verdict"] for row in ledger.read(root / ledger.LEDGER_FILE)] == ["promoted"]


def test_regressed_removes_branch(siap: tuple[Path, Path, dict]) -> None:
    root, repo, lock = siap
    bench = FakeBench(root.parent, {**_skor(["repo"], 0.70), **_skor(["v001"], 0.40)})
    orch = _orch(root, repo, bench)
    orch.measure_baseline(repo)

    hasil = orch.evaluate(_variant())

    assert hasil.verdict == "regressed"
    assert not (root / "worktrees" / "v001").exists()
    assert _git(repo, "branch", "--list", "eval/v001").strip() == ""
    assert ledger.last(root / ledger.LEDGER_FILE)["verdict"] == "regressed"


def test_out_of_scope_diff_is_schema_rejected(siap: tuple[Path, Path, dict]) -> None:
    root, repo, lock = siap
    bench = FakeBench(root.parent, _skor(["repo"], 0.40))
    orch = _orch(root, repo, bench)
    orch.measure_baseline(repo)
    bench.panggilan.clear()

    hasil = orch.evaluate(_variant(diff=_patch("src/swarmfold_verify/scorer.py")))

    assert hasil.verdict == "schema_rejected"
    assert bench.panggilan == []
    assert not (root / "worktrees" / "v001").exists()


def test_baseline_from_other_pin_is_refused(siap: tuple[Path, Path, dict]) -> None:
    root, repo, lock = siap
    bench = FakeBench(root.parent, _skor(["repo"], 0.40))
    orch = _orch(root, repo, bench)
    data = orch.measure_baseline(repo)
    data["pin"] = "sha256:0000"
    (root / orchestrator.BASELINE_FILE).write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(orchestrator.OrchestratorError, match="verifier"):
        orch.baseline()


def test_tampered_ledger_stops_evaluate(siap: tuple[Path, Path, dict]) -> None:
    root, repo, lock = siap
    bench = FakeBench(root.parent, _skor(["repo"], 0.40))
    orch = _orch(root, repo, bench)
    orch.measure_baseline(repo)
    (root / ledger.LEDGER_FILE).write_text('{"seq": 1, "verdict": "promoted"}\n', encoding="utf-8")

    with pytest.raises(gate.GateError):
        orch.evaluate(_variant())


def test_selftest_clean(siap: tuple[Path, Path, dict]) -> None:
    root, repo, lock = siap

    assert _orch(root, repo, FakeBench(root.parent, {})).selftest() == []


def test_cli_selftest(siap: tuple[Path, Path, dict], capsys: pytest.CaptureFixture[str]) -> None:
    root, repo, lock = siap

    kode = cli.main(["selftest", "--root", str(root), "--repo", str(repo)])

    assert kode == 0
    assert json.loads(capsys.readouterr().out)["count"] == 0
