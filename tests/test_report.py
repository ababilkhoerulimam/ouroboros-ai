"""Tes renderer slot laporan, CONTRACTS.md §8."""

from __future__ import annotations

import pytest

from swarmfold.evidence import EvidenceStore
from swarmfold.report import ReportError, render_slots
from swarmfold.runtime import RunPaths

DATASET_HASH = "sha256:aaa111"


def _store(tmp_path) -> EvidenceStore:
    paths = RunPaths(root=tmp_path, run_id="2026-11-11-test").ensure()
    return EvidenceStore(paths)


def _finding(**overrides) -> dict:
    entry = {
        "id": "E-001",
        "pillar": "fact",
        "statement": "pendapatan turun 12,4% dibanding kuartal sebelumnya",
        "value": -0.124,
        "unit": "ratio",
        "display": "-12,4%",
        "cell": 1,
        "artifact": "cells/001.out.txt",
        "dataset_hash": DATASET_HASH,
        "confidence": "high",
        "verified": True,
    }
    entry.update(overrides)
    return entry


def test_slot_diganti_dengan_display(tmp_path):
    store = _store(tmp_path)
    store.add("F3", _finding())

    text = render_slots("Pendapatan turun {{E-001}}.", store=store, completed=["F3"])

    assert text == "Pendapatan turun -12,4%."


def test_slot_chart_diganti_dengan_path(tmp_path):
    store = _store(tmp_path)
    store.add("F3", _finding(chart="charts/F3_01.png"))

    text = render_slots("{{E-001.chart}}", store=store, completed=["F3"])

    assert text == "charts/F3_01.png"


def test_slot_value_memuat_satuan(tmp_path):
    store = _store(tmp_path)
    store.add("F3", _finding(value=3320, unit="count", display="3.320 pesanan"))

    text = render_slots("{{E-001.value}}", store=store, completed=["F3"])

    assert text == "3320 count"


def test_id_tidak_ada_menggagalkan_seluruh_laporan(tmp_path):
    store = _store(tmp_path)
    store.add("F3", _finding())

    with pytest.raises(ReportError) as excinfo:
        render_slots("{{E-001}} lalu {{E-999}}", store=store, completed=["F3"])

    assert "E-999" in str(excinfo.value)


def test_temuan_belum_terverifikasi_menggagalkan_laporan(tmp_path):
    store = _store(tmp_path)
    store.add("F3", _finding(verified=False))

    with pytest.raises(ReportError) as excinfo:
        render_slots("{{E-001}}", store=store, completed=["F3"])

    assert "verified" in str(excinfo.value)


def test_fase_belum_selesai_menggagalkan_laporan(tmp_path):
    store = _store(tmp_path)
    store.add("F3", _finding())

    with pytest.raises(ReportError) as excinfo:
        render_slots("{{E-001}}", store=store, completed=["F1"])

    assert "F3" in str(excinfo.value)


def test_fase_dilewati_tetap_dikutip_bila_sudah_diaudit(tmp_path):
    # F4 dilewati karena data tidak punya identifier pelanggan; temuannya
    # ("0 kolom ditemukan") justru alasan yang harus muncul di laporan.
    store = _store(tmp_path)
    store.add("F4", _finding(display="0 kolom tahapan pesanan ditemukan"))

    text = render_slots(
        "{{E-001}}", store=store, completed=["F1", "F6"], audited=True
    )

    assert text == "0 kolom tahapan pesanan ditemukan"


def test_chart_yang_tidak_ada_menggagalkan_laporan(tmp_path):
    store = _store(tmp_path)
    store.add("F3", _finding())

    with pytest.raises(ReportError) as excinfo:
        render_slots("{{E-001.chart}}", store=store, completed=["F3"])

    assert "chart" in str(excinfo.value)


def test_teks_tanpa_slot_tidak_berubah(tmp_path):
    store = _store(tmp_path)

    assert render_slots("Tidak ada angka.", store=store, completed=[]) == "Tidak ada angka."
