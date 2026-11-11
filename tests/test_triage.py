"""Tes triage deterministik: business penuh, generic penuh, cleaning, belum siap."""

from __future__ import annotations

from swarmfold.triage import (
    MODE_CLEANING,
    MODE_FULL,
    MODE_INSUFFICIENT,
    PACK_BUSINESS,
    PACK_GENERIC,
    triage_profile,
)


def _col(
    name: str,
    dtype: str = "object",
    samples: tuple[str, ...] = ("a", "b", "c"),
    distinct: int | None = None,
) -> dict:
    return {
        "name": name,
        "dtype": dtype,
        "samples": list(samples),
        "distinct": len(set(samples)) if distinct is None else distinct,
    }


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
    assert result.pack == PACK_BUSINESS
    assert result.missing == []
    assert any("nominal" in reason for reason in result.reasons)


def test_measure_with_date_runs_generic_pipeline() -> None:
    profile = _profile(
        _col("waktu", samples=("2025-01-05", "2025-02-05", "2025-03-05")),
        _col("suhu", "float64", ("21.4", "22.1", "23.0")),
    )

    result = triage_profile(profile)

    assert result.mode == MODE_FULL
    assert result.pack == PACK_GENERIC
    assert any("ukuran" in reason for reason in result.reasons)


def test_measure_with_category_runs_generic_pipeline() -> None:
    profile = _profile(
        _col("suhu", "float64", ("21.4", "22.1", "23.0")),
        _col("status", samples=("normal", "tinggi", "normal")),
    )

    result = triage_profile(profile)

    assert result.mode == MODE_FULL
    assert result.pack == PACK_GENERIC


def test_measure_without_comparator_is_cleaned_only() -> None:
    profile = _profile(
        _col("suhu", "float64", ("21.4", "22.1", "23.0")),
        _col("catatan", distinct=200),
    )

    result = triage_profile(profile)

    assert result.mode == MODE_CLEANING
    assert result.pack == PACK_GENERIC
    assert any("pembanding" in reason for reason in result.reasons)


def test_identifier_is_not_a_measure() -> None:
    profile = _profile(_col("baris_id", "int64", ("1", "2", "3")), _col("nama"))

    result = triage_profile(profile)

    assert result.mode == MODE_CLEANING
    assert result.pack == PACK_GENERIC


def test_data_without_business_signals_is_cleaned_only() -> None:
    profile = _profile(_col("nama"), _col("catatan"))

    result = triage_profile(profile)

    assert result.mode == MODE_CLEANING
    assert result.pack == PACK_GENERIC
    assert any("sinyal bisnis" in reason for reason in result.reasons)
    assert len(result.missing) == 3


def test_entity_without_nominal_is_cleaned_only() -> None:
    profile = _profile(
        _col("pelanggan_id", samples=("P-01", "P-02", "P-03")), _col("catatan")
    )

    result = triage_profile(profile)

    assert result.mode == MODE_CLEANING
    assert result.pack == PACK_GENERIC
    assert any("nominal" in item for item in result.missing)


def test_tiny_data_is_insufficient() -> None:
    profile = _profile(_col("a"), rows=2, cols=1)

    result = triage_profile(profile)

    assert result.mode == MODE_INSUFFICIENT
    assert result.pack == PACK_GENERIC
    assert "2 baris" in result.reasons[0]


def test_tiny_business_data_keeps_business_pack() -> None:
    profile = _profile(_col("total", "int64", ("100", "200", "300")), rows=2, cols=1)

    assert triage_profile(profile).pack == PACK_BUSINESS


def test_empty_profile_is_insufficient() -> None:
    assert triage_profile({}).mode == MODE_INSUFFICIENT
