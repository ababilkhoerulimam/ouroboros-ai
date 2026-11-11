from __future__ import annotations

import json
from pathlib import Path

from conftest import ScriptedModel, finish, run_cell, tool_turn
from synthetic import tulis_penjualan

from swarmfold.ingest import ingest
from swarmfold.loop import AgentLoop, Brief, RunOutcome
from swarmfold.multidataset import (
    UnitResult,
    build_done,
    filter_profile,
    merge_reports,
    prepare_unit,
)
from swarmfold.runtime import RunPaths, read_json


def _turns_for_one_unit() -> list:
    """Satu unit: finish (memaksa F7), lalu tulis laporan di kernel.

    Setelah laporan ada, loop menutup unit sendiri di F7, jadi tidak perlu
    giliran finish kedua.
    """
    return [
        tool_turn(finish("partial", "cukup")),
        tool_turn(
            run_cell(
                "open('laporan.md', 'w', encoding='utf-8').write('# Laporan unit')",
                "tulis laporan",
            )
        ),
    ]


def test_multi_dataset_run_writes_unit_notebooks_and_one_report(
    run_dua_berkas: RunPaths, settings
) -> None:
    model = ScriptedModel(_turns_for_one_unit() * 2)

    outcome = AgentLoop(run_dua_berkas, settings, model, Brief()).run()

    assert outcome.report_written
    done = read_json(run_dua_berkas.done_file)
    assert done["mode"] == "multi_dataset"
    assert [item["id"] for item in done["datasets"]] == ["D1", "D2"]
    assert done["deliverables"]["notebook"] == [
        "datasets/D1/analysis.ipynb",
        "datasets/D2/analysis.ipynb",
    ]
    for item in done["datasets"]:
        assert (run_dua_berkas.dir / item["notebook"]).is_file()
        assert (run_dua_berkas.dir / item["report"]).is_file()

    report = run_dua_berkas.report_file.read_text(encoding="utf-8")
    assert "## Kelompok D1" in report
    assert "## Kelompok D2" in report
    assert "## Ringkasan lintas kelompok" in report
    assert "tidak dibandingkan" in report

    status = read_json(run_dua_berkas.status_file)
    assert status["state"] == "done"
    assert [item["id"] for item in status["datasets"]] == ["D1", "D2"]


def test_each_unit_sees_only_its_own_group(run_dua_berkas: RunPaths, settings) -> None:
    class Capturing(ScriptedModel):
        def __init__(self) -> None:
            super().__init__([tool_turn(finish("partial", "cukup")) for _ in range(4)])
            self.openings: list[str] = []

        def chat(self, messages: list[dict], tools: list[dict] | None = None):
            self.openings.append(str(messages[1]["content"]))
            return super().chat(messages, tools)

    model = Capturing()
    AgentLoop(run_dua_berkas, settings, model, Brief()).run()

    openings = list(dict.fromkeys(model.openings))
    assert any("D1: penjualan.csv" in text for text in openings)
    assert any("D2: pelanggan.csv" in text for text in openings)
    for text in openings:
        assert "Lingkup unit" in text
        assert "Analisis kelompok ini saja" in text
    d1 = next(text for text in openings if "D1: penjualan.csv" in text)
    assert "D2: pelanggan.csv" not in d1


def test_unit_profile_drops_other_files_and_joins(run_dua_berkas: RunPaths) -> None:
    profile = read_json(run_dua_berkas.profile_file)
    dataset = profile["datasets"][0]

    unit_profile = filter_profile(profile, dataset)

    assert [item["name"] for item in unit_profile["files"]] == dataset["files"]
    assert unit_profile["datasets"] == [dataset]
    assert all(
        join["left"] in dataset["files"] and join["right"] in dataset["files"]
        for join in unit_profile["joins"]
    )


def test_prepare_unit_links_data_and_writes_profile(run_dua_berkas: RunPaths) -> None:
    profile = read_json(run_dua_berkas.profile_file)
    dataset = profile["datasets"][0]

    unit = prepare_unit(run_dua_berkas, dataset, profile)

    assert unit.dir == run_dua_berkas.dir / "datasets" / dataset["id"]
    assert sorted(path.name for path in unit.data_dir.iterdir()) == sorted(
        path.name for path in run_dua_berkas.data_dir.iterdir()
    )
    assert read_json(unit.profile_file)["datasets"] == [dataset]


