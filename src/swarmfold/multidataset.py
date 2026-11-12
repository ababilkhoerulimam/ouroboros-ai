"""Eksekusi run multi-kelompok: satu unit per kelompok data.

Kelompok dari `profile.json.datasets` tidak berbagi kunci, sehingga join lintas
kelompok menghasilkan tabel kosong atau fan-out. Run dengan lebih dari satu
kelompok dipecah menjadi sub-run `datasets/<id>/` yang tata letaknya sama persis
dengan run biasa: kernel, notebook, evidence, dan laporan sendiri. Hasilnya
digabung menjadi satu `laporan.md` dan satu `done.json` di akar run.

Penggabungan tidak memanggil model. Kelompok-kelompok ini tidak terhubung, jadi
ringkasan lintas kelompok hanya menyebut jumlah berkas, baris, status, dan
temuan. Tidak ada angka yang dibandingkan antar kelompok.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from typing import Any

from .docx_export import export_docx
from .evidence import EvidenceStore
from .loop import AgentLoop, RunOutcome
from .pdf_export import export_pdf
from .phases import PHASES
from .runtime import (
    RunPaths,
    StatusStore,
    atomic_write_json,
    atomic_write_text,
    read_json,
    utc_now,
)

#: Pola path relatif unit yang harus digeser saat laporan digabung.
_PATH_PREFIX = re.compile(r"(?<![\w/])(charts|cells|evidence|notes|derived)/")


@dataclass
class UnitResult:
    """Hasil satu kelompok: profilnya, direktorinya, dan hasil run-nya."""

    dataset: dict[str, Any]
    paths: RunPaths
    outcome: RunOutcome


def filter_profile(profile: dict[str, Any], dataset: dict[str, Any]) -> dict[str, Any]:
    """Profil run yang dipersempit ke satu kelompok.

    Berkas di luar kelompok dibuang, begitu pula kandidat join yang menyentuhnya,
    supaya model di unit ini tidak punya alasan menyebut kelompok lain.
    """
    names = {str(name) for name in dataset.get("files") or []}
    files = [
        item
        for item in profile.get("files") or []
        if isinstance(item, dict) and str(item.get("name")) in names
    ]
    joins = [
        item
        for item in profile.get("joins") or []
        if isinstance(item, dict)
        and str(item.get("left")) in names
        and str(item.get("right")) in names
    ]
    return {
        "generated_at": profile.get("generated_at"),
        "files": files,
        "joins": joins,
        "datasets": [dataset],
        "warnings": list(profile.get("warnings") or []),
    }


def prepare_unit(
    run: RunPaths, dataset: dict[str, Any], profile: dict[str, Any]
) -> RunPaths:
    """Siapkan sub-run: data yang sama (tautan keras), profil yang disempitkan."""
    unit = run.child(str(dataset["id"])).ensure()
    _link_data(run, unit)
    atomic_write_json(unit.profile_file, filter_profile(profile, dataset))
    return unit


def _link_data(run: RunPaths, unit: RunPaths) -> None:
    """Tautkan seluruh `data/` run ke unit; jatuh ke salinan bila tautan gagal.

    Unit perlu `data/` sendiri karena semua path dan hash di dalam unit relatif
    terhadap direktorinya. Seluruh berkas ditautkan, bukan hanya milik kelompok
    ini, supaya `dataset_hash` unit sama dengan hash run. Tautan keras tidak
    menggandakan byte; salinan hanya dipakai bila filesystem menolak tautan.
    """
    for source in sorted(run.data_dir.iterdir()):
        if not source.is_file():
            continue
        target = unit.data_dir / source.name
        if target.exists():
            continue
        try:
            os.link(source, target)
        except OSError:
            shutil.copy2(source, target)


def run_multi(
    run: RunPaths,
    settings: Any,
    client: Any,
    brief: Any,
    datasets: list[dict[str, Any]],
) -> RunOutcome:
    """Jalankan satu unit per kelompok, lalu gabungkan hasilnya."""
    profile = read_json(run.profile_file, {}) or {}
    units: list[UnitResult] = []
    for dataset in datasets:
        unit = prepare_unit(run, dataset, profile)
        outcome = AgentLoop(unit, settings, client, brief, dataset=dataset).run()
        units.append(UnitResult(dataset=dataset, paths=unit, outcome=outcome))

    docx_error = merge_reports(run, units)
    done = build_done(run, units, pack=settings.pack)
    atomic_write_json(run.done_file, done)
    if docx_error:
        StatusStore(run).warn(f"report docx: {docx_error}")

    cells = sum(unit.outcome.cells for unit in units)
    evidence = sum(unit.outcome.evidence for unit in units)
    charts = sum(unit.outcome.charts for unit in units)
    # Jalur ini tidak melewati `_finalize`, jadi identitas kebijakan dan model
    # harus diambil dari unit: tanpa itu provenance run akar kosong.
    unit_status = [read_json(unit.paths.status_file, {}) or {} for unit in units]
    hashes = {
        str(unit.dataset.get("id") or index): str(state.get("dataset_hash") or "")
        for index, (unit, state) in enumerate(zip(units, unit_status, strict=True))
        if state.get("dataset_hash")
    }
    returned = next(
        (
            str((state.get("model") or {}).get("returned") or "")
            for state in unit_status
            if (state.get("model") or {}).get("returned")
        ),
        "",
    )
    fingerprint = next(
        (
            str(state.get("prompt_fingerprint") or "")
            for state in unit_status
            if state.get("prompt_fingerprint")
        ),
        "",
    )
    StatusStore(run).update(
        state="done" if done["status"] in {"ok", "partial"} else "failed",
        phase="F7",
        mode="multi_dataset",
        pack=done["pack"],
        cell=cells,
        counts={"cells": cells, "evidence": evidence, "charts": charts},
        dataset_hash=EvidenceStore.composite_of(hashes) if hashes else "",
        prompt_fingerprint=fingerprint,
        model={"requested": settings.model, "returned": returned},
        datasets=[
            {
                "id": unit.dataset.get("id"),
                "status": unit.outcome.status,
                "cells": unit.outcome.cells,
                "evidence": unit.outcome.evidence,
            }
            for unit in units
        ],
    )

    return RunOutcome(
        status=str(done["status"]),
        summary=str(done["summary"]),
        cells=cells,
        evidence=evidence,
        charts=charts,
        errors=[error for unit in units for error in unit.outcome.errors],
        report_written=run.report_file.is_file(),
    )


def merge_reports(run: RunPaths, units: list[UnitResult]) -> str:
    """Gabungkan laporan unit menjadi satu laporan run; kembalikan galat docx.

    Isi laporan unit disalin apa adanya; path relatif unit (`charts/...`,
    `cells/...`) digeser ke `datasets/<id>/...` supaya tetap menunjuk berkas
    yang benar dari akar run.
    """
    lines = [
        f"# Analisis data: {len(units)} kelompok",
        "",
        "Run ini memuat kelompok data yang tidak berbagi kunci. Setiap kelompok "
        "dianalisis sebagai unit terpisah, dan laporan ini menggabungkan hasilnya "
        "tanpa membandingkan angka antar kelompok.",
        "",
        "| Kelompok | Berkas | Baris | Status | Temuan |",
        "|---|---|---|---|---|",
    ]
    for unit in units:
        dataset = unit.dataset
        files = ", ".join(str(name) for name in dataset.get("files") or [])
        lines.append(
            f"| {dataset.get('id')} | {files} | {dataset.get('rows')} | "
            f"{unit.outcome.status} | {unit.outcome.evidence} |"
        )

    for unit in units:
        lines.extend(["", f"## Kelompok {unit.dataset.get('id')}", ""])
        report = unit.paths.report_file
        if report.is_file():
            lines.append(_rebase_paths(report.read_text(encoding="utf-8"), run, unit.paths))
        else:
            lines.append(
                f"Laporan kelompok ini tidak terbit (status {unit.outcome.status})."
            )

    lines.extend(["", "## Ringkasan lintas kelompok", ""])
    for unit in units:
        files = len(unit.dataset.get("files") or [])
        lines.append(
            f"- {unit.dataset.get('id')}: {files} berkas, {unit.dataset.get('rows')} baris, "
            f"status {unit.outcome.status}, {unit.outcome.evidence} temuan terverifikasi."
        )
    lines.append(
        "- Kelompok tidak berbagi kunci, jadi angka antar kelompok tidak "
        "dibandingkan dalam laporan ini."
    )
    atomic_write_text(run.report_file, "\n".join(lines).rstrip() + "\n")
    # Laporan gabungan memakai path gambar relatif terhadap akar run, jadi
    # base_dir-nya run, bukan direktori unit.
    text = run.report_file.read_text(encoding="utf-8")
    errors: list[str] = []
    for export, target in (
        (export_docx, run.report_docx_file),
        (export_pdf, run.report_pdf_file),
    ):
        try:
            export(text, target, base_dir=run.dir)
        except Exception as exc:  # noqa: BLE001 - markdown tetap kanonik
            errors.append(f"{type(exc).__name__}: {exc}")
    return "; ".join(errors)


def _rebase_paths(text: str, run: RunPaths, unit: RunPaths) -> str:
    prefix = run.relative(unit.dir)
    return _PATH_PREFIX.sub(rf"{prefix}/\1/", text)


def build_done(
    run: RunPaths, units: list[UnitResult], *, pack: str = ""
) -> dict[str, Any]:
    """`done.json` run: status agregat, deliverable per kelompok, dan ringkasan."""
    statuses = [unit.outcome.status for unit in units]
    if "failed" in statuses:
        status = "failed"
    elif "blocked" in statuses:
        status = "blocked"
    elif "partial" in statuses:
        status = "partial"
    else:
        status = "ok"

    completed_per_unit: list[set[str]] = []
    mismatches: list[str] = []
    packs: set[str] = set()
    for unit in units:
        done = read_json(unit.paths.done_file, {}) or {}
        completed_per_unit.append(set(done.get("phases_completed") or []))
        unit_pack = str(done.get("pack") or "")
        if unit_pack:
            packs.add(unit_pack)
        verification = done.get("verification")
        if isinstance(verification, dict):
            for item in verification.get("mismatches") or []:
                mismatches.append(f"{unit.dataset.get('id')}: {item}")

    completed = set.intersection(*completed_per_unit) if completed_per_unit else set()
    phases_completed = [phase for phase in PHASES if phase in completed]
    phases_skipped = [
        {"phase": phase, "reason": "tidak selesai di semua kelompok"}
        for phase in PHASES
        if phase not in completed
    ]

    return {
        "status": status,
        "mode": "multi_dataset",
        "pack": next(iter(packs)) if len(packs) == 1 else ("mixed" if packs else pack),
        "datasets": [
            {
                "id": unit.dataset.get("id"),
                "files": list(unit.dataset.get("files") or []),
                "rows": unit.dataset.get("rows"),
                "status": unit.outcome.status,
                "notebook": _deliverable(run, unit.paths.notebook_file),
                "report": _deliverable(run, unit.paths.report_file),
                "clean_data": _deliverable(run, unit.paths.clean_data_file),
                "cells": unit.outcome.cells,
                "evidence": unit.outcome.evidence,
            }
            for unit in units
        ],
        "phases_completed": phases_completed,
        "phases_skipped": phases_skipped,
        "deliverables": {
            "notebook": [
                name
                for unit in units
                if (name := _deliverable(run, unit.paths.notebook_file))
            ],
            "report_md": _deliverable(run, run.report_file),
            "report_docx": _deliverable(run, run.report_docx_file),
            "report_pdf": _deliverable(run, run.report_pdf_file),
            "clean_data": [
                name
                for unit in units
                if (name := _deliverable(run, unit.paths.clean_data_file))
            ],
        },
        "verification": {"rerun": "skipped", "mismatches": mismatches},
        "summary": _summary(units, status),
        "finished_at": utc_now(),
    }


def _deliverable(root: RunPaths, path: Any) -> str:
    """Path relatif terhadap ``root`` bila berkas ada; string kosong bila tidak."""
    if not path.is_file():
        return ""
    try:
        return path.relative_to(root.dir).as_posix()
    except ValueError:
        return ""


def _summary(units: list[UnitResult], status: str) -> str:
    parts = [
        f"{unit.dataset.get('id')} {unit.outcome.status} "
        f"({unit.outcome.evidence} temuan)"
        for unit in units
    ]
    return f"{len(units)} kelompok, status {status}: " + "; ".join(parts)
