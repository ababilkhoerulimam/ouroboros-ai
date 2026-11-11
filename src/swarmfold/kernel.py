"""Kernel Jupyter dan penulisan notebook.

Satu kernel per run (ARCHITECTURE.md §4): state Python hidup antar cell, output
dan gambar ditangkap dari iopub, dan notebook ditulis dengan nbformat 4 sehingga
dapat dibuka di Jupyter tanpa perbaikan manual.

Tidak ada jalur eksekusi lain: kode pengguna hanya berjalan di dalam kernel, tidak
lewat shell dan tidak lewat subprocess. Kernel juga dijalankan dengan environment
allowlist (kredensial API tidak ikut) dan prelude yang memblokir jaringan serta
subprocess sebagai pertahanan berlapis.
"""

from __future__ import annotations

import base64
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty
from typing import Any

import nbformat
from jupyter_client import KernelManager

from .runtime import atomic_write_text

DEFAULT_TIMEOUT_S = 300
_READY_TIMEOUT_S = 60
_REPLY_TIMEOUT_S = 5.0
_DRAIN_TIMEOUT_S = 3.0
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# Environment kernel dibangun dari allowlist, bukan salinan os.environ: proses API
# memegang SWARMFOLD_API_KEY dan cell yang mencetak os.environ tidak boleh
# memindahkannya ke cells/NNN.out.txt, notebook, atau zip unduhan.
_KERNEL_ENV_ALLOWLIST = (
    "PATH",
    "HOME",
    "USERPROFILE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "MPLCONFIGDIR",
    "IPYTHONDIR",
    "JUPYTER_RUNTIME_DIR",
    "PYTHONUNBUFFERED",
    "LANG",
    "LC_ALL",
)
# Jaring pengaman bila allowlist suatu saat ditambah: nama apa pun yang cocok
# pola ini tidak boleh sampai ke kernel.
_KERNEL_ENV_DENY = ("SWARMFOLD_", "KEY", "TOKEN", "SECRET", "PASSWORD")

# Prelude dijalankan sekali di kernel sebelum session dipakai. Ini pertahanan
# berlapis, bukan sandbox: model yang gigih bisa memuat ulang modul, tetapi
# jalur paling wajar (socket/subprocess/os.system) ditutup dan gagal berisik.
# `socket.socket` sendiri tidak diganti: ipykernel memakainya untuk plumbing
# internal, dan menggantinya membuat kernel berhenti menjawab eksekusi kedua
# (terbukti: cell kedua selalu timeout). Yang diblokir adalah titik sambungnya.
_KERNEL_GUARD = '''
import os as _os, socket as _socket, subprocess as _subprocess


def _blokir(*_args, **_kwargs):
    raise RuntimeError("diblokir di kernel analisis")


_socket.socket.connect = _blokir
_socket.create_connection = _blokir
_socket.getaddrinfo = _blokir
_subprocess.Popen = _blokir
_subprocess.run = _blokir
_os.system = _blokir
if hasattr(_os, "fork"):
    _os.fork = _blokir

del _os, _socket, _subprocess, _blokir
'''

# Batas akumulasi output per stream. Cell yang mencetak ratusan MB tidak boleh
# menahan semuanya di memori proses API; teks yang dikembalikan tetap yang
# dipotong, sehingga notebook memuat teks yang sama.
_MAX_STREAM_BYTES = 1024 * 1024
_TRUNCATION_MARK = "[output dipotong di kernel: 1 MB]"


@dataclass
class CellOutput:
    """Hasil satu eksekusi cell, siap dipakai agent loop dan notebook."""

    status: str  # "ok" | "error" | "timeout"
    stdout: str = ""
    stderr: str = ""
    error: str | None = None  # teks traceback ketika status != "ok"
    images: list[bytes] = field(default_factory=list)
    duration_ms: int = 0
    execution_count: int | None = None