def test_merged_report_rebases_unit_paths(run_dua_berkas: RunPaths) -> None:
    profile = read_json(run_dua_berkas.profile_file)
    dataset = profile["datasets"][0]
    unit = prepare_unit(run_dua_berkas, dataset, profile)
    unit.report_file.write_text(
        "# Laporan\n\n![tren](charts/F2_001_tren.png)\n\n"
        "Angka dari `cells/019.out.txt` dan evidence/F2.json.\n",
        encoding="utf-8",
    )
    outcome = RunOutcome("ok", "selesai", 1, 0, 1)

    merge_reports(run_dua_berkas, [UnitResult(dataset, unit, outcome)])

    report = run_dua_berkas.report_file.read_text(encoding="utf-8")
    assert "datasets/D1/charts/F2_001_tren.png" in report
    assert "datasets/D1/cells/019.out.txt" in report
    assert "datasets/D1/evidence/F2.json" in report
    assert "](charts/" not in report


def test_missing_unit_report_is_declared(run_dua_berkas: RunPaths) -> None:
    profile = read_json(run_dua_berkas.profile_file)
    dataset = profile["datasets"][0]
    unit = prepare_unit(run_dua_berkas, dataset, profile)
    outcome = RunOutcome("failed", "tidak terbit", 0, 0, 0)

    merge_reports(run_dua_berkas, [UnitResult(dataset, unit, outcome)])

    report = run_dua_berkas.report_file.read_text(encoding="utf-8")
    assert "tidak terbit" in report


def test_done_lists_each_dataset_deliverable(run_dua_berkas: RunPaths) -> None:
    profile = read_json(run_dua_berkas.profile_file)
    dataset = profile["datasets"][0]
    unit = prepare_unit(run_dua_berkas, dataset, profile)
    unit.notebook_file.write_text(json.dumps({"cells": []}), encoding="utf-8")
    unit.report_file.write_text("# laporan\n", encoding="utf-8")
    unit.done_file.write_text(
        json.dumps(
            {
                "status": "ok",
                "pack": "business",
                "phases_completed": ["F1"],
                "verification": {"rerun": "skipped", "mismatches": []},
            }
        ),
        encoding="utf-8",
    )
    outcome = RunOutcome("ok", "selesai", 1, 0, 0)

    done = build_done(run_dua_berkas, [UnitResult(dataset, unit, outcome)], pack="business")

    assert done["datasets"][0]["notebook"] == "datasets/D1/analysis.ipynb"
    assert done["deliverables"]["notebook"] == ["datasets/D1/analysis.ipynb"]
    assert done["pack"] == "business"
    assert done["status"] == "ok"


def test_done_reports_mixed_pack_when_units_differ(run_dua_berkas: RunPaths) -> None:
    profile = read_json(run_dua_berkas.profile_file)
    units = []
    for dataset, pack in zip(profile["datasets"], ("business", "generic"), strict=False):
        unit = prepare_unit(run_dua_berkas, dataset, profile)
        unit.done_file.write_text(
            json.dumps(
                {
                    "status": "ok",
                    "pack": pack,
                    "phases_completed": ["F1"],
                    "verification": {"rerun": "skipped", "mismatches": []},
                }
            ),
            encoding="utf-8",
        )
        units.append(UnitResult(dataset, unit, RunOutcome("ok", "selesai", 1, 0, 0)))

    done = build_done(run_dua_berkas, units, pack="business")

    assert done["pack"] == "mixed"


def test_small_group_does_not_stop_the_run(tmp_path: Path, settings) -> None:
    paths = RunPaths(settings.data_root, "2026-01-01-kecil").ensure()
    mini = tmp_path / "mini.csv"
    mini.write_text("a,b\n1,2\n", encoding="utf-8")
    ingest([tulis_penjualan(tmp_path / "penjualan.csv"), mini], paths)

    outcome = AgentLoop(paths, settings, ScriptedModel(_turns_for_one_unit()), Brief()).run()

    done = read_json(paths.done_file)
    assert {item["id"]: item["status"] for item in done["datasets"]} == {
        "D1": "partial",
        "D2": "failed",
    }
    small = paths.child("D2").report_file
    assert small.is_file()
    assert "Data belum siap" in small.read_text(encoding="utf-8")
    merged = paths.report_file.read_text(encoding="utf-8")
    assert "## Kelompok D1" in merged
    assert "## Kelompok D2" in merged
    assert outcome.status == "failed"
