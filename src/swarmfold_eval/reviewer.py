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
from typing import Any

from . import patcher

VERDICTS = ("approve", "revise", "reject")
SEVERITIES = ("critical", "high", "medium", "low")
#: Alasan minimal sependek ini; satu kata bukan alasan.
MIN_REASON = 10

_FENCE = re.compile(r"^\s*```(?:json)?\s*(?P<isi>.*?)\s*```\s*$", re.DOTALL)


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