class _CappedBuffer:
    """Penampung teks satu stream dengan batas byte.

    Setelah batas tercapai, penambahan berhenti dan satu baris penanda
    ditambahkan, sehingga teks yang dikembalikan (dan yang masuk notebook)
    adalah teks yang sudah dipotong.
    """

    def __init__(self, limit: int = _MAX_STREAM_BYTES):
        self._limit = int(limit)
        self._chunks: list[str] = []
        self._bytes = 0
        self._truncated = False

    def append(self, text: str) -> None:
        if self._truncated or not text:
            return
        size = len(text.encode("utf-8"))
        if self._bytes + size <= self._limit:
            self._chunks.append(text)
            self._bytes += size
            return
        remaining = self._limit - self._bytes
        if remaining > 0:
            head = text.encode("utf-8")[:remaining].decode("utf-8", errors="ignore")
            self._chunks.append(head)
            self._bytes += len(head.encode("utf-8"))
        self._truncated = True
        prefix = "" if self.text().endswith("\n") else "\n"
        self._chunks.append(prefix + _TRUNCATION_MARK + "\n")

    def text(self) -> str:
        return "".join(self._chunks)


class KernelSession:
    """Satu kernel ipykernel yang hidup selama satu run."""

    def __init__(self, cwd: Path, timeout_s: int = DEFAULT_TIMEOUT_S):
        self.cwd = Path(cwd)
        self.timeout_s = int(timeout_s)
        self._km: KernelManager | None = None
        self._kc: Any = None
        self._started = False
        self._closed = False

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self._started:
            return
        self.cwd.mkdir(parents=True, exist_ok=True)
        km = KernelManager(kernel_name="python3")
        km.start_kernel(cwd=str(self.cwd), env=self._kernel_env())
        kc = km.client()
        kc.start_channels()
        try:
            kc.wait_for_ready(timeout=_READY_TIMEOUT_S)
            self._install_guard(kc)
        except Exception:
            try:
                kc.stop_channels()
            finally:
                try:
                    km.shutdown_kernel(now=True)
                except Exception:  # pragma: no cover - proses bisa sudah mati
                    pass
            raise
        self._km = km
        self._kc = kc
        self._started = True

    def shutdown(self) -> None:
        """Hentikan kernel. Aman dipanggil berkali-kali."""
        if self._closed:
            return
        self._closed = True
        self._teardown()

    def _teardown(self) -> None:
        kc, km = self._kc, self._km
        self._kc = None
        self._km = None
        self._started = False
        if kc is not None:
            try:
                kc.stop_channels()
            except Exception:  # pragma: no cover - teardown best-effort
                pass
        if km is not None:
            try:
                km.shutdown_kernel(now=True)
            except Exception:  # pragma: no cover - proses bisa sudah mati
                pass

    def __enter__(self) -> KernelSession:
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> bool:
        self.shutdown()
        return False

    # -- eksekusi ----------------------------------------------------------

    def execute(self, code: str, timeout_s: int | None = None) -> CellOutput:
        if not self._started or self._kc is None:
            raise RuntimeError("kernel belum dijalankan; panggil start() lebih dulu")

        limit = self.timeout_s if timeout_s is None else int(timeout_s)
        started = time.monotonic()
        deadline = started + limit

        stdout = _CappedBuffer()
        stderr = _CappedBuffer()
        images: list[bytes] = []
        error: str | None = None
        execution_count: int | None = None
        timed_out = False

        msg_id = self._kc.execute(code)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            try:
                msg = self._kc.get_iopub_msg(timeout=remaining)
            except Empty:
                timed_out = True
                break
            if (msg.get("parent_header") or {}).get("msg_id") not in (None, msg_id):
                continue
            msg_type = msg.get("msg_type")
            content = msg.get("content") or {}
            if msg_type == "stream":
                text = str(content.get("text", ""))
                if content.get("name") == "stderr":
                    stderr.append(text)
                else:
                    stdout.append(text)
            elif msg_type in ("execute_result", "display_data"):
                data = content.get("data") or {}
                png = data.get("image/png")
                if isinstance(png, str):
                    images.append(base64.b64decode(png))
                elif msg_type == "execute_result":
                    plain = data.get("text/plain")
                    if isinstance(plain, str):
                        stdout.append(plain if plain.endswith("\n") else plain + "\n")
            elif msg_type == "error":
                error = self._format_error(content)
            elif msg_type == "status":
                if content.get("execution_state") == "idle":
                    break
            # status, execute_input, comm_* dan pesan lain diabaikan

        if timed_out:
            if not self._interrupt_and_drain():
                self._restart()
            return CellOutput(
                status="timeout",
                stdout=stdout.text(),
                stderr=stderr.text(),
                error=f"timeout setelah {limit} detik",
                images=images,
                duration_ms=int((time.monotonic() - started) * 1000),
                execution_count=None,
            )

        reply = self._execute_reply(msg_id)
        if reply is not None:
            content = reply.get("content") or {}
            count = content.get("execution_count")
            if isinstance(count, int):
                execution_count = count
            if error is None and content.get("status") != "ok":
                error = f"eksekusi berakhir dengan status {content.get('status')!r}"

        return CellOutput(
            status="error" if error else "ok",
            stdout=stdout.text(),
            stderr=stderr.text(),
            error=error,
            images=images,
            duration_ms=int((time.monotonic() - started) * 1000),
            execution_count=execution_count,
        )

    # -- internal ----------------------------------------------------------

    @staticmethod
    def _kernel_env() -> dict[str, str]:
        """Environment kernel dari allowlist, bukan salinan `os.environ`.

        Proses API memegang `SWARMFOLD_API_KEY`; menyalin seluruh environment
        berarti satu cell `print(os.environ)` membocorkan kredensial itu ke
        `cells/NNN.out.txt`, notebook, dan zip unduhan. Hanya variabel yang
        dibutuhkan interpreter dan ipykernel yang diteruskan.

        PATH kernel diberi direktori interpreter ini lebih dulu: kernelspec
        `python3` memanggil `python` polos, sehingga tanpa ini kernel bisa
        memakai interpreter lain (atau stub Windows) yang tidak punya pandas
        dan matplotlib.
        """
        env = {
            name: os.environ[name]
            for name in _KERNEL_ENV_ALLOWLIST
            if os.environ.get(name)
        }
        env = {
            name: value
            for name, value in env.items()
            if not any(bad in name.upper() for bad in _KERNEL_ENV_DENY)
        }
        bin_dir = str(Path(sys.executable).parent)
        path = env.get("PATH", "")
        env["PATH"] = bin_dir + os.pathsep + path if path else bin_dir
        return env

    @staticmethod
    def _install_guard(kc: Any) -> None:
        """Jalankan prelude pemblokir jaringan/subprocess sekali per kernel.

        `silent=True` membuat prelude tidak menambah execution_count dan tidak
        meninggalkan output, sehingga cell pertama pengguna tetap `1`.
        """
        msg_id = kc.execute(_KERNEL_GUARD, silent=True, store_history=False)
        deadline = time.monotonic() + _READY_TIMEOUT_S
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("prelude keamanan kernel tidak selesai")
            try:
                msg = kc.get_iopub_msg(timeout=remaining)
            except Empty:
                continue
            if (msg.get("parent_header") or {}).get("msg_id") != msg_id:
                continue
            content = msg.get("content") or {}
            if msg.get("msg_type") == "error":
                detail = KernelSession._format_error(content)
                raise RuntimeError(f"prelude keamanan kernel gagal: {detail}")
            if (
                msg.get("msg_type") == "status"
                and content.get("execution_state") == "idle"
            ):
                return

    @staticmethod
    def _format_error(content: dict[str, Any]) -> str:
        traceback_lines = content.get("traceback") or []
        text = "\n".join(str(line) for line in traceback_lines)
        if not text:
            ename = str(content.get("ename", "Error"))
            evalue = str(content.get("evalue", ""))
            text = f"{ename}: {evalue}" if evalue else ename
        return _ANSI_ESCAPE.sub("", text)

    def _execute_reply(self, msg_id: str) -> dict[str, Any] | None:
        """Balasan shell milik eksekusi ini saja.

        Kanal shell juga membawa balasan lain (mis. `kernel_info_reply` dari
        `wait_for_ready`); tanpa penyaringan, balasan lama bisa terbaca sebagai
        status cell berikutnya.
        """
        deadline = time.monotonic() + _REPLY_TIMEOUT_S
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                reply = self._kc.get_shell_msg(timeout=remaining)
            except Empty:
                return None
            if reply.get("msg_type") != "execute_reply":
                continue
            if (reply.get("parent_header") or {}).get("msg_id") == msg_id:
                return reply

    def _interrupt_and_drain(self) -> bool:
        """Interrupt kernel lalu buang sisa pesan cell yang dihentikan.

        Mengembalikan True bila kernel kembali idle. Di Windows, panggilan
        pemblokiran murni (`time.sleep`) tidak selalu dapat diinterupsi, jadi
        pemanggil harus menyiapkan jalur pemulihan saat hasilnya False.
        """
        km, kc = self._km, self._kc
        if km is None or kc is None:
            return False
        try:
            km.interrupt_kernel()
        except Exception:  # pragma: no cover - kernel bisa sudah mati
            return False
        deadline = time.monotonic() + _DRAIN_TIMEOUT_S
        idle = False
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                msg = kc.get_iopub_msg(timeout=min(remaining, 0.5))
            except Empty:
                continue
            content = msg.get("content") or {}
            if msg.get("msg_type") == "status" and content.get("execution_state") == "idle":
                idle = True
                break
        self._drain_shell()
        return idle

    def _restart(self) -> None:
        """Ganti kernel baru ketika interrupt tidak menghentikan cell.

        State Python hilang; ini harga yang dibayar agar satu cell yang macet
        tidak membekukan sisa run (ARCHITECTURE.md §6: timeout cell bukan
        kegagalan run).
        """
        self._teardown()
        self.start()

    def _drain_shell(self) -> None:
        kc = self._kc
        if kc is None:
            return
        deadline = time.monotonic() + _DRAIN_TIMEOUT_S
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            try:
                kc.get_shell_msg(timeout=min(remaining, 0.2))
            except Empty:
                return


