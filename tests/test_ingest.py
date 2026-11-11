"""Tes ingest dan profil deterministik (M1)."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import Workbook

from swarmfold.ingest import ingest
from swarmfold.runtime import RunPaths


def _run(tmp_path: Path, run_id: str = "2026-11-11-test") -> RunPaths:
    return RunPaths(root=tmp_path / "runs", run_id=run_id)


def _profile(run: RunPaths) -> dict:
    return json.loads(run.profile_file.read_text(encoding="utf-8"))


def test_all_five_formats(tmp_path: Path) -> None:
    source = tmp_path / "sumber"
    source.mkdir()

    csv_path = source / "csv_data.csv"
    csv_path.write_text(
        "id,nama,total\n1,A,10.5\n2,B,20.0\n3,C,30.25\n", encoding="utf-8"
    )

    tsv_path = source / "tsv_data.tsv"
    tsv_path.write_text("id\tnama\ttotal\n1\tA\t10.5\n2\tB\t20.0\n", encoding="utf-8")

    xlsx_path = source / "xlsx_data.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["id", "nama", "total"])
    sheet.append([1, "A", 10.5])
    sheet.append([2, "B", 20.0])
    workbook.save(xlsx_path)

    json_path = source / "json_data.json"
    json_path.write_text(
        json.dumps(
            [
                {"id": 1, "nama": "A", "total": 10.5},
                {"id": 2, "nama": "B", "total": 20.0},
            ]
        ),
        encoding="utf-8",
    )

    parquet_path = source / "parquet_data.parquet"
    pd.DataFrame({"id": [1, 2], "nama": ["A", "B"], "total": [10.5, 20.0]}).to_parquet(
        parquet_path, index=False
    )

    run = _run(tmp_path)
    result = ingest(
        [csv_path, tsv_path, xlsx_path, json_path, parquet_path], run
    )

    assert [item.format for item in result.files] == [
        "csv",
        "tsv",
        "xlsx",
        "json",
        "parquet",
    ]
    assert [item.rows for item in result.files] == [3, 2, 2, 2, 2]
    assert [item.cols for item in result.files] == [3, 3, 3, 3, 3]

    assert run.profile_file.exists()
    profile = _profile(run)
    assert len(profile["files"]) == 5
    assert all(len(entry["columns"]) == 3 for entry in profile["files"])
    for item in result.files:
        assert (run.dir / item.input_path).exists()
        assert (run.dir / item.data_path).exists()


def test_semicolon_cp1252_decimal_comma(tmp_path: Path) -> None:
    path = tmp_path / "penjualan.csv"
    text = (
        "invoice_id;pelanggan;total\n"
        "INV-1;André;1.234,56\n"
        "INV-2;Budí;2.500,00\n"
        "INV-3;Citra;999,99\n"
    )
    path.write_bytes(text.encode("cp1252"))

    run = _run(tmp_path)
    result = ingest([path], run)
    item = result.files[0]

    assert item.encoding == "cp1252"
    assert item.delimiter == ";"
    assert item.rows == 3
    assert item.cols == 3

    frame = pd.read_csv(run.data_dir / "penjualan.csv")
    assert list(frame["total"]) == [1234.56, 2500.0, 999.99]
    assert str(frame["total"].dtype) == "float64"

    profile = _profile(run)
    entry = profile["files"][0]
    assert entry["encoding"] == "cp1252"
    assert entry["delimiter"] == ";"
    total = next(column for column in entry["columns"] if column["name"] == "total")
    assert total["dtype"] == "float64"
    assert total["casts"] == ["decimal_comma"]
    assert total["samples"][0] == "1234.56"


def test_join_candidate_between_two_files(tmp_path: Path) -> None:
    left_path = tmp_path / "pesanan.csv"
    right_path = tmp_path / "pelanggan.csv"

    pd.DataFrame(
        {
            "customer_id": [f"C{index % 50}" for index in range(100)],
            "total": np.arange(100, dtype=float),
        }
    ).to_csv(left_path, index=False)

    pd.DataFrame(
        {
            "id": [f"C{index}" for index in range(93)],
            "nama": [f"N{index}" for index in range(93)],
        }
    ).to_csv(right_path, index=False)

    run = _run(tmp_path)
    result = ingest([left_path, right_path], run)

    assert len(result.files) == 2
    joins = result.profile["joins"]
    match = [
        join
        for join in joins
        if join["left"] == "pesanan.csv"
        and join["right"] == "pelanggan.csv"
        and join["left_columns"] == ["customer_id"]
        and join["right_columns"] == ["id"]
    ]
    assert match, f"tidak ada kandidat join: {joins}"
    join = match[0]
    assert join["overlap"] > 0.8
    assert join["cardinality"] == "many_to_one"
    assert join["fanout_risk"] == "none"


def test_datasets_merge_files_sharing_a_key(tmp_path: Path) -> None:
    left_path = tmp_path / "pesanan.csv"
    right_path = tmp_path / "pelanggan.csv"

    pd.DataFrame(
        {
            "customer_id": [f"C{index % 40}" for index in range(120)],
            "total": np.arange(120, dtype=float),
        }
    ).to_csv(left_path, index=False)
    pd.DataFrame(
        {
            "id": [f"C{index}" for index in range(93)],
            "nama": [f"N{index}" for index in range(93)],
        }
    ).to_csv(right_path, index=False)

    result = ingest([left_path, right_path], _run(tmp_path))
    datasets = result.profile["datasets"]

    assert len(datasets) == 1
    assert datasets[0]["id"] == "D1"
    assert datasets[0]["files"] == ["pesanan.csv", "pelanggan.csv"]
    assert datasets[0]["rows"] == 213
    assert datasets[0]["keys"] == ["customer_id", "id"]


def test_datasets_keep_unrelated_files_apart(tmp_path: Path) -> None:
    penjualan_path = tmp_path / "penjualan.csv"
    catatan_path = tmp_path / "catatan.csv"

    pd.DataFrame(
        {"produk": ["Kopi", "Teh", "Roti"] * 5, "qty": list(range(15))}
    ).to_csv(penjualan_path, index=False)
    pd.DataFrame(
        {"nama": ["Ani", "Budi", "Citra", "Dewi", "Eko"], "catatan": list("abcde")}
    ).to_csv(catatan_path, index=False)

    result = ingest([penjualan_path, catatan_path], _run(tmp_path))
    datasets = result.profile["datasets"]

    assert [item["id"] for item in datasets] == ["D1", "D2"]
    assert [item["files"] for item in datasets] == [["penjualan.csv"], ["catatan.csv"]]
    assert [item["keys"] for item in datasets] == [[], []]


def test_datasets_ignore_same_name_column_without_overlap(tmp_path: Path) -> None:
    left_path = tmp_path / "toko_a.csv"
    right_path = tmp_path / "toko_b.csv"

    pd.DataFrame(
        {
            "kota": ["Bandung", "Jakarta", "Surabaya", "Medan"] * 3,
            "omzet": np.arange(12, dtype=float),
        }
    ).to_csv(left_path, index=False)
    pd.DataFrame(
        {
            "kota": ["Makassar", "Semarang", "Denpasar", "Palembang"] * 3,
            "omzet": np.arange(12, dtype=float) + 100,
        }
    ).to_csv(right_path, index=False)

    result = ingest([left_path, right_path], _run(tmp_path))
    datasets = result.profile["datasets"]

    # Kandidat join tetap tercatat, tetapi isinya tidak beririsan sehingga
    # kedua berkas bukan satu kelompok.
    assert any(
        join["left_columns"] == ["kota"] and join["overlap"] == 0.0
        for join in result.profile["joins"]
    )
    assert len(datasets) == 2


def test_datasets_do_not_merge_on_date_column_alone(tmp_path: Path) -> None:
    left_path = tmp_path / "januari.csv"
    right_path = tmp_path / "februari.csv"
    dates = [f"2025-01-{day:02d}" for day in range(1, 13)]

    pd.DataFrame({"tanggal": dates, "total": np.arange(12, dtype=float)}).to_csv(
        left_path, index=False
    )
    pd.DataFrame(
        {"tanggal": dates, "total": np.arange(12, dtype=float) + 500}
    ).to_csv(right_path, index=False)

    result = ingest([left_path, right_path], _run(tmp_path))
    datasets = result.profile["datasets"]

    assert len(datasets) == 2
    assert [item["files"] for item in datasets] == [["januari.csv"], ["februari.csv"]]


def test_input_files_are_read_only_and_hashed(tmp_path: Path) -> None:
    path = tmp_path / "data.csv"
    path.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")

    run = _run(tmp_path)
    result = ingest([path], run)

    stored = run.input_dir / "data.csv"
    assert stored.exists()
    assert stored.stat().st_mode & 0o222 == 0
    assert not os.access(stored, os.W_OK)

    digest = hashlib.sha256(stored.read_bytes()).hexdigest()
    assert digest == result.files[0].sha256
    assert result.files[0].input_path == "input/data.csv"

    work_copy = run.dir / result.files[0].data_path
    assert work_copy.stat().st_mode & 0o222 == 0

    # Sumber asli tidak boleh berubah.
    assert path.stat().st_mode & 0o222 != 0
    assert path.read_text(encoding="utf-8") == "a,b\n1,2\n3,4\n"


def test_hundred_thousand_rows_under_thirty_seconds(tmp_path: Path) -> None:
    path = tmp_path / "besar.csv"
    rows = 100_000
    rng = np.random.default_rng(0)
    frame = pd.DataFrame(
        {
            "invoice_id": [f"INV-{index:06d}" for index in range(rows)],
            "tanggal": pd.date_range("2024-01-01", periods=rows, freq="min").astype(str),
            "pelanggan": rng.choice([f"C{index}" for index in range(500)], rows),
            "produk": rng.choice([f"P{index}" for index in range(40)], rows),
            "qty": rng.integers(1, 10, rows),
            "harga": rng.uniform(1_000, 100_000, rows).round(2),
            "total": rng.uniform(1_000, 1_000_000, rows).round(2),
            "kanal": rng.choice(["toko", "online", "reseller"], rows),
        }
    )
    frame.to_csv(path, index=False)

    run = _run(tmp_path)
    started = time.perf_counter()
    result = ingest([path], run)
    elapsed = time.perf_counter() - started

    assert result.files[0].rows == rows
    assert result.files[0].cols == 8
    assert elapsed < 30, f"ingest butuh {elapsed:.2f} detik"


def test_profile_has_no_secrets_or_urls(tmp_path: Path) -> None:
    path = tmp_path / "penjualan.csv"
    path.write_text("id,total\n1,10.5\n2,20.0\n", encoding="utf-8")

    run = _run(tmp_path)
    ingest([path], run)

    raw = run.profile_file.read_text(encoding="utf-8")
    assert "api_key" not in raw
    assert "http" not in raw


def _column(profile: dict, name: str) -> dict:
    entry = profile["files"][0]
    return next(column for column in entry["columns"] if column["name"] == name)


def test_european_thousands_dot_and_decimal_comma_casts(tmp_path: Path) -> None:
    path = tmp_path / "europe.csv"
    path.write_text('id,total\n1,"1.234,56"\n2,"12,5"\n', encoding="utf-8")

    run = _run(tmp_path)
    ingest([path], run)

    frame = pd.read_csv(run.data_dir / "europe.csv")
    assert list(frame["total"]) == [1234.56, 12.5]
    assert str(frame["total"].dtype) == "float64"

    total = _column(_profile(run), "total")
    assert total["casts"] == ["decimal_comma"]
    assert "kolom 'total' dikonversi dari desimal koma" in _profile(run)["warnings"]


def test_us_thousands_separator_is_not_cast(tmp_path: Path) -> None:
    path = tmp_path / "us.csv"
    path.write_text('id,total\n1,"1,234"\n2,"5,678"\n3,"9,012"\n', encoding="utf-8")

    run = _run(tmp_path)
    ingest([path], run)

    frame = pd.read_csv(run.data_dir / "us.csv", dtype={"total": str})
    assert list(frame["total"]) == ["1,234", "5,678", "9,012"]

    profile = _profile(run)
    total = _column(profile, "total")
    assert total["dtype"] == "object"
    assert total["casts"] == ["ambiguous_comma"]
    assert any("ambigu" in warning and "total" in warning for warning in profile["warnings"])


def test_mixed_comma_column_is_not_cast(tmp_path: Path) -> None:
    path = tmp_path / "campur.csv"
    path.write_text('id,total\n1,"1,234"\n2,"12,50"\n', encoding="utf-8")

    run = _run(tmp_path)
    ingest([path], run)

    frame = pd.read_csv(run.data_dir / "campur.csv", dtype={"total": str})
    assert list(frame["total"]) == ["1,234", "12,50"]

    profile = _profile(run)
    total = _column(profile, "total")
    assert total["dtype"] == "object"
    assert total["casts"] == ["ambiguous_comma"]
    assert any("ambigu" in warning for warning in profile["warnings"])


def test_single_decimal_place_casts(tmp_path: Path) -> None:
    path = tmp_path / "satu_desimal.csv"
    path.write_text('id,total\n1,"1,5"\n2,"2,0"\n', encoding="utf-8")

    run = _run(tmp_path)
    ingest([path], run)

    frame = pd.read_csv(run.data_dir / "satu_desimal.csv")
    assert list(frame["total"]) == [1.5, 2.0]
    assert str(frame["total"].dtype) == "float64"

    profile = _profile(run)
    assert _column(profile, "total")["casts"] == ["decimal_comma"]
    assert "kolom 'total' dikonversi dari desimal koma" in profile["warnings"]
