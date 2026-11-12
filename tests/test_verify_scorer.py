"""Tes scorer dan CLI verifier.

Fokusnya dua hal yang menentukan apakah skor bisa dipakai sebagai dasar seleksi:
metriknya menghitung apa yang diklaim, dan scorer tidak pernah membaca truth
dari dalam run tree (kalau bisa, run dapat menyelundupkan jawaban sendiri).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarmfold_verify import cli, scorer
from swarmfold_verify.truth import Anchor, Case


def _finding(
    ident: str,
    value: float,
    unit: str = "ratio",
    confidence: str = "high",
    display: str | None = None,
) -> dict:
    return {
        "id": ident,
        "statement": "temuan uji",
        "value": value,
        "unit": unit,
        "cell": 1,
        "artifact": f"cells/{ident}.txt",
        "dataset_hash": "h",
        "verified": True,
        "confidence": confidence,
        "display": f"{value * 100:.2f}%" if display is None else display,
    }


def _run(tmp_path: Path, findings: list[dict], laporan: str = "# Laporan\n") -> Path:
    run = tmp_path / "run"
    (run / "evidence").mkdir(parents=True, exist_ok=True)
    (run / "evidence" / "F2.json").write_text(
        json.dumps(
            {
                "phase": "F2",
                "question": "",
                "findings": findings,
                "hypotheses": [],
                "anomalies": [],
                "cannot_answer": [],
            }
        ),
        encoding="utf-8",
    )
    (run / "laporan.md").write_text(laporan, encoding="utf-8")
    (run / "done.json").write_text(json.dumps({"phases_completed": ["F2"]}), encoding="utf-8")
    for finding in findings:
        path = run / finding["artifact"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(finding.get("display") or ""), encoding="utf-8")
    return run


def _case(*anchors: Anchor) -> Case:
    return Case(case_id="uji-01", split="tune", seed=1, anchors=anchors)


def _patch_artifact(run: Path, ident: str, artifact: str) -> None:
    """Ganti `artifact` satu finding setelah run ditulis."""
    path = run / "evidence" / "F2.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for finding in data["findings"]:
        if finding["id"] == ident:
            finding["artifact"] = artifact
    path.write_text(json.dumps(data), encoding="utf-8")


def test_recall_two_of_three(tmp_path: Path) -> None:
    case = _case(
        Anchor("A1", "trend", 0.08, "ratio", 0.02),
        Anchor("A2", "count", 100, "count", 0.01),
        Anchor("A3", "tail", 0.415, "ratio", 0.01),
    )
    run = _run(tmp_path, [_finding("E-001", 0.081), _finding("E-002", 100, "count")])

    hasil = scorer.score(run, case)

    assert hasil["recall"] == pytest.approx(2 / 3, abs=1e-6)
    assert hasil["matched"] == ["A1", "A2"]
    assert hasil["missed"] == ["A3"]


def test_numeric_tolerance_zero_error(tmp_path: Path) -> None:
    case = _case(Anchor("A1", "trend", 0.08, "ratio", 0.02))
    run = _run(tmp_path, [_finding("E-001", 0.08)])

    hasil = scorer.score(run, case)

    assert hasil["numeric_error"] == {"median_rel": 0.0, "worst_rel": 0.0, "n": 1}


def test_numeric_error_uses_nearest_finding(tmp_path: Path) -> None:
    case = _case(Anchor("A1", "trend", 1.0, "count", 0.10))
    run = _run(tmp_path, [_finding("E-001", 1.06, "count"), _finding("E-002", 1.02, "count")])

    hasil = scorer.score(run, case)

    assert hasil["numeric_error"]["worst_rel"] == pytest.approx(0.02, abs=1e-6)


def test_false_discovery_counts_contradiction(tmp_path: Path) -> None:
    case = _case(
        Anchor("A1", "trend", 0.08, "ratio", 0.02),
        Anchor("A2", "count", 100, "count", 0.01),
        Anchor("A3", "trend", -0.30, "ratio", 0.02),
    )
    run = _run(
        tmp_path,
        [_finding("E-001", 0.08), _finding("E-002", 100, "count"), _finding("E-003", 0.30)],
    )

    hasil = scorer.score(run, case)

    assert hasil["recall"] == pytest.approx(2 / 3, abs=1e-6)
    assert hasil["false_discovery"] == pytest.approx(1 / 3, abs=1e-6)
    assert [item["anchor"] for item in hasil["contradictions"]] == ["A3"]


def test_unit_mismatch_is_not_a_match(tmp_path: Path) -> None:
    case = _case(Anchor("A1", "count", 100, "count", 0.01))
    run = _run(tmp_path, [_finding("E-001", 100, "IDR")])

    hasil = scorer.score(run, case)

    assert hasil["recall"] == 0.0
    assert hasil["false_discovery"] == 1.0


def test_defect_rate_flags_multi_number_display(tmp_path: Path) -> None:
    finding = _finding("E-001", 0.08, display="naik 8,00% dari 100 menjadi 108")
    run = _run(tmp_path, [finding])
    # Artifact hanya memuat angka pertama: persis celah yang ditutup checks.py.
    (run / "cells" / "E-001.txt").write_text("8,00%", encoding="utf-8")

    hasil = scorer.score(run, _case(Anchor("A1", "trend", 0.08, "ratio", 0.02)))

    assert hasil["defect_rate"] > 0
    assert {item["kind"] for item in hasil["defects"]} == {"multi_number_display"}


def test_ratio_percent_matches_artifact_ratio(tmp_path: Path) -> None:
    """`84,13%` sah untuk artifact `zero_ratio=0.8413` — jangan dilaporkan cacat."""
    run = _run(tmp_path, [_finding("E-001", 0.8413)])
    (run / "cells" / "E-001.txt").write_text("zero_ratio=0.8413", encoding="utf-8")

    hasil = scorer.score(run, _case(Anchor("A1", "trend", 0.8413, "ratio", 0.01)))

    assert hasil["defects"] == []


def test_scaled_display_matches_artifact(tmp_path: Path) -> None:
    """`Rp 362,4 juta` sah untuk artifact `362400000`."""
    finding = _finding("E-001", 362400000.0, unit="IDR", display="Rp 362,4 juta")
    run = _run(tmp_path, [finding])
    (run / "cells" / "E-001.txt").write_text("total=362400000", encoding="utf-8")

    hasil = scorer.score(run, _case(Anchor("A1", "trend", 362400000.0, "IDR", 0.01)))

    assert hasil["defects"] == []


def test_display_contradicting_value_is_flagged(tmp_path: Path) -> None:
    run = _run(tmp_path, [_finding("E-001", 0.08, display="9,00%")])
    (run / "cells" / "E-001.txt").write_text("ratio=0.0800", encoding="utf-8")

    hasil = scorer.score(run, _case(Anchor("A1", "trend", 0.08, "ratio", 0.02)))

    assert [item["kind"] for item in hasil["defects"]] == ["unsupported_number"]


def test_duplicate_rate_counts_copies(tmp_path: Path) -> None:
    run = _run(tmp_path, [_finding("E-001", 0.08), _finding("E-002", 0.08)])

    hasil = scorer.score(run, _case(Anchor("A1", "trend", 0.08, "ratio", 0.02)))

    assert hasil["duplicate_rate"] == pytest.approx(0.5)


def test_calibration_rewards_honest_confidence(tmp_path: Path) -> None:
    case = _case(Anchor("A1", "trend", 0.08, "ratio", 0.02))
    jujur = _run(
        tmp_path / "jujur",
        [_finding("E-001", 0.08, confidence="high"), _finding("E-002", 0.5, confidence="low")],
    )
    sombong = _run(
        tmp_path / "sombong",
        [_finding("E-001", 0.08, confidence="low"), _finding("E-002", 0.5, confidence="high")],
    )

    assert scorer.score(jujur, case)["calibration"]["brier"] < (
        scorer.score(sombong, case)["calibration"]["brier"]
    )


def test_scorer_reads_nothing_outside_run_dir(tmp_path: Path) -> None:
    case = _case(Anchor("A1", "trend", 0.08, "ratio", 0.02))
    run = _run(tmp_path, [_finding("E-001", 0.08)])

    pertama = scorer.score(run, case)
    for source in pertama["sources"]:
        assert not source.startswith("..")
        assert (run / source).is_file()

    # Truth palsu di dalam run tree tidak boleh mengubah skor.
    (run / "truth").mkdir()
    (run / "truth" / "uji-01.json").write_text(
        json.dumps({"case_id": "uji-01", "split": "tune", "seed": 1, "anchors": []}),
        encoding="utf-8",
    )
    assert scorer.score(run, case) == pertama


def test_empty_run_scores_zero_without_crashing(tmp_path: Path) -> None:
    run = tmp_path / "kosong"
    run.mkdir()

    hasil = scorer.score(run, _case(Anchor("A1", "trend", 0.08, "ratio", 0.02)))

    assert hasil["recall"] == 0.0
    assert hasil["numeric_error"] == {"median_rel": None, "worst_rel": None, "n": 0}
    assert hasil["calibration"] == {"brier": None, "n": 0}
    # Tanpa temuan, kedua pecahan tidak terdefinisi — bukan sempurna.
    assert hasil["false_discovery"] is None
    assert hasil["defect_rate"] is None
    assert {item["kind"] for item in hasil["run_defects"]} == {"missing_report", "missing_done"}


def test_run_defects_are_not_diluted_by_findings(tmp_path: Path) -> None:
    """Laporan hilang tetap cacat run, berapa pun temuan yang dihasilkan."""
    run = _run(tmp_path, [_finding(f"E-{index:03d}", 0.08) for index in range(1, 21)])
    (run / "laporan.md").unlink()

    hasil = scorer.score(run, _case(Anchor("A1", "trend", 0.08, "ratio", 0.02)))

    assert hasil["defect_rate"] == 0.0
    assert [item["kind"] for item in hasil["run_defects"]] == ["missing_report"]


def test_artifact_outside_run_is_rejected(tmp_path: Path) -> None:
    """`artifact` tidak boleh membawa scorer keluar dari run tree."""
    luar = tmp_path / "luar.txt"
    luar.write_text("9.0000", encoding="utf-8")
    run = _run(tmp_path, [_finding("E-001", 0.08, display="9,00%")])
    _patch_artifact(run, "E-001", str(luar.resolve()))

    hasil = scorer.score(run, _case(Anchor("A1", "trend", 0.08, "ratio", 0.02)))

    assert [item["kind"] for item in hasil["defects"]] == ["artifact_outside_run"]
    assert luar.name not in " ".join(hasil["sources"])
    assert all(not Path(source).is_absolute() for source in hasil["sources"])


def test_corrupt_artifacts_do_not_crash(tmp_path: Path) -> None:
    run = _run(tmp_path, [_finding("E-001", 0.08)])
    (run / "done.json").write_text("[1, 2, 3]", encoding="utf-8")
    (run / "evidence" / "F2.json").write_bytes(b"\xff\xfe\x00rusak")

    hasil = scorer.score(run, _case(Anchor("A1", "trend", 0.08, "ratio", 0.02)))

    assert hasil["n_findings"] == 0
    assert {item["kind"] for item in hasil["run_defects"]} == {"corrupt_done"}


def test_cli_build_then_score(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "evals"
    assert cli.main(["build", "--root", str(root)]) == 0
    assert json.loads(capsys.readouterr().out)["splits"]["tune"]

    run = _run(tmp_path, [_finding("E-001", 0.08)])
    out = tmp_path / "skor.json"
    kode = cli.main(
        ["score", "--run", str(run), "--case", "trend-01", "--root", str(root), "--out", str(out)]
    )
    assert kode == 0
    assert json.loads(out.read_text(encoding="utf-8"))["case_id"] == "trend-01"


def test_cli_score_without_truth_exits_two(tmp_path: Path) -> None:
    run = _run(tmp_path, [])
    kode = cli.main(["score", "--run", str(run), "--case", "tidak-ada", "--root", str(tmp_path)])
    assert kode == 2


def test_cli_check_exits_one_on_defect(tmp_path: Path) -> None:
    run = _run(tmp_path, [], laporan="# Laporan\n\n{{E-999}}\n")
    assert cli.main(["check", "--run", str(run)]) == 1
