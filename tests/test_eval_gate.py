"""Tes gerbang promosi dan worktree.

Gerbang harus menolak kenaikan yang rapuh: satu replika bagus tidak boleh
menutupi dua replika buruk (karena itu median), dan run kosong tidak boleh
lolos lewat metrik yang tidak terdefinisi.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from swarmfold_eval import gate, ledger


def _scores(**metrics: list[float | None]) -> list[dict]:
    """Skor run; guardrail default nol supaya tidak mengganggu tes lain."""
    jumlah = len(next(iter(metrics.values())))
    dasar: dict = {"false_discovery": [0.0] * jumlah, "defect_rate": [0.0] * jumlah}
    dasar.update(metrics)
    return [{nama: nilai[index] for nama, nilai in dasar.items()} for index in range(jumlah)]


def _policy(**ubah: object) -> gate.GatePolicy:
    dasar: dict = {"metric": "recall", "min_delta": 0.10, "max_regression": 0.02}
    dasar.update(ubah)
    return gate.GatePolicy(**dasar)


def test_promoted_when_median_rises() -> None:
    hasil = gate.decide(
        _policy(),
        tune_before=_scores(recall=[0.40, 0.42, 0.41]),
        tune_after=_scores(recall=[0.60, 0.61, 0.59]),
        heldout_before=_scores(recall=[0.50]),
        heldout_after=_scores(recall=[0.55]),
    )

    assert hasil.verdict == "promoted"
    assert hasil.tune_after == pytest.approx(0.60)


def test_regression_when_tune_drops() -> None:
    hasil = gate.decide(
        _policy(),
        tune_before=_scores(recall=[0.60]),
        tune_after=_scores(recall=[0.50]),
        heldout_before=_scores(recall=[0.50]),
        heldout_after=_scores(recall=[0.50]),
    )

    assert hasil.verdict == "regressed"


def test_regression_when_heldout_drops() -> None:
    hasil = gate.decide(
        _policy(),
        tune_before=_scores(recall=[0.50]),
        tune_after=_scores(recall=[0.70]),
        heldout_before=_scores(recall=[0.60]),
        heldout_after=_scores(recall=[0.40]),
    )

    assert hasil.verdict == "regressed"
    assert "heldout" in hasil.reason


def test_guardrail_blocks_promotion() -> None:
    hasil = gate.decide(
        _policy(),
        tune_before=_scores(recall=[0.40], defect_rate=[0.02]),
        tune_after=_scores(recall=[0.70], defect_rate=[0.30]),
        heldout_before=_scores(recall=[0.40]),
        heldout_after=_scores(recall=[0.70]),
    )

    assert hasil.verdict == "rejected"
    assert "guardrail" in hasil.reason
    assert hasil.guardrails == {"defect_rate": 0.30}


def test_none_metric_counts_as_worst() -> None:
    """Run tanpa temuan: defect_rate `None` harus menggagalkan guardrail."""
    hasil = gate.decide(
        _policy(),
        tune_before=_scores(recall=[0.40], defect_rate=[0.0]),
        tune_after=_scores(recall=[0.70], defect_rate=[None]),
        heldout_before=_scores(recall=[0.40]),
        heldout_after=_scores(recall=[0.70]),
    )

    assert hasil.verdict == "rejected"
    assert hasil.guardrails["defect_rate"] == gate.WORST


def test_median_not_mean() -> None:
    """Satu replika sempurna tidak boleh menutupi dua yang biasa saja."""
    hasil = gate.decide(
        _policy(),
        tune_before=_scores(recall=[0.90, 0.90, 0.90]),
        tune_after=_scores(recall=[0.90, 0.90, 0.90]),
        heldout_before=_scores(recall=[0.90]),
        heldout_after=_scores(recall=[0.90]),
    )

    assert hasil.verdict == "rejected"


def test_small_gain_is_rejected() -> None:
    hasil = gate.decide(
        _policy(),
        tune_before=_scores(recall=[0.50]),
        tune_after=_scores(recall=[0.55]),
        heldout_before=_scores(recall=[0.50]),
        heldout_after=_scores(recall=[0.55]),
    )

    assert hasil.verdict == "rejected"
    assert "min_delta" in hasil.reason


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
    (repo / "README.md").write_bytes(b"awal\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "awal")
    _git(repo, "branch", "eval/base")
    return repo


def test_create_and_remove_worktree(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    worktree = repo / "evals" / "worktrees" / "v001"

    gate.create_worktree(repo, worktree, "eval/v001")
    assert (worktree / "README.md").is_file()
    assert "eval/v001" in _git(repo, "branch", "--list", "eval/v001")

    gate.remove_worktree(repo, worktree, "eval/v001")
    assert not worktree.exists()
    assert _git(repo, "branch", "--list", "eval/v001").strip() == ""


def test_regression_removes_branch(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    worktree = repo / "evals" / "worktrees" / "v002"
    gate.create_worktree(repo, worktree, "eval/v002")

    hasil = gate.decide(
        _policy(),
        tune_before=_scores(recall=[0.60]),
        tune_after=_scores(recall=[0.40]),
        heldout_before=_scores(recall=[0.60]),
        heldout_after=_scores(recall=[0.40]),
    )
    assert hasil.verdict == "regressed"
    gate.remove_worktree(repo, worktree, "eval/v002")

    assert _git(repo, "branch", "--list", "eval/v002").strip() == ""


def test_create_worktree_without_base_fails(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    with pytest.raises(gate.GateError):
        gate.create_worktree(repo, repo / "wt", "eval/v003", base="tidak-ada")


def test_tampered_ledger_stops_the_gate(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger.record(path, {"variant_id": "v1"})
    isi = path.read_text(encoding="utf-8").replace('"v1"', '"v9"')
    path.write_text(isi, encoding="utf-8")

    with pytest.raises(gate.GateError, match="tidak utuh"):
        gate.assert_ledger_intact(path)
