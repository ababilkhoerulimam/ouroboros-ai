"""Gerbang promosi dan worktree sekali pakai.

Keputusan promosi memakai **median**, bukan rata-rata: skor run punya ekor
panjang (satu run bisa gagal total), dan rata-rata membuat satu kegagalan
terlihat seperti penurunan mutu yang merata.

Metrik yang tidak terdefinisi (`None`, mis. `defect_rate` saat run tidak
menghasilkan temuan) dihitung sebagai nilai terburuk. Kalau dianggap nol, run
kosong akan lolos gerbang dengan nilai sempurna.
"""

from __future__ import annotations

import statistics
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import ledger

#: Nilai pengganti untuk metrik `None`. Skala semua metrik 0..1.
WORST = 1.0


class GateError(RuntimeError):
    """Worktree atau branch tidak bisa dibuat/dihapus."""


@dataclass(frozen=True)
class GatePolicy:
    metric: str = "recall"
    min_delta: float = 0.10
    max_regression: float = 0.02
    guardrails: dict[str, float] = field(
        default_factory=lambda: {"false_discovery": 0.05, "defect_rate": 0.10}
    )


@dataclass(frozen=True)
class Decision:
    verdict: str
    reason: str
    tune_before: float
    tune_after: float
    heldout_before: float
    heldout_after: float
    guardrails: dict[str, float]


def median(scores: list[dict[str, Any]], metric: str) -> float:
    """Median satu metrik; `None` dihitung sebagai terburuk."""
    angka = [WORST if item.get(metric) is None else float(item[metric]) for item in scores]
    return statistics.median(angka) if angka else WORST


def decide(
    policy: GatePolicy,
    tune_before: list[dict[str, Any]],
    tune_after: list[dict[str, Any]],
    heldout_before: list[dict[str, Any]],
    heldout_after: list[dict[str, Any]],
) -> Decision:
    """Putuskan satu varian: promosi, penolakan, atau regresi."""
    tb = median(tune_before, policy.metric)
    ta = median(tune_after, policy.metric)
    hb = median(heldout_before, policy.metric)
    ha = median(heldout_after, policy.metric)
    pelanggaran = {
        nama: median(tune_after, nama)
        for nama, batas in policy.guardrails.items()
        if median(tune_after, nama) > batas
    }

    def hasil(verdict: str, alasan: str) -> Decision:
        return Decision(verdict, alasan, tb, ta, hb, ha, pelanggaran)

    if ta < tb - policy.max_regression:
        return hasil("regressed", f"{policy.metric} tune turun {tb:.3f} -> {ta:.3f}")
    if ha < hb - policy.max_regression:
        return hasil("regressed", f"{policy.metric} heldout turun {hb:.3f} -> {ha:.3f}")
    if pelanggaran:
        rinci = ", ".join(f"{nama}={nilai:.3f}" for nama, nilai in sorted(pelanggaran.items()))
        return hasil("rejected", f"guardrail dilanggar: {rinci}")
    if ta >= tb + policy.min_delta:
        return hasil("promoted", f"{policy.metric} tune naik {tb:.3f} -> {ta:.3f}")
    return hasil(
        "rejected",
        f"kenaikan {ta - tb:+.3f} di bawah min_delta {policy.min_delta:.3f}",
    )


def assert_ledger_intact(path: Path) -> None:
    """Dipanggil sebelum keputusan apa pun: catatan yang bisa diedit bukan catatan."""
    masalah = ledger.verify_chain(path)
    if masalah:
        raise GateError("ledger tidak utuh: " + "; ".join(masalah))


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, timeout=120, check=False
    )
    if result.returncode != 0:
        raise GateError(f"git {' '.join(args)} gagal: {result.stderr.decode('utf-8', 'replace')}")
    return result.stdout.decode("utf-8", "surrogateescape")


def create_worktree(repo: Path, worktree: Path, branch: str, base: str = "eval/base") -> Path:
    """Worktree + branch baru dari `base`, terpisah dari checkout utama."""
    Path(worktree).parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", str(worktree), "-b", branch, base)
    return Path(worktree)


def remove_worktree(repo: Path, worktree: Path, branch: str) -> None:
    """Buang worktree dan branch; dipakai saat varian tidak dipromosikan."""
    _git(repo, "worktree", "remove", "--force", str(worktree))
    _git(repo, "branch", "-D", branch)
    _git(repo, "worktree", "prune")
