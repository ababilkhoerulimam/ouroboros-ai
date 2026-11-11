"""Tes triage deterministik: business penuh, cleaning, atau belum siap."""

from __future__ import annotations

from swarmfold.triage import (
    MODE_CLEANING,
    MODE_FULL,
    MODE_INSUFFICIENT,
    triage_profile,
)


def _col(name: str, dtype: str = "object", samples: tuple[str, ...] = ("a", "b", "c")) -> dict:
    return {"name": name, "dtype": dtype, "samples": list(samples)}


def _profile(*columns: dict, rows: int = 10, cols: int | None = None) -> dict:
    return {
        "files": [
            {
                "rows": rows,
                "cols": cols if cols is not None else len(columns),
                "columns": list(columns),
            }
        ]
    }


def test_business_data_runs_full_pipeline() -> None:
    profile = _profile(
        _col("tanggal", samples=("2025-01-05", "2025-02-05", "2025-03-05")),
        _col("total", "int64", ("120000", "150000", "90000")),
    )

    result = triage_profile(profile)

    assert result.mode == MODE_FULL
    assert result.missing == []
    assert any("nominal" in reason for reason in result.reasons)


def test_data_without_business_signals_is_cleaned_only() -> None:
    profile = _profile(_col("nama"), _col("catatan"))

    result = triage_profile(profile)

    assert result.mode == MODE_CLEANING
    assert any("sinyal bisnis" in reason for reason in result.reasons)
    assert len(result.missing) == 3


def test_nominal_without_date_or_entity_is_cleaned_only() -> None:
    profile = _profile(_col("total", "int64", ("100", "200", "300")), _col("catatan"))

    result = triage_profile(profile)

    assert result.mode == MODE_CLEANING
    assert any("tanggal" in item for item in result.missing)


def test_entity_without_nominal_is_cleaned_only() -> None:
    profile = _profile(
        _col("pelanggan_id", samples=("P-01", "P-02", "P-03")), _col("catatan")
    )

    result = triage_profile(profile)

    assert result.mode == MODE_CLEANING
    assert any("nominal" in item for item in result.missing)


def test_tiny_data_is_insufficient() -> None:
    profile = _profile(_col("a"), rows=2, cols=1)

    result = triage_profile(profile)

    assert result.mode == MODE_INSUFFICIENT
    assert "2 baris" in result.reasons[0]


def test_empty_profile_is_insufficient() -> None:
    assert triage_profile({}).mode == MODE_INSUFFICIENT
