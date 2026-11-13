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

from swarmfold_eval import cli, gate, ledger, orchestrator, patcher, reviewer
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


def test_baseline_survives_one_failed_run(siap: tuple[Path, Path, dict]) -> None:
    root, repo, lock = siap
    bench = FakeBench(root.parent, _skor(["repo"], 0.40))
    asli = bench.run

    def run(worktree: Path, case_id: str, input_dir: Path, replica: int) -> Path:
        if case_id == "trend-01" and replica == 0:
            raise orchestrator.OrchestratorError("run terputus")
        return asli(worktree, case_id, input_dir, replica)

    orch = orchestrator.Orchestrator(root, repo, run, bench.score, replicas=2)

    data = orch.measure_baseline(repo)

    tune = data["splits"]["tune"]
    assert len(tune) == len(cases.splits()["tune"]) * 2
    gagal = [item for item in tune if item.get("error")]
    assert len(gagal) == 1
    assert "recall" not in gagal[0]
    assert gate.median(tune, "recall") == 0.40


# -- M7: reviewer sebagai pengusul patch ------------------------------------


def _review(patch: str = "", verdict: str = "revise") -> reviewer.Review:
    return reviewer.Review(
        verdict=verdict,
        reason="kasus tune kehilangan jangkar karena rasio ditulis sebagai desimal",
        findings=(
            reviewer.Finding(
                file="prompts/style.md", issue="rasio ditulis desimal", severity="high"
            ),
        ),
        patch=patch,
    )


def test_evolve_promotes_reviewer_patch(siap: tuple[Path, Path, dict]) -> None:
    root, repo, lock = siap
    bench = FakeBench(root.parent, {**_skor(["repo"], 0.40), **_skor(["r01"], 0.70)})
    orch = _orch(root, repo, bench)
    orch.measure_baseline(repo)

    hasil = orch.evolve(repo, lambda konteks: _review(_patch()), rounds=1)

    assert [item.verdict for item in hasil] == ["promoted"]
    assert (root / "worktrees" / "r01").is_dir()
    assert ledger.last(root / ledger.LEDGER_FILE)["variant_id"] == "r01"
    assert ledger.last(root / ledger.LEDGER_FILE)["layer"] == "prompt"


def test_evolve_stops_when_reviewer_finds_nothing(siap: tuple[Path, Path, dict]) -> None:
    root, repo, lock = siap
    bench = FakeBench(root.parent, _skor(["repo"], 0.40))
    orch = _orch(root, repo, bench)
    orch.measure_baseline(repo)

    hasil = orch.evolve(repo, lambda konteks: _review(verdict="approve"), rounds=1)

    assert hasil == []
    assert ledger.last(root / ledger.LEDGER_FILE)["verdict"] == "rejected"
    assert not (root / "worktrees" / "r01").exists()


def test_evolve_records_bad_reviewer_answer(siap: tuple[Path, Path, dict]) -> None:
    root, repo, lock = siap
    bench = FakeBench(root.parent, _skor(["repo"], 0.40))
    orch = _orch(root, repo, bench)
    orch.measure_baseline(repo)

    def proposer(konteks: dict) -> reviewer.Review:
        raise reviewer.ReviewError("jawaban reviewer bukan JSON")

    hasil = orch.evolve(repo, proposer, rounds=1)

    assert [item.verdict for item in hasil] == ["unexpected"]
    assert "reviewer" in hasil[0].reason
    assert ledger.last(root / ledger.LEDGER_FILE)["verdict"] == "unexpected"


def test_second_round_builds_on_promoted_branch(siap: tuple[Path, Path, dict]) -> None:
    root, repo, lock = siap
    bench = FakeBench(
        root.parent,
        {**_skor(["repo"], 0.40), **_skor(["r01"], 0.70), **_skor(["r02"], 0.90)},
    )
    orch = _orch(root, repo, bench)
    orch.measure_baseline(repo)
    dilihat: list[str] = []

    def proposer(konteks: dict) -> reviewer.Review:
        dilihat.append(konteks["parent"])
        return _review(_patch())

    hasil = orch.evolve(repo, proposer, rounds=2)

    assert [item.verdict for item in hasil] == ["promoted", "promoted"]
    assert dilihat == ["eval/base", "eval/r01"]
    assert "eval/r02" in _git(repo, "branch", "--list", "eval/r02")


def test_context_carries_scores_scope_and_files(siap: tuple[Path, Path, dict]) -> None:
    root, repo, lock = siap
    orch = _orch(root, repo, FakeBench(root.parent, {}))

    konteks = orch.context(
        repo,
        [{"case_id": "t01", "recall": 0.5, "sources": ["laporan.md"], "defects": [{"a": 1}]}],
        "eval/base",
    )

    assert konteks["scope"]["allowed"] == list(patcher.ALLOWED)
    assert konteks["scores"][0]["recall"] == 0.5
    assert "sources" not in konteks["scores"][0]
    assert "prompts/style.md" in konteks["files"]
    assert all(
        path.startswith(patcher.ALLOWED) for path in konteks["files"]
    )


# -- jalur subprocess: path absolut dan galat yang bisa dilacak --------------


def test_pinned_scorer_memakai_path_absolut(
    siap: tuple[Path, Path, dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Skorer berjalan dengan `cwd` di direktori pin, jadi path relatif salah.

    `--root evals` yang relatif akan dicari di bawah direktori pin: truth tidak
    ditemukan dan semua run tercatat gagal meski run-nya sendiri selesai.
    """
    root, repo, lock = siap
    tercatat: dict[str, list[str]] = {}

    def run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        tercatat["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")

    monkeypatch.setattr(orchestrator.subprocess, "run", run)
    scorer = orchestrator.pinned_scorer(root / "pins", Path("evals"))

    assert scorer(Path("runs/x"), "trend-01") == {}

    cmd = tercatat["cmd"]
    akar = Path(cmd[cmd.index("--root") + 1])
    direktori_run = Path(cmd[cmd.index("--run") + 1])
    assert akar == Path("evals").resolve()
    assert direktori_run.is_absolute()


def test_run_pipeline_melaporkan_exit_code(
    siap: tuple[Path, Path, dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proses anak yang mati tanpa stderr tetap harus meninggalkan jejak."""
    root, repo, lock = siap

    def run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 3, stdout="", stderr="")

    monkeypatch.setattr(orchestrator.subprocess, "run", run)

    with pytest.raises(orchestrator.OrchestratorError) as info:
        orchestrator.run_pipeline(
            repo,
            "trend-01",
            root / "cases" / "trend-01" / "input",
            0,
            data_root=root / "runs",
        )

    pesan = str(info.value)
    assert "exit 3" in pesan
    assert "tanpa keluaran" in pesan
