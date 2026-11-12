"""Tes provenance: setiap run bisa diatribusikan ke kebijakan dan model yang dipakai.

Kontrak yang diuji berasal dari rencana evolusi M1: tanpa versi kebijakan, model
aktual, dan sampling yang tercatat, dua run tidak bisa dibandingkan sehingga
seleksi patch tidak punya dasar.
"""

from __future__ import annotations

import json

from conftest import ScriptedModel, finish, tool_turn

from swarmfold.loop import AgentLoop, Brief
from swarmfold.phases import PromptLibrary
from swarmfold.provenance import write_provenance
from swarmfold.runtime import RunPaths, StatusStore, read_json


def test_provenance_has_all_sections(run: RunPaths, settings) -> None:
    StatusStore(run).create(model={"requested": settings.model, "returned": ""})

    data = write_provenance(run, settings, prompt_fingerprint="sha256:abc", pack="business")

    assert data["schema"] == 1
    assert data["run_id"] == run.run_id
    assert {"image", "build_sha", "git_sha"} <= set(data["build"])
    assert data["prompts"]["fingerprint"] == "sha256:abc"
    assert data["prompts"]["pack"] == "business"
    assert data["model"]["requested"] == settings.model
    assert data["settings"]["model"] == settings.model
    assert (run.dir / "provenance.json").exists()


def test_provenance_records_input_hashes(run: RunPaths, settings) -> None:
    StatusStore(run).create(
        inputs=[{"name": "penjualan.csv", "sha256": "deadbeef", "bytes": 10}]
    )

    data = write_provenance(run, settings)

    assert data["inputs"][0]["sha256"] == "deadbeef"


def test_provenance_is_idempotent(run: RunPaths, settings) -> None:
    StatusStore(run).create()

    first = write_provenance(run, settings)
    second = write_provenance(run, settings)

    assert first["run_id"] == second["run_id"]
    stored = json.loads((run.dir / "provenance.json").read_text(encoding="utf-8"))
    assert stored["schema"] == 1
    # Penulisan terakhir menang, dan isinya sama dengan nilai yang dikembalikan.
    assert stored["prompts"] == second["prompts"]
    assert stored["build"] == second["build"]


def test_run_backfills_inputs_env_and_records_returned_model(run: RunPaths, settings) -> None:
    # Jalur API membuat status.json lebih dulu, tanpa env dan inputs.
    StatusStore(run).create(model={"requested": settings.model, "returned": ""})
    turn = tool_turn(finish("ok", "selesai"))
    turn.model_returned = "gemini-3.8-flash-n"

    AgentLoop(run, settings, ScriptedModel([turn]), Brief()).run()

    status = read_json(run.status_file, {})
    assert status["inputs"], "inputs tidak diisi ulang dari profile.json"
    assert status["env"].get("python"), "env tidak diisi ulang"
    assert status["model"]["returned"] == "gemini-3.8-flash-n"


def test_prompt_fingerprint_differs_per_pack() -> None:
    business = PromptLibrary(pack="business").fingerprint()
    generic = PromptLibrary(pack="generic").fingerprint()

    assert business.startswith("sha256:")
    assert business != generic, "pack berbeda harus punya fingerprint berbeda"


def test_prompt_fingerprint_stable_across_instances() -> None:
    first = PromptLibrary(pack="business").fingerprint()
    second = PromptLibrary(pack="business").fingerprint()

    assert first == second, "fingerprint tidak boleh berubah antar instance"


def test_prompt_fingerprint_changes_when_file_content_changes(tmp_path) -> None:
    # Janji inti M1: perubahan kebijakan harus mengubah sidik jari. Tanpa tes
    # ini, fingerprint bisa mengabaikan isi berkas dan tetap lulus.
    (tmp_path / "system.md").write_text("aturan lama", encoding="utf-8")
    before = PromptLibrary(prompts_dir=tmp_path, pack="business").fingerprint()

    (tmp_path / "system.md").write_text("aturan baru", encoding="utf-8")
    after = PromptLibrary(prompts_dir=tmp_path, pack="business").fingerprint()

    assert before != after


def test_provenance_written_when_run_raises(run: RunPaths, settings) -> None:
    # Jalur gagal tidak melewati `_finalize`; provenance harus tetap ditulis.
    from swarmfold.api import JobRunner
    from swarmfold.loop import Brief

    def gagal(_settings):
        raise RuntimeError("gateway mati")

    JobRunner(settings, gagal)._run_one(run, Brief())

    stored = json.loads((run.dir / "provenance.json").read_text(encoding="utf-8"))
    assert stored["run_id"] == run.run_id
    assert stored["schema"] == 1
