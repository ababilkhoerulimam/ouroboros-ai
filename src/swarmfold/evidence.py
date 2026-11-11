"""Berkas bukti `evidence/F{n}.json`: tulis, baca, dan validasi.

Aturan mengikuti CONTRACTS.md §4 dan `prompts/evidence.md`: `E-###` hanya untuk
angka yang tercetak di output cell, `H-###` untuk hipotesis, `AN-###` untuk
anomali. `add` menolak entri yang melanggar skema; `validate` tidak pernah
melempar, ia mengembalikan daftar kesalahan yang bisa dibaca manusia.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .runtime import RunPaths, atomic_write_json, read_json

_PHASE_RE = re.compile(r"^F[1-7]$")
_ID_RE = re.compile(r"^(E|H|AN)-\d{3}$")
_DEEPDIVE_RE = re.compile(r"^(\d+)\.json$")

#: `measure` = angka dengan satuan milik data itu sendiri (cm, kg, detik,
#: skor); satuannya ditulis di `display`, bukan diubah ke satuan lain.
UNITS = ("ratio", "IDR", "count", "days", "pp", "measure")
CONFIDENCE_LEVELS = ("high", "medium", "low")
HYPOTHESIS_STATUSES = ("unresolved", "supported", "rejected")

SECTION_BY_KIND = {"E": "findings", "H": "hypotheses", "AN": "anomalies"}
SECTIONS = ("findings", "hypotheses", "anomalies")
REQUIRED_FINDING_KEYS = (
    "id",
    "statement",
    "value",
    "unit",
    "cell",
    "artifact",
    "dataset_hash",
    "verified",
    "confidence",
)
PHASES = tuple(f"F{n}" for n in range(1, 8))


class EvidenceError(RuntimeError):
    """Entri bukti atau berkas bukti melanggar skema."""


def _is_number(value: Any) -> bool:
    """Angka sungguhan: bool dan NaN/tak hingga bukan nilai yang bisa dilaporkan."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _skeleton(phase: str, question: str = "") -> dict[str, Any]:
    return {
        "phase": phase,
        "question": question,
        "findings": [],
        "hypotheses": [],
        "anomalies": [],
        "cannot_answer": [],
    }


def _require_text(entry: dict[str, Any], key: str, ident: str) -> None:
    if not _is_text(entry.get(key)):
        raise EvidenceError(f"{ident}: {key} wajib berupa teks tidak kosong")


def _check_phase(phase: str) -> str:
    if not isinstance(phase, str) or not _PHASE_RE.match(phase):
        raise EvidenceError(f"fase tidak dikenal: {phase!r}; pilih F1 sampai F7")
    return phase