class NotebookWriter:
    """Menyusun `analysis.ipynb` dari cell yang dieksekusi."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._nb = nbformat.v4.new_notebook()
        self._nb.metadata["kernelspec"] = {
            "name": "python3",
            "display_name": "Python 3 (ipykernel)",
            "language": "python",
        }
        self._nb.metadata["language_info"] = {"name": "python"}

    def add_markdown(self, text: str) -> None:
        self._nb.cells.append(nbformat.v4.new_markdown_cell(source=text))

    def add_code(self, code: str, intent: str, output: CellOutput) -> int:
        self._nb.cells.append(nbformat.v4.new_markdown_cell(source=f"### {intent}"))
        cell = nbformat.v4.new_code_cell(
            source=code,
            execution_count=output.execution_count,
            outputs=self._build_outputs(output),
        )
        self._nb.cells.append(cell)
        return len(self._nb.cells) - 1

    def save(self) -> None:
        nbformat.validate(self._nb)
        atomic_write_text(self.path, nbformat.writes(self._nb))

    # -- internal ----------------------------------------------------------

    @staticmethod
    def _build_outputs(output: CellOutput) -> list[nbformat.NotebookNode]:
        outputs: list[nbformat.NotebookNode] = []
        if output.stdout:
            outputs.append(nbformat.v4.new_output("stream", name="stdout", text=output.stdout))
        if output.stderr:
            outputs.append(nbformat.v4.new_output("stream", name="stderr", text=output.stderr))
        if output.error:
            text = _ANSI_ESCAPE.sub("", output.error)
            ename, evalue = _split_error(text)
            traceback = [line + "\n" for line in text.splitlines()]
            outputs.append(
                nbformat.v4.new_output(
                    "error", ename=ename, evalue=evalue, traceback=traceback
                )
            )
        for image in output.images:
            outputs.append(
                nbformat.v4.new_output(
                    "display_data",
                    data={
                        "image/png": base64.b64encode(image).decode("ascii"),
                        "text/plain": f"<image/png {len(image)} bytes>",
                    },
                    metadata={},
                )
            )
        return outputs


def _split_error(text: str) -> tuple[str, str]:
    """Ambil ename/evalue dari baris terakhir traceback."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "Error", ""
    last = lines[-1]
    if ":" in last:
        name, value = last.split(":", 1)
        name, value = name.strip(), value.strip()
        if name and " " not in name:
            return name, value
    return "Error", last


__all__ = ["CellOutput", "KernelSession", "NotebookWriter", "DEFAULT_TIMEOUT_S"]
