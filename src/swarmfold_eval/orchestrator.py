"""Orkestrator satu varian: worktree, patch, replika, skor, keputusan, ledger.

Urutannya sengaja kaku. Ledger diperiksa sebelum apa pun, pin dan split
diperiksa sebelum patch diterapkan, dan skor selalu datang dari salinan
verifier yang terpin — bukan dari `src/` yang baru saja dipatch.

Baseline diukur sekali pada sistem tanpa patch (`measure_baseline`), disimpan
di `evals/baseline.json`, dan diikat ke digest verifier. Baseline dari verifier
lain tidak boleh dipakai membandingkan; angkanya tidak sebanding.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from swarmfold_verify import cases, pins
from swarmfold_verify import split as splits

from . import gate, ledger, patcher

BASELINE_FILE = "baseline.json"
BASELINE_SCHEMA = 1

#: (worktree, case_id, input_dir, replika) -> direktori run.
Runner = Callable[[Path, str, Path, int], Path]
#: (direktori run, case_id) -> skor dari verifier terpin.
Scorer = Callable[[Path, str], dict[str, Any]]


class OrchestratorError(RuntimeError):
    """Baseline atau konfigurasi tidak bisa dipakai."""


@dataclass(frozen=True)
class Variant:
    variant_id: str
    hypothesis: str
    layer: str
    expected: str
    diff: str
    parent: str = "eval/base"


@dataclass(frozen=True)
class Outcome:
    verdict: str
    reason: str
    entry: dict[str, Any]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def pinned_scorer(pin_root: Path, evals_root: Path) -> Scorer:
    """Skorer yang menjalankan CLI dari salinan terpin, bukan dari `src/`."""

    def score(run_dir: Path, case_id: str) -> dict[str, Any]:
        env = {**os.environ, "PYTHONPATH": str(pin_root)}
        hasil = subprocess.run(
            [
                sys.executable,
                "-m",
                "swarmfold_verify.cli",
                "score",
                "--run",
                str(run_dir),
                "--case",
                case_id,
                "--root",
                str(evals_root),
            ],
            cwd=pin_root,
            capture_output=True,
            text=True,
            env=env,
            timeout=600,
            check=False,
        )
        if hasil.returncode != 0:
            raise OrchestratorError(f"skor gagal untuk {case_id}: {hasil.stderr.strip()}")
        return json.loads(hasil.stdout)

    return score


def run_pipeline(
    worktree: Path, case_id: str, input_dir: Path, replica: int, *, data_root: Path
) -> Path:
    """Jalankan pipeline pada satu kasus di dalam worktree varian.

    Subprocess, bukan panggilan langsung: proses orkestrator sudah meng-import
    `swarmfold` dari checkout utama, jadi menjalankan di sini akan menguji kode
    yang salah.
    """
    env = {
        **os.environ,
        "PYTHONPATH": str(Path(worktree) / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    hasil = subprocess.run(
        [
            sys.executable,
            "-m",
            "swarmfold_eval.runner",
            "--case",
            case_id,
            "--input",
            str(input_dir),
            "--data-root",
            str(data_root),
            "--replica",
            str(replica),
        ],
        cwd=worktree,
        capture_output=True,
        text=True,
        env=env,
        timeout=3600,
        check=False,
    )
    if hasil.returncode != 0:
        raise OrchestratorError(
            f"run {case_id} r{replica} gagal: {hasil.stderr.strip()[-800:]}"
        )
    return Path(json.loads(hasil.stdout.strip().splitlines()[-1])["run_dir"])


class Orchestrator:
    def __init__(
        self,
        root: Path,
        repo: Path,
        runner: Runner | None = None,
        scorer: Scorer | None = None,
        *,
        policy: gate.GatePolicy | None = None,
        replicas: int = 3,
    ) -> None:
        self.root = Path(root)
        self.repo = Path(repo)
        self.runner = runner
        self.scorer = scorer
        self.policy = policy or gate.GatePolicy()
        self.replicas = replicas

    @property
    def ledger_path(self) -> Path:
        return self.root / ledger.LEDGER_FILE

    @property
    def baseline_path(self) -> Path:
        return self.root / BASELINE_FILE

    @property
    def pin_store(self) -> Path:
        return self.root / "pins"

    def lock(self) -> dict[str, Any]:
        return pins.read_lock(self.pin_store / pins.LOCK_NAME)

    # -- pemeriksaan --------------------------------------------------------

    def selftest(self) -> list[str]:
        """Semua invarian yang harus benar sebelum satu varian dinilai."""
        lock = self.lock()
        masalah = [
            f"pin: {item}" for item in pins.verify(pins.snapshot_dir(self.pin_store, lock), lock)
        ]
        sumber = Path(__file__).resolve().parents[1] / pins.PACKAGE
        masalah += [f"pin src: {item}" for item in pins.verify(sumber, lock)]
        masalah += [f"split: {item}" for item in splits.verify(self.root)]
        masalah += [f"ledger: {item}" for item in ledger.verify_chain(self.ledger_path)]
        return masalah

    # -- baseline -----------------------------------------------------------

    def _measure(self, worktree: Path, split_name: str) -> list[dict[str, Any]]:
        if self.runner is None or self.scorer is None:
            raise OrchestratorError("runner dan scorer belum dipasang")
        hasil = []
        kasus = splits.expand(splits.cases_for(self.root, split_name), self.replicas)
        for case_id, replica in kasus:
            run_dir = self.runner(
                worktree, case_id, cases.case_input_dir(case_id, self.root), replica
            )
            hasil.append(self.scorer(run_dir, case_id))
        return hasil

    def measure_baseline(self, worktree: Path) -> dict[str, Any]:
        """Ukur sistem tanpa patch dan simpan; dipakai semua varian sesudahnya."""
        data = {
            "schema": BASELINE_SCHEMA,
            "created_at": _now(),
            "pin": self.lock()["digest"],
            "replicas": self.replicas,
            "splits": {nama: self._measure(worktree, nama) for nama in splits.SELECTABLE},
        }
        self.baseline_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return data

    def baseline(self) -> dict[str, Any]:
        if not self.baseline_path.is_file():
            raise OrchestratorError(
                f"belum ada {self.baseline_path}; jalankan `baseline` lebih dulu"
            )
        data = json.loads(self.baseline_path.read_text(encoding="utf-8"))
        if data.get("schema") != BASELINE_SCHEMA:
            raise OrchestratorError("skema baseline tidak dikenal")
        if data.get("pin") != self.lock()["digest"]:
            raise OrchestratorError("baseline diukur dengan verifier yang berbeda; ukur ulang")
        return data

    # -- satu varian --------------------------------------------------------

    def evaluate(self, variant: Variant) -> Outcome:
        gate.assert_ledger_intact(self.ledger_path)
        masalah = self.selftest()
        if masalah:
            return self._record(variant, "tampered", "; ".join(masalah), {})

        baseline = self.baseline()
        worktree = self.root / "worktrees" / variant.variant_id
        branch = f"eval/{variant.variant_id}"
        gate.create_worktree(self.repo, worktree, branch, variant.parent)
        try:
            patcher.apply(worktree, variant.diff)
        except patcher.ScopeError as error:
            gate.remove_worktree(self.repo, worktree, branch)
            return self._record(variant, "schema_rejected", str(error), {})

        try:
            skor = {nama: self._measure(worktree, nama) for nama in splits.SELECTABLE}
        except Exception as error:  # run gagal tidak boleh mematikan seluruh loop
            gate.remove_worktree(self.repo, worktree, branch)
            return self._record(variant, "unexpected", f"run gagal: {error}", {})

        keputusan = gate.decide(
            self.policy,
            baseline["splits"]["tune"],
            skor["tune"],
            baseline["splits"]["heldout"],
            skor["heldout"],
        )
        hasil = self._record(
            variant,
            keputusan.verdict,
            keputusan.reason,
            {
                "before": {
                    "tune": gate.median(baseline["splits"]["tune"], self.policy.metric),
                    "heldout": gate.median(baseline["splits"]["heldout"], self.policy.metric),
                },
                "after": {"tune": keputusan.tune_after, "heldout": keputusan.heldout_after},
                "guardrails": keputusan.guardrails,
            },
        )
        if keputusan.verdict != "promoted":
            gate.remove_worktree(self.repo, worktree, branch)
        return hasil

    def _record(
        self, variant: Variant, verdict: str, reason: str, ukuran: dict[str, Any]
    ) -> Outcome:
        row = ledger.record(
            self.ledger_path,
            {
                "variant_id": variant.variant_id,
                "parent": variant.parent,
                "hypothesis": variant.hypothesis,
                "layer": variant.layer,
                "files": sorted(patcher._paths(variant.diff)),
                "diff_sha": "sha256:" + hashlib.sha256(variant.diff.encode()).hexdigest(),
                "expected": variant.expected,
                "split": ",".join(splits.SELECTABLE),
                "replicas": self.replicas,
                "before": ukuran.get("before", {}),
                "after": ukuran.get("after", {}),
                "heldout": ukuran.get("guardrails", {}),
                "verdict": verdict,
                "branch": f"eval/{variant.variant_id}",
                "run_ids": [],
                "reason": reason,
            },
        )
        return Outcome(verdict=verdict, reason=reason, entry=row)