@dataclass
class EvidenceStore:
    paths: RunPaths

    # -- berkas -------------------------------------------------------------

    def file_for(self, phase: str) -> Path:
        return self.paths.evidence_dir / f"{_check_phase(phase)}.json"

    def load(self, phase: str) -> dict:
        """Isi berkas fase, atau kerangka kosong bila berkas belum ada."""
        path = self.file_for(phase)
        data = read_json(path)
        if data is None:
            return _skeleton(phase)
        if not isinstance(data, dict):
            raise EvidenceError(f"{path.name} bukan objek JSON")
        return self._normalize(phase, data)

    def write_phase(self, phase: str, data: dict) -> None:
        path = self.file_for(phase)
        if not isinstance(data, dict):
            raise EvidenceError(f"{path.name} harus ditulis sebagai objek JSON")
        atomic_write_json(path, data)

    @staticmethod
    def _normalize(phase: str, data: dict[str, Any]) -> dict[str, Any]:
        out = dict(data)
        out.setdefault("phase", phase)
        out.setdefault("question", "")
        for section in SECTIONS:
            out.setdefault(section, [])
        out.setdefault("cannot_answer", [])
        return out

    # -- tulis --------------------------------------------------------------

    def add(self, phase: str, entry: dict, question: str = "") -> dict:
        """Validasi satu entri lalu simpan ke berkas fase. Mengembalikan entri."""
        if not isinstance(entry, dict):
            raise EvidenceError("entri bukti harus berupa objek JSON")
        ident = entry.get("id")
        if not isinstance(ident, str) or not _ID_RE.match(ident):
            raise EvidenceError(
                f"id {ident!r} tidak sah: harus berbentuk E-###, H-###, atau AN-###"
            )
        if ident in self.ids():
            raise EvidenceError(f"id {ident} sudah dipakai di run ini")

        kind = ident.split("-", 1)[0]
        if kind == "E":
            self._check_finding(entry, ident)
        elif kind == "H":
            self._check_hypothesis(entry, ident)
        else:
            self._check_anomaly(entry, ident)

        data = self.load(phase)
        section = SECTION_BY_KIND[kind]
        bucket = data.get(section)
        if not isinstance(bucket, list):
            raise EvidenceError(f"{self.file_for(phase).name}: '{section}' bukan list")
        if question and not data.get("question"):
            data["question"] = question
        bucket.append(entry)
        self.write_phase(phase, data)
        return dict(entry)

    @staticmethod
    def _check_finding(entry: dict[str, Any], ident: str) -> None:
        _require_text(entry, "statement", ident)
        value = entry.get("value")
        if not _is_number(value):
            raise EvidenceError(
                f"{ident}: value harus angka (int/float), bukan {type(value).__name__}"
            )
        unit = entry.get("unit")
        if unit not in UNITS:
            raise EvidenceError(
                f"{ident}: unit {unit!r} tidak dikenal; pilih {', '.join(UNITS)}"
            )
        if not _is_int(entry.get("cell")):
            raise EvidenceError(f"{ident}: cell harus bilangan bulat")
        _require_text(entry, "artifact", ident)
        _require_text(entry, "dataset_hash", ident)
        if not isinstance(entry.get("verified"), bool):
            raise EvidenceError(f"{ident}: verified harus true atau false")
        confidence = entry.get("confidence")
        if confidence not in CONFIDENCE_LEVELS:
            raise EvidenceError(
                f"{ident}: confidence {confidence!r} tidak dikenal; "
                f"pilih {', '.join(CONFIDENCE_LEVELS)}"
            )

    @staticmethod
    def _check_hypothesis(entry: dict[str, Any], ident: str) -> None:
        _require_text(entry, "statement", ident)
        status = entry.get("status")
        if status not in HYPOTHESIS_STATUSES:
            raise EvidenceError(
                f"{ident}: status {status!r} tidak dikenal; "
                f"pilih {', '.join(HYPOTHESIS_STATUSES)}"
            )

    @staticmethod
    def _check_anomaly(entry: dict[str, Any], ident: str) -> None:
        _require_text(entry, "statement", ident)
        if not isinstance(entry.get("handled"), bool):
            raise EvidenceError(f"{ident}: handled harus true atau false")

    def set_verified(self, phase: str, finding_id: str, verified: bool) -> dict:
        """Ubah `verified` pada finding yang ada; entri tidak pernah dihapus."""
        data = self.load(phase)
        findings = data.get("findings")
        if not isinstance(findings, list):
            raise EvidenceError(f"{self.file_for(phase).name}: 'findings' bukan list")
        for finding in findings:
            if isinstance(finding, dict) and finding.get("id") == finding_id:
                finding["verified"] = bool(verified)
                self.write_phase(phase, data)
                return dict(finding)
        raise EvidenceError(f"{finding_id} tidak ada di {phase}")

    # -- baca ---------------------------------------------------------------

    def ids(self) -> set[str]:
        found: set[str] = set()
        for phase in PHASES:
            data = read_json(self.file_for(phase))
            if not isinstance(data, dict):
                continue
            for section in SECTIONS:
                bucket = data.get(section)
                if not isinstance(bucket, list):
                    continue
                for entry in bucket:
                    if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                        found.add(entry["id"])
        return found

    def count(self, phase: str | None = None) -> int:
        """Jumlah `E-###` dengan `verified: true`, satu fase atau seluruh run."""
        phases = (phase,) if phase is not None else PHASES
        total = 0
        for name in phases:
            data = self.load(name)
            findings = data.get("findings")
            if not isinstance(findings, list):
                continue
            total += sum(
                1
                for finding in findings
                if isinstance(finding, dict) and finding.get("verified") is True
            )
        return total

    @staticmethod
    def composite_of(tree: dict[str, str]) -> str:
        """sha256 dari peta `{nama berkas: sha256}`.

        Dipakai loop dengan peta yang dibekukan saat run mulai, supaya angka
        yang divalidasi di akhir tidak bergantung pada isi `data/` yang sudah
        berubah di tengah run.
        """
        payload = json.dumps(dict(sorted(tree.items())), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def composite_hash(self) -> str:
        """Satu sha256 untuk seluruh `data/`: hash dari peta `{nama berkas: sha256}`.

        `dataset_hash` per berkas tidak cukup untuk run multi-berkas: model bisa
        mengutip angka dari berkas yang tidak ikut di-hash. Impor `hash_tree`
        lokal untuk memutus impor melingkar `tools` -> `evidence`.
        """
        from .tools import hash_tree

        return self.composite_of(hash_tree(self.paths.data_dir))

    def has_residual_zero(self, phase: str) -> bool:
        """True bila ada finding di fase itu dengan `meta.residual == 0`."""
        data = self.load(phase)
        findings = data.get("findings")
        if not isinstance(findings, list):
            return False
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            meta = finding.get("meta")
            if isinstance(meta, dict):
                residual = meta.get("residual")
                if _is_number(residual) and residual == 0:
                    return True
        return False

    # -- validasi -----------------------------------------------------------

    def validate(self, phase: str, *, cells_index: dict, dataset_hash: str) -> list[str]:
        """Daftar kesalahan untuk satu berkas fase; tidak pernah melempar."""
        errors: list[str] = []
        path = self.file_for(phase)
        data = read_json(path)
        if data is None:
            # Fase yang belum berjalan belum punya berkas; ketiadaannya bukan
            # pelanggaran skema (lihat `phases_skipped` di done.json).
            return []
        if not isinstance(data, dict):
            return [f"berkas bukti {path.name} bukan objek JSON"]

        for section in SECTIONS:
            if not isinstance(data.get(section), list):
                errors.append(f"'{section}' bukan list")
        if not isinstance(data.get("cannot_answer", []), list):
            errors.append("'cannot_answer' bukan list")

        cell_records = self._cell_index(cells_index)
        seen: dict[str, int] = {}
        other_phases = self._ids_by_phase(exclude=phase)

        findings = data.get("findings")
        if isinstance(findings, list):
            for index, finding in enumerate(findings):
                if not isinstance(finding, dict):
                    errors.append(f"findings[{index}] bukan objek JSON")
                    continue
                errors.extend(
                    self._check_entry_shape(finding, index, seen, other_phases, phase)
                )
                missing = [k for k in REQUIRED_FINDING_KEYS if k not in finding]
                if missing:
                    errors.append(
                        f"findings[{index}] kehilangan kunci: {', '.join(missing)}"
                    )
                    continue
                errors.extend(
                    self._check_finding_value(
                        finding, cell_records, dataset_hash, phase
                    )
                )

        for section in ("hypotheses", "anomalies"):
            bucket = data.get(section)
            if not isinstance(bucket, list):
                continue
            for index, entry in enumerate(bucket):
                if not isinstance(entry, dict):
                    errors.append(f"{section}[{index}] bukan objek JSON")
                    continue
                errors.extend(
                    self._check_entry_shape(entry, index, seen, other_phases, phase, section)
                )

        return errors

    def validate_all(self, *, cells_index: dict, dataset_hash: str) -> list[str]:
        errors: list[str] = []
        for phase in PHASES:
            for message in self.validate(
                phase, cells_index=cells_index, dataset_hash=dataset_hash
            ):
                errors.append(f"{phase}: {message}")
        return errors

    @staticmethod
    def _cell_index(cells_index: Any) -> dict[int, dict[str, Any]]:
        """Peta `n` -> entri cell utuh, agar `status` dan `phase` bisa diperiksa."""
        index: dict[int, dict[str, Any]] = {}
        if not isinstance(cells_index, dict):
            return index
        cells = cells_index.get("cells")
        if not isinstance(cells, list):
            return index
        for cell in cells:
            if not isinstance(cell, dict):
                continue
            number = cell.get("n")
            if _is_int(number):
                index[number] = cell
        return index

    def _ids_by_phase(self, *, exclude: str) -> dict[str, str]:
        owners: dict[str, str] = {}
        for phase in PHASES:
            if phase == exclude:
                continue
            data = read_json(self.file_for(phase))
            if not isinstance(data, dict):
                continue
            for section in SECTIONS:
                bucket = data.get(section)
                if not isinstance(bucket, list):
                    continue
                for entry in bucket:
                    if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                        owners.setdefault(entry["id"], phase)
        return owners

    @staticmethod
    def _check_entry_shape(
        entry: dict[str, Any],
        index: int,
        seen: dict[str, int],
        other_phases: dict[str, str],
        phase: str,
        section: str = "findings",
    ) -> list[str]:
        errors: list[str] = []
        ident = entry.get("id")
        if not isinstance(ident, str) or not _ID_RE.match(ident):
            errors.append(f"{section}[{index}]: id {ident!r} tidak sah")
            return errors
        if ident in seen:
            errors.append(f"id {ident} muncul lebih dari sekali di {phase}")
        seen[ident] = index
        owner = other_phases.get(ident)
        if owner is not None:
            errors.append(f"id {ident} duplikat: sudah dipakai di {owner}")
        return errors

    def _check_finding_value(
        self,
        finding: dict[str, Any],
        cells: dict[int, dict[str, Any]],
        dataset_hash: str,
        phase: str,
    ) -> list[str]:
        errors: list[str] = []
        ident = str(finding["id"])

        value = finding.get("value")
        if not _is_number(value):
            errors.append(f"{ident}: value bukan angka")
        unit = finding.get("unit")
        if unit not in UNITS:
            errors.append(f"{ident}: unit {unit!r} tidak dikenal")

        cell = finding.get("cell")
        expected_artifact: str | None = None
        if not _is_int(cell):
            errors.append(f"{ident}: cell bukan bilangan bulat")
        else:
            expected_artifact = f"cells/{cell:03d}.out.txt"
            record = cells.get(cell)
            if record is None:
                errors.append(f"{ident}: cell {cell} tidak ada di cells/index.json")
            else:
                if record.get("status") != "ok":
                    errors.append(
                        f"{ident}: cell {cell} berstatus {record.get('status')!r}, "
                        "bukan 'ok'"
                    )
                if record.get("phase") != phase:
                    errors.append(
                        f"{ident}: cell {cell} milik fase {record.get('phase')!r}, "
                        f"bukan {phase}"
                    )

        display = finding.get("display")
        if not _is_text(display):
            errors.append(f"{ident}: display wajib berupa teks tidak kosong")

        artifact = finding.get("artifact")
        if not _is_text(artifact):
            errors.append(f"{ident}: artifact wajib berupa teks tidak kosong")
        elif expected_artifact is None:
            # cell tidak sah: kesalahannya sudah dilaporkan di atas, dan tanpa
            # nomor cell yang benar tidak ada path artifact yang bisa dituntut.
            pass
        else:
            # `artifact` hanya boleh output cell yang dikutip. Tanpa batas ini
            # model bisa menulis `evidence/F3.json` sendiri lalu mengutipnya.
            normalised = artifact.strip().replace("\\", "/")
            if normalised != expected_artifact:
                errors.append(
                    f"{ident}: artifact {artifact!r} harus {expected_artifact!r} "
                    f"(output cell {cell})"
                )
            else:
                errors.extend(
                    self._check_file(ident, "artifact", normalised, display=display)
                )

        chart = finding.get("chart")
        if chart not in (None, ""):
            if not isinstance(chart, str):
                errors.append(f"{ident}: chart harus berupa path teks")
            else:
                errors.extend(self._check_file(ident, "chart", chart))

        stored_hash = finding.get("dataset_hash")
        if stored_hash != dataset_hash:
            errors.append(
                f"{ident}: dataset_hash {stored_hash!r} tidak sama dengan hash run "
                f"{dataset_hash!r}"
            )
        return errors

    def _check_file(
        self,
        ident: str,
        field: str,
        relative: str,
        *,
        display: Any = None,
    ) -> list[str]:
        path = self._resolve(relative)
        if path is None:
            return [f"{ident}: {field} {relative!r} keluar dari direktori run"]
        if not path.is_file():
            return [f"{ident}: {field} {relative!r} tidak ditemukan"]
        if field != "artifact":
            return []
        text = path.read_text(encoding="utf-8", errors="replace")
        if not _contains_rendering(text, display):
            return [
                f"{ident}: artifact {relative!r} tidak memuat display {display!r}"
            ]
        return []

    def _resolve(self, relative: str) -> Path | None:
        root = self.paths.dir.resolve()
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return None
        return candidate


def _contains_rendering(text: str, display: Any) -> bool:
    """Apakah artefak memuat `display` sebagai token utuh.

    Hanya `display` yang diterima: `str(value)` membuat `value: 3` cocok dengan
    sembarang keluaran yang memuat digit 3 (mis. `rows=3`), dan pencocokan
    substring membuat `display: "3"` cocok dengan `rows=13`. Token utuh berarti
    baris (setelah di-strip) sama persis dengan `display`, atau `display`
    diapit karakter non-alfanumerik. Bentuk Indonesia seperti `-12,4%` memang
    sudah menjadi isi `display`, jadi tidak perlu render angka lain.
    """
    if not _is_text(display):
        return False
    needle = display.strip()
    if not needle:
        return False
    for line in text.splitlines():
        if line.strip() == needle:
            return True
    start = 0
    while True:
        index = text.find(needle, start)
        if index < 0:
            return False
        end = index + len(needle)
        before = text[index - 1] if index > 0 else ""
        after = text[end] if end < len(text) else ""
        if not before.isalnum() and not after.isalnum():
            return True
        start = index + 1


def next_deepdive_path(paths: RunPaths) -> Path:
    """`evidence/deepdive/NN.json` berikutnya, tanpa menimpa berkas lama."""
    highest = 0
    directory = paths.deepdive_dir
    if directory.is_dir():
        for child in directory.iterdir():
            match = _DEEPDIVE_RE.match(child.name)
            if match and child.is_file():
                highest = max(highest, int(match.group(1)))
    return directory / f"{highest + 1:02d}.json"


def deepdive_due(
    *,
    cells_since_checkpoint: int,
    stall_streak: int,
    every: int,
    stall_limit: int,
) -> str | None:
    """Pemicu deep-dive: stagnasi menang atas jadwal."""
    if stall_streak >= stall_limit:
        return "stall"
    if cells_since_checkpoint >= every:
        return "every"
    return None
