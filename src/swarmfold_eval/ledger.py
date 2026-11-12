"""Ledger varian: satu baris per percobaan, append-only dan berantai hash.

Ledger menjawab pertanyaan yang tidak bisa dijawab riwayat git: percobaan mana
yang diharapkan berhasil, apa hasilnya, dan atas dasar apa ia dipromosikan atau
dibuang. Karena itu ia tidak boleh bisa diedit diam-diam — setiap baris memuat
`prev_sha` baris sebelumnya, sehingga satu perubahan membatalkan seluruh rantai
sesudahnya.

Baris yang tidak lolos validasi tetap ditulis, dengan `verdict:
schema_rejected`. Menolak menulisnya justru menghapus bukti bahwa ada usulan
cacat yang pernah datang.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = 1
LEDGER_FILE = "ledger.jsonl"
GENESIS = "genesis"
VERDICTS = (
    "promoted",
    "rejected",
    "regressed",
    "tampered",
    "unexpected",
    "schema_rejected",
)
#: Kolom yang wajib diisi pengusul. `seq`, `ts`, `prev_sha`, dan `_sha` diisi ledger.
REQUIRED = (
    "variant_id",
    "parent",
    "hypothesis",
    "layer",
    "files",
    "diff_sha",
    "expected",
    "split",
    "replicas",
    "before",
    "after",
    "heldout",
    "verdict",
    "branch",
    "run_ids",
)


class LedgerError(RuntimeError):
    """Ledger tidak bisa dibaca atau rantainya tidak utuh."""


def _canonical(data: dict[str, Any]) -> bytes:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def _sha(data: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical(data)).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def read(path: Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.is_file():
        return []
    baris: list[dict[str, Any]] = []
    for nomor, teks in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not teks.strip():
            continue
        try:
            data = json.loads(teks)
        except json.JSONDecodeError as error:
            raise LedgerError(f"baris {nomor} bukan JSON: {error}") from error
        if not isinstance(data, dict):
            raise LedgerError(f"baris {nomor} bukan objek")
        baris.append(data)
    return baris


def verify_chain(path: Path) -> list[str]:
    """Daftar pelanggaran rantai; kosong berarti utuh."""
    masalah: list[str] = []
    sebelumnya = GENESIS
    for nomor, row in enumerate(read(path), start=1):
        if row.get("seq") != nomor:
            masalah.append(f"baris {nomor}: seq {row.get('seq')!r} tidak berurutan")
        if row.get("prev_sha") != sebelumnya:
            masalah.append(f"baris {nomor}: prev_sha tidak cocok")
        isi = {key: value for key, value in row.items() if key != "_sha"}
        if row.get("_sha") != _sha(isi):
            masalah.append(f"baris {nomor}: isi berubah sejak ditulis")
        sebelumnya = str(row.get("_sha") or "")
    return masalah


def _problems(entry: dict[str, Any]) -> list[str]:
    masalah = [f"{key} wajib diisi" for key in REQUIRED if key not in entry]
    verdict = entry.get("verdict")
    if verdict is not None and verdict not in VERDICTS:
        masalah.append(f"verdict tidak dikenal: {verdict!r}")
    files = entry.get("files")
    if files is not None and not isinstance(files, list):
        masalah.append("files harus daftar path")
    replicas = entry.get("replicas")
    if replicas is not None and (not isinstance(replicas, int) or replicas < 1):
        masalah.append("replicas harus bilangan bulat >= 1")
    if entry.get("expected") is not None and not str(entry.get("expected")).strip():
        masalah.append("expected tidak boleh kosong")
    return masalah


def record(path: Path, entry: dict[str, Any]) -> dict[str, Any]:
    """Tambahkan satu baris; baris cacat ditulis sebagai `schema_rejected`."""
    path = Path(path)
    entry = dict(entry)
    masalah = _problems(entry)
    if masalah:
        entry["verdict"] = "schema_rejected"
        entry["errors"] = masalah

    baris = read(path)
    row: dict[str, Any] = {
        "schema": SCHEMA,
        "seq": len(baris) + 1,
        "ts": _now(),
        **entry,
        "prev_sha": str(baris[-1].get("_sha") or GENESIS) if baris else GENESIS,
    }
    row["_sha"] = _sha({key: value for key, value in row.items() if key != "_sha"})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return row


def last(path: Path) -> dict[str, Any] | None:
    baris = read(path)
    return baris[-1] if baris else None
