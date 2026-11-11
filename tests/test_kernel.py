"""Tes kernel dan notebook (M2).

Setiap tes memakai direktori sementara sendiri; tidak ada jaringan.
"""

from __future__ import annotations

import base64
import time

import nbformat
import pytest

from swarmfold.kernel import CellOutput, KernelSession, NotebookWriter

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def session(tmp_path):
    s = KernelSession(tmp_path / "run")
    s.start()
    try:
        yield s
    finally:
        s.shutdown()


def test_state_persists_between_executions(session):
    first = session.execute("x = 41")
    assert first.status == "ok"
    assert first.error is None
    assert first.execution_count == 1

    second = session.execute("print(x + 1)")
    assert second.status == "ok"
    assert second.stdout.strip() == "42"
    assert second.execution_count == 2


def test_error_returns_traceback_and_kernel_survives(session):
    bad = session.execute("raise ValueError('data tidak lengkap')")
    assert bad.status == "error"
    assert bad.error
    assert "ValueError" in bad.error
    assert "data tidak lengkap" in bad.error

    after = session.execute("print('kernel masih hidup')")
    assert after.status == "ok"
    assert "kernel masih hidup" in after.stdout


def test_matplotlib_figure_captured_and_embedded(tmp_path):
    run_dir = tmp_path / "run"
    nb_path = run_dir / "analysis.ipynb"
    code = (
        "import matplotlib.pyplot as plt\n"
        "fig, ax = plt.subplots()\n"
        "ax.plot([0, 1, 2], [2, 1, 0])\n"
        "plt.show()\n"
    )

    with KernelSession(run_dir) as session:
        output = session.execute(code)

    assert output.status == "ok"
    assert len(output.images) == 1
    assert output.images[0].startswith(PNG_SIGNATURE)

    writer = NotebookWriter(nb_path)
    writer.add_code(code, "grafik garis sederhana", output)
    writer.save()

    nb = nbformat.read(nb_path, as_version=4)
    nbformat.validate(nb)

    code_cell = nb.cells[1]
    assert code_cell.cell_type == "code"
    image_outputs = [
        out
        for out in code_cell.outputs
        if out.output_type == "display_data" and "image/png" in out.get("data", {})
    ]
    assert len(image_outputs) == 1
    embedded = base64.b64decode(image_outputs[0]["data"]["image/png"])
    assert embedded.startswith(PNG_SIGNATURE)
    assert embedded == output.images[0]


def test_timeout_interrupts_and_session_recovers(tmp_path):
    with KernelSession(tmp_path / "run", timeout_s=2) as session:
        started = time.monotonic()
        output = session.execute("import time; time.sleep(5)")
        elapsed = time.monotonic() - started

        assert output.status == "timeout"
        assert output.error == "timeout setelah 2 detik"
        assert elapsed < 15

        after = session.execute("print('pulih setelah timeout')")
        assert after.status == "ok"
        assert "pulih setelah timeout" in after.stdout


def test_notebook_intent_above_code_and_cells_in_order(tmp_path):
    nb_path = tmp_path / "run" / "analysis.ipynb"
    writer = NotebookWriter(nb_path)
    writer.add_code("a = 1", "siapkan variabel", CellOutput(status="ok", stdout="", execution_count=1))
    writer.add_code("print(a)", "cetak variabel", CellOutput(status="ok", stdout="1\n", execution_count=2))
    writer.save()

    nb = nbformat.read(nb_path, as_version=4)
    nbformat.validate(nb)

    assert [cell.cell_type for cell in nb.cells] == [
        "markdown",
        "code",
        "markdown",
        "code",
    ]
    assert nb.cells[0].source == "### siapkan variabel"
    assert nb.cells[1].source == "a = 1"
    assert nb.cells[2].source == "### cetak variabel"
    assert nb.cells[3].source == "print(a)"


