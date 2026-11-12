"""Tes skema jawaban reviewer.

Reviewer yang menjawab dengan prosa tidak bisa dipakai loop, dan reviewer yang
menyetujui sambil membawa patch berarti dua hal sekaligus. Skema ini memaksa
satu jawaban yang jelas, dan menolak patch yang keluar dari jangkauan sebelum
patch itu sempat diterapkan.
"""

from __future__ import annotations

import json

import pytest

from swarmfold_eval import reviewer

PATCH = (
    "diff --git a/prompts/style.md b/prompts/style.md\n"
    "--- a/prompts/style.md\n"
    "+++ b/prompts/style.md\n"
    "@@ -1 +1 @@\n"
    "-lama\n"
    "+baru\n"
)


def _jawaban(**ubah: object) -> dict:
    dasar = {
        "verdict": "approve",
        "reason": "aturan persen sudah sesuai kontrak evidence",
        "findings": [],
    }
    dasar.update(ubah)
    return dasar


def test_approve_without_patch() -> None:
    hasil = reviewer.parse(_jawaban())

    assert hasil.verdict == "approve"
    assert hasil.patch == ""


def test_accepts_fenced_json() -> None:
    teks = "```json\n" + json.dumps(_jawaban()) + "\n```"

    assert reviewer.parse(teks).verdict == "approve"


def test_revise_requires_patch() -> None:
    with pytest.raises(reviewer.ReviewError, match="patch"):
        reviewer.parse(
            _jawaban(
                verdict="revise",
                findings=[{"file": "prompts/style.md", "issue": "salah", "severity": "high"}],
            )
        )


def test_revise_patch_must_be_in_scope() -> None:
    luar = PATCH.replace("prompts/style.md", "src/swarmfold_verify/scorer.py")

    with pytest.raises(reviewer.ReviewError, match="jangkauan"):
        reviewer.parse(
            _jawaban(
                verdict="revise",
                patch=luar,
                findings=[{"file": "x", "issue": "y", "severity": "high"}],
            )
        )


def test_revise_needs_findings() -> None:
    with pytest.raises(reviewer.ReviewError, match="temuan"):
        reviewer.parse(_jawaban(verdict="revise", patch=PATCH))


def test_approve_may_not_carry_patch() -> None:
    with pytest.raises(reviewer.ReviewError, match="tidak boleh membawa patch"):
        reviewer.parse(_jawaban(patch=PATCH))


def test_reject_needs_findings() -> None:
    with pytest.raises(reviewer.ReviewError, match="temuan"):
        reviewer.parse(_jawaban(verdict="reject"))


def test_unknown_verdict_rejected() -> None:
    with pytest.raises(reviewer.ReviewError, match="verdict"):
        reviewer.parse(_jawaban(verdict="setuju"))


def test_short_reason_rejected() -> None:
    with pytest.raises(reviewer.ReviewError, match="reason"):
        reviewer.parse(_jawaban(reason="oke"))


def test_unknown_severity_rejected() -> None:
    with pytest.raises(reviewer.ReviewError, match="severity"):
        reviewer.parse(
            _jawaban(
                verdict="reject",
                findings=[{"file": "prompts/style.md", "issue": "x", "severity": "fatal"}],
            )
        )


def test_finding_without_file_rejected() -> None:
    with pytest.raises(reviewer.ReviewError, match="file"):
        reviewer.parse(_jawaban(verdict="reject", findings=[{"issue": "x", "severity": "high"}]))


def test_schema_mentions_every_verdict() -> None:
    skema = reviewer.schema()

    assert set(skema["properties"]["verdict"]["enum"]) == set(reviewer.VERDICTS)
    assert "patch" in skema["properties"]
