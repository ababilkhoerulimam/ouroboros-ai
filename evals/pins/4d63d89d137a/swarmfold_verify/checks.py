"""Pemeriksaan deterministik atas artefak run.

Semua pemeriksaan di sini berbasis angka dan berkas, bukan penilaian model:
angka di `display` harus muncul di output cell, slot laporan harus punya
evidence, dan klaim fase harus punya berkas evidence-nya.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

NUMBER = re.compile(r"-?\d+(?:[.,]\d+)*")
#: Id evidence yang disebut di prosa laporan, dirender atau tidak.
ID_TOKEN = re.compile(r"\bE-\d{3}\b")
#: Fase yang wajib meninggalkan `evidence/F{n}.json`. F7 tidak termasuk: ia
#: menghasilkan `laporan.md`, bukan berkas evidence.
EVIDENCE_PHASES = ("F1", "F2", "F3", "F4", "F5", "F6")
#: Toleransi relatif saat mencocokkan angka `display` ke output cell.
_TOL = 1e-3


def to_float(token: str) -> float | None:
    """Ubah angka bergaya Indonesia atau Inggris menjadi float.

    ``1.234,56`` dan ``1,234.56`` sama-sama 1234.56; ``4.627`` dibaca sebagai
    ribuan karena ekornya tiga digit, sedangkan ``0,0080`` sebagai desimal.
    """
    negatif = token.startswith("-")
    teks = token.lstrip("-")
    if "." in teks and "," in teks:
        desimal = "." if teks.rfind(".") > teks.rfind(",") else ","
        ribuan = "," if desimal == "." else "."
        teks = teks.replace(ribuan, "").replace(desimal, ".")
    elif "." in teks or "," in teks:
        pemisah = "." if "." in teks else ","
        kepala, _, ekor = teks.partition(pemisah)
        if len(ekor) == 3 and 1 <= len(kepala) <= 3:
            teks = kepala + ekor
        else:
            teks = kepala + "." + ekor
    try:
        nilai = float(teks)
    except ValueError:
        return None
    return -nilai if negatif else nilai


def numbers(text: str) -> list[float]:
    hasil = []
    for token in NUMBER.findall(text):
        nilai = to_float(token)
        if nilai is not None:
            hasil.append(nilai)
    return hasil


def _appears(value: float, candidates: list[float]) -> bool:
    for candidate in candidates:
        skala = max(abs(value), abs(candidate), 1.0)
        if abs(candidate - value) / skala <= _TOL:
            return True
    return False


def load_findings(run_dir: Path) -> list[dict[str, Any]]:
    """Semua finding dari `evidence/F*.json`, ditandai fase asalnya."""
    findings: list[dict[str, Any]] = []
    for path in sorted(Path(run_dir).glob("evidence/F*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        for item in data.get("findings") or []:
            if isinstance(item, dict):
                findings.append({**item, "_phase": path.stem})
    return findings


def artifact_path(run_dir: Path, artifact: str) -> Path | None:
    """Path artifact bila benar-benar berada di dalam run, selain itu `None`.

    `artifact` datang dari run, jadi ia tidak boleh dipercaya: path absolut
    menang atas `run_dir` dan `..` bisa keluar. Tanpa penjagaan ini sebuah run
    dapat memenuhi `unsupported_number` dengan menunjuk berkas mana pun di
    mesin — termasuk truth-nya sendiri.
    """
    if not artifact:
        return None
    root = Path(run_dir).resolve()
    candidate = (root / artifact).resolve()
    return candidate if candidate.is_relative_to(root) else None


def _artifact_text(run_dir: Path, finding: dict[str, Any]) -> str:
    path = artifact_path(run_dir, str(finding.get("artifact") or ""))
    if path is None:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _defect(
    ident: str, kind: str, detail: str, where: str, *, scope: str = "run", subject: str = ""
) -> dict[str, str]:
    """`scope` memisahkan cacat per-finding dari cacat per-run.

    Scorer butuh pemisahan itu: cacat laporan yang dibagi jumlah temuan akan
    terlihat makin kecil justru ketika run menghasilkan lebih banyak temuan.
    """
    return {
        "id": ident,
        "kind": kind,
        "detail": detail,
        "where": where,
        "scope": scope,
        "subject": subject,
    }


#: Skala yang sah antara angka `display` dan angka artifact, dipicu kata pada
#: `display` itu sendiri. `84,13%` untuk `0.8413` dan `Rp 362,4 juta` untuk
#: `362400000` sama-sama bentuk terbulatkan, bukan kontradiksi.
_SCALE_HINTS = (
    ("%", 1e2),
    ("ribu", 1e-3),
    ("juta", 1e-6),
    ("miliar", 1e-9),
    ("triliun", 1e-12),
)


def _candidates(finding: dict[str, Any], artifact: list[float]) -> list[float]:
    """Angka yang sah untuk `display`: isi artifact, nilai finding, dan skalanya.

    Skala hanya diterapkan bila `display` menyebutnya (`%`, `juta`). Tanpa
    syarat itu, `count` 16,9 dengan `display: "1.690"` akan lolos sebagai
    "pembulatan" padahal angkanya berbeda seratus kali.
    """
    kandidat = list(artifact)
    value = finding.get("value")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        kandidat.append(float(value))
    teks = str(finding.get("display") or "").lower()
    skala = [1.0] + [faktor for kata, faktor in _SCALE_HINTS if kata in teks]
    return [angka * faktor for angka in kandidat for faktor in skala]


def check_evidence(run_dir: Path) -> list[dict[str, str]]:
    """Cacat pada finding: angka tak tercetak, rasio tampil desimal."""
    defects: list[dict[str, str]] = []
    # Beberapa finding sering menunjuk cell yang sama; artifact besar jangan
    # dibaca ulang untuk tiap finding.
    cache: dict[str, str] = {}
    for index, finding in enumerate(load_findings(run_dir), start=1):
        ident = str(finding.get("id") or f"#{index}")
        display = str(finding.get("display") or "")
        nilai_display = numbers(display)
        artifact = str(finding.get("artifact") or "")
        if artifact not in cache:
            cache[artifact] = _artifact_text(run_dir, finding)
        kandidat = _candidates(finding, numbers(cache[artifact]))

        if artifact and artifact_path(run_dir, artifact) is None:
            defects.append(
                _defect(
                    f"D-{ident}-escape",
                    "artifact_outside_run",
                    f"artifact menunjuk ke luar run: {artifact!r}",
                    artifact,
                    scope="finding",
                    subject=ident,
                )
            )
            continue

        if nilai_display and not _appears(nilai_display[0], kandidat):
            defects.append(
                _defect(
                    f"D-{ident}-unsupported",
                    "unsupported_number",
                    f"angka pertama display {nilai_display[0]} tidak ada di artifact",
                    artifact,
                    scope="finding",
                    subject=ident,
                )
            )
        elif len(nilai_display) >= 2 and not all(_appears(v, kandidat) for v in nilai_display):
            # Validator internal hanya memeriksa angka pertama; ini menutup sisanya.
            defects.append(
                _defect(
                    f"D-{ident}-multi",
                    "multi_number_display",
                    "display memuat lebih dari satu angka dan tidak semuanya tercetak",
                    artifact,
                    scope="finding",
                    subject=ident,
                )
            )

        if str(finding.get("unit") or "") == "ratio" and "%" not in display:
            defects.append(
                _defect(
                    f"D-{ident}-decimal",
                    "decimal_percent",
                    f"rasio tampil sebagai desimal: {display!r}",
                    "display",
                    scope="finding",
                    subject=ident,
                )
            )
    return defects


def check_report(run_dir: Path) -> list[dict[str, str]]:
    """Cacat pada `laporan.md`: slot tersisa atau menyebut id tanpa evidence."""
    path = Path(run_dir) / "laporan.md"
    if not path.is_file():
        return [_defect("D-report-missing", "missing_report", "laporan.md tidak ada", "laporan.md")]
    teks = path.read_text(encoding="utf-8", errors="replace")
    known = {str(item.get("id") or "") for item in load_findings(run_dir)}
    defects: list[dict[str, str]] = []

    if "{{" in teks:
        defects.append(
            _defect("D-slot-leftover", "slot_leftover", "slot belum dirender", "laporan.md")
        )
    for ident in sorted(set(ID_TOKEN.findall(teks))):
        if ident not in known:
            defects.append(
                _defect(
                    f"D-{ident}-dangling",
                    "dangling_id",
                    f"laporan menyebut {ident} tetapi tidak ada di evidence",
                    "laporan.md",
                )
            )
    return defects


def check_phases(run_dir: Path) -> list[dict[str, str]]:
    """`done.json` mengklaim fase selesai tetapi berkas evidence-nya tidak ada."""
    done_path = Path(run_dir) / "done.json"
    if not done_path.is_file():
        return [_defect("D-done-missing", "missing_done", "done.json tidak ada", "done.json")]
    try:
        done = json.loads(done_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [_defect("D-done-corrupt", "corrupt_done", "done.json bukan JSON", "done.json")]
    if not isinstance(done, dict):
        return [
            _defect("D-done-corrupt", "corrupt_done", "done.json bukan objek JSON", "done.json")
        ]

    defects: list[dict[str, str]] = []
    for phase in done.get("phases_completed") or []:
        if phase in EVIDENCE_PHASES:
            if not (Path(run_dir) / "evidence" / f"{phase}.json").is_file():
                defects.append(
                    _defect(
                        f"D-{phase}-claim",
                        "phase_claim",
                        f"{phase} diklaim selesai tanpa evidence/{phase}.json",
                        "done.json",
                    )
                )
    return defects


def check_all(run_dir: Path) -> list[dict[str, str]]:
    return check_evidence(run_dir) + check_report(run_dir) + check_phases(run_dir)
