"""Skema jawaban reviewer dan pembacanya.

Reviewer adalah model yang lebih kuat yang memeriksa diff usulan worker.
Jawabannya harus bisa diproses mesin, bukan prosa: tanpa `verdict` yang tegas,
loop tidak tahu harus menerapkan patch, meminta revisi, atau membuangnya.

Yang dijaga di sini: `revise` wajib membawa patch yang lolos `patcher.check_scope`,
`approve` tidak boleh membawa patch (kalau membawa, ia sebenarnya `revise`),
dan temuan wajib punya `file`, `issue`, dan `severity`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

from . import patcher

VERDICTS = ("approve", "revise", "reject")
SEVERITIES = ("critical", "high", "medium", "low")
#: Alasan minimal sependek ini; satu kata bukan alasan.
MIN_REASON = 10

_FENCE = re.compile(r"^\s*```(?:json)?\s*(?P<isi>.*?)\s*```\s*$", re.DOTALL)

#: Instruksi tetap untuk peran reviewer. Sengaja tinggal di paket eval, bukan di
#: `prompts/`: berkas ini di luar jangkauan patch, jadi varian tidak bisa
#: menulis ulang penilainya sendiri. Prompt worker berbahasa Inggris, jadi
#: instruksi ini juga, supaya istilah di dalam patch cocok dengan yang dibaca.
SYSTEM = """You are the reviewer in an evolution loop for a data-analysis agent.

The worker reads CSV input, writes notebook cells, and reports findings with
evidence. A ground-truth benchmark scores each run on recall of planted anchors,
false discovery, contradictions, numeric error, calibration, and artifact
defects. You are given the scores of the current system and the in-scope source
files. Find the rule that explains the scored failure, then propose the
smallest patch that fixes it.

Hard rules:
- Patch only these prefixes: {allowed}. Nothing else is writable.
- At most {max_files} files and {max_lines} changed lines in total.
- The patch must be a unified diff that `git apply` accepts from the repo root,
  with correct context lines taken from the files shown to you.
- Every hunk must be justified by a failure you name in `findings`, quoting the
  case id and the metric or defect that failed.
- Never weaken evidence rules, scoring, or tests. Never touch eval or verify
  code. Never add a rule that only helps one case id.
- Prefer changing one rule in one prompt file over rewriting a file.

Answer with one JSON object and nothing else:
{schema}
"""


class ChatClient(Protocol):
    """Bagian `ModelClient` yang dipakai reviewer; cukup untuk diuji dengan fake."""

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> Any: ...


def system_prompt() -> str:
    """Instruksi reviewer, dengan batas patch diisi dari `patcher` itu sendiri."""
    return SYSTEM.format(
        allowed=", ".join(patcher.ALLOWED),
        max_files=patcher.MAX_FILES,
        max_lines=patcher.MAX_TOTAL_LINES,
        schema=json.dumps(schema(), ensure_ascii=False),
    )


def build_messages(context: dict[str, Any]) -> list[dict[str, str]]:
    """Pesan untuk model reviewer: instruksi tetap + konteks sebagai JSON."""
    return [
        {"role": "system", "content": system_prompt()},
        {
            "role": "user",
            "content": json.dumps(context, ensure_ascii=False, indent=2, sort_keys=True),
        },
    ]


def from_model(client: ChatClient, context: dict[str, Any]) -> Review:
    """Tanya model reviewer lalu baca jawabannya; `ReviewError` bila tidak sesuai."""
    turn = client.chat(build_messages(context))
    return parse(turn.content)


class ReviewError(ValueError):
    """Jawaban reviewer tidak sesuai skema."""


@dataclass(frozen=True)
class Finding:
    file: str
    issue: str
    severity: str
    line: int | None = None


@dataclass(frozen=True)
class Review:
    verdict: str
    reason: str
    findings: tuple[Finding, ...]
    patch: str = ""


def schema() -> dict[str, Any]:
    """Skema JSON untuk ditempel di prompt reviewer."""
    return {
        "type": "object",
        "required": ["verdict", "reason", "findings"],
        "properties": {
            "verdict": {"enum": list(VERDICTS)},
            "reason": {"type": "string", "minLength": MIN_REASON},
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["file", "issue", "severity"],
                    "properties": {
                        "file": {"type": "string"},
                        "line": {"type": "integer"},
                        "issue": {"type": "string"},
                        "severity": {"enum": list(SEVERITIES)},
                    },
                },
            },
            "patch": {"type": "string", "description": "wajib bila verdict=revise"},
        },
    }


def _load(payload: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    teks = str(payload).strip()
    match = _FENCE.match(teks)
    if match:
        teks = match.group("isi")
    try:
        data = json.loads(teks)
    except json.JSONDecodeError as error:
        raise ReviewError(f"jawaban reviewer bukan JSON: {error}") from error
    if not isinstance(data, dict):
        raise ReviewError("jawaban reviewer harus objek JSON")
    return data


def _findings(raw: Any) -> tuple[Finding, ...]:
    if not isinstance(raw, list):
        raise ReviewError("findings harus daftar")
    hasil: list[Finding] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ReviewError("finding harus objek")
        for key in ("file", "issue", "severity"):
            if not str(item.get(key) or "").strip():
                raise ReviewError(f"finding tanpa {key}")
        severity = str(item["severity"])
        if severity not in SEVERITIES:
            raise ReviewError(f"severity tidak dikenal: {severity!r}")
        line = item.get("line")
        if line is not None and (isinstance(line, bool) or not isinstance(line, int)):
            raise ReviewError("line harus bilangan bulat")
        hasil.append(
            Finding(
                file=str(item["file"]),
                issue=str(item["issue"]),
                severity=severity,
                line=line,
            )
        )
    return tuple(hasil)


def parse(payload: str | dict[str, Any]) -> Review:
    """Baca jawaban reviewer; lempar `ReviewError` bila tidak sesuai skema."""
    data = _load(payload)
    verdict = str(data.get("verdict") or "")
    if verdict not in VERDICTS:
        raise ReviewError(f"verdict tidak dikenal: {verdict!r}; pilih {VERDICTS}")
    reason = str(data.get("reason") or "").strip()
    if len(reason) < MIN_REASON:
        raise ReviewError(f"reason terlalu pendek (minimal {MIN_REASON} karakter)")
    findings = _findings(data.get("findings") or [])
    patch = str(data.get("patch") or "")

    if verdict == "revise":
        if not patch.strip():
            raise ReviewError("verdict revise wajib membawa patch")
        masalah = patcher.check_scope(patch)
        if masalah:
            raise ReviewError("patch reviewer di luar jangkauan: " + "; ".join(masalah))
        if not findings:
            raise ReviewError("verdict revise wajib menyebut temuan yang diperbaiki")
    elif patch.strip():
        raise ReviewError(f"verdict {verdict} tidak boleh membawa patch")
    if verdict == "reject" and not findings:
        raise ReviewError("verdict reject wajib menyebut temuan")

    return Review(verdict=verdict, reason=reason, findings=findings, patch=patch)