def test_notebook_with_error_and_timeout_outputs_stays_valid(tmp_path):
    nb_path = tmp_path / "run" / "analysis.ipynb"
    writer = NotebookWriter(nb_path)
    writer.add_markdown("## Analisis")
    writer.add_code(
        "raise RuntimeError('gagal')",
        "cell yang gagal",
        CellOutput(
            status="error",
            stderr="jejak galat\n",
            error="Traceback (most recent call last):\nRuntimeError: gagal",
            duration_ms=5,
            execution_count=3,
        ),
    )
    writer.add_code(
        "time.sleep(999)",
        "cell yang timeout",
        CellOutput(status="timeout", error="timeout setelah 300 detik", duration_ms=300000),
    )
    writer.save()
    writer.save()  # idempotent

    nb = nbformat.read(nb_path, as_version=4)
    nbformat.validate(nb)

    error_cell = nb.cells[2]
    error_outputs = [out for out in error_cell.outputs if out.output_type == "error"]
    assert len(error_outputs) == 1
    assert error_outputs[0].ename == "RuntimeError"
    assert error_outputs[0].evalue == "gagal"
    assert error_outputs[0].traceback == [
        "Traceback (most recent call last):\n",
        "RuntimeError: gagal\n",
    ]

    timeout_cell = nb.cells[4]
    timeout_outputs = [out for out in timeout_cell.outputs if out.output_type == "error"]
    assert len(timeout_outputs) == 1
    assert "timeout" in timeout_outputs[0].evalue


def test_shutdown_twice_does_not_raise(tmp_path):
    session = KernelSession(tmp_path / "run")
    session.start()
    session.shutdown()
    session.shutdown()


def test_kunci_api_tidak_masuk_environment_kernel(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARMFOLD_API_KEY", "kunci-rahasia-uji")

    env = KernelSession._kernel_env()
    assert "SWARMFOLD_API_KEY" not in env
    assert all("SWARMFOLD_" not in name for name in env)
    assert all(
        bad not in name.upper()
        for name in env
        for bad in ("KEY", "TOKEN", "SECRET", "PASSWORD")
    )

    with KernelSession(tmp_path / "run") as session:
        output = session.execute("import os; print(repr(os.environ.get('SWARMFOLD_API_KEY')))")

    assert output.status == "ok"
    assert output.stdout.strip() == "None"
    assert "kunci-rahasia-uji" not in output.stdout


def test_jaringan_dan_subprocess_diblokir_di_kernel(tmp_path):
    with KernelSession(tmp_path / "run") as session:
        jaringan = session.execute(
            'import socket\nsocket.create_connection(("example.com", 80))'
        )
        assert jaringan.status == "error"
        assert "RuntimeError" in jaringan.error
        assert "diblokir di kernel analisis" in jaringan.error

        proses = session.execute('import subprocess\nsubprocess.run(["echo", "x"])')
        assert proses.status == "error"
        assert "RuntimeError" in proses.error
        assert "diblokir di kernel analisis" in proses.error


def test_output_dipotong_satu_megabyte(tmp_path):
    nb_path = tmp_path / "run" / "analysis.ipynb"
    batas = 1024 * 1024
    penanda = "[output dipotong di kernel: 1 MB]"

    with KernelSession(tmp_path / "run") as session:
        output = session.execute("print('x' * 2_000_000)")
        galat = session.execute("import sys; sys.stderr.write('y' * 2_000_000)")

    assert output.status == "ok"
    assert penanda in output.stdout
    assert output.stdout.count(penanda) == 1
    assert len(output.stdout.encode("utf-8")) <= batas + 64

    assert penanda in galat.stderr
    assert len(galat.stderr.encode("utf-8")) <= batas + 64

    writer = NotebookWriter(nb_path)
    writer.add_code("print('x' * 2_000_000)", "cetak teks besar", output)
    writer.save()

    nb = nbformat.read(nb_path, as_version=4)
    nbformat.validate(nb)
    assert nb.cells[1].outputs[0]["text"] == output.stdout

