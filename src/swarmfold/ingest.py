"""Ingest multi-file dan profil deterministik (tanpa LLM).

Modul ini menyalin berkas asli ke `input/` (read-only), menulis salinan kerja
kanonik ke `data/`, lalu menghasilkan `profile.json`. Tidak ada panggilan
jaringan, tidak ada panggilan model, dan tidak ada output ke stdout.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .runtime import RunPaths, atomic_write_json, utc_now

#: Mode berkas read-only untuk `input/` dan `data/`.
_READ_ONLY = 0o444

_FORMAT_BY_SUFFIX = {
    ".csv": "csv",
    ".txt": "csv",
    ".tsv": "tsv",
    ".tab": "tsv",
    ".xlsx": "xlsx",
    ".xlsm": "xlsx",
    ".json": "json",
    ".parquet": "parquet",
    ".pq": "parquet",
}

_DELIMITERS = (",", ";", "\t", "|")

#: Urutan percobaan encoding. `latin-1` selalu berhasil dan menjadi jaring akhir.
_ENCODINGS = ("utf-8", "cp1252", "latin-1")

#: Keluarga angka berkoma: "1.234,56", "1.234" (ribuan titik), atau "12,5".
_DECIMAL_COMMA_RE = re.compile(r"^-?\d{1,3}(\.\d{3})*(,\d+)?$|^-?\d+,\d+$")
#: Bukti kuat desimal koma: koma diikuti 1-2 digit ("12,5", "999,99").
_DECIMAL_COMMA_EVIDENCE_RE = re.compile(r"^-?\d+,\d{1,2}$")
#: Pengelompokan ribuan murni tanpa bagian desimal ("1,234", "1,234,567").
_THOUSANDS_GROUP_RE = re.compile(r"^-?\d{1,3}(,\d{3})+$")
_DECIMAL_COMMA_MIN = 0.80

_MIN_UNIQUE_RATIO = 0.98
_MAX_CANDIDATE_KEYS = 5
_UNIQUE_EPS = 0.999

_MISSING_WARN_PCT = 0.40
_MAX_SAMPLES = 3
_MAX_SAMPLE_CHARS = 120

_JOIN_MIN_OVERLAP = 0.80
_JOIN_MIN_DISTINCT = 2
_JOIN_MAX_DISTINCT = 20_000

#: Ambang tepi kelompok data. Kandidat join boleh lemah (cukup nama kolom sama),
#: tetapi dua berkas baru dianggap satu kelompok bila nilai kuncinya benar
#: beririsan dan kolomnya cukup berisi.
_COMPONENT_MIN_OVERLAP = 0.80
_COMPONENT_MIN_DISTINCT = 3
#: Kolom bertanggal tidak boleh menjadi satu-satunya alasan dua berkas digabung:
#: dua tabel penjualan berbeda sama-sama punya `tanggal` tanpa saling terkait.
_DATE_NAME_RE = re.compile(
    r"(tanggal|tgl|date|waktu|time|bulan|month|periode|period|tahun|year)",
    re.IGNORECASE,
)


@dataclass
class IngestedFile:
    name: str
    input_path: str
    data_path: str
    sha256: str
    bytes: int
    format: str
    encoding: str | None
    delimiter: str | None
    rows: int
    cols: int


@dataclass
class IngestResult:
    files: list[IngestedFile]
    profile: dict[str, Any]
    warnings: list[str]


def ingest(paths: list[Path], run: RunPaths) -> IngestResult:
    """Salin, profil, dan tulis `profile.json` untuk setiap berkas masukan."""
    sources = [Path(p) for p in paths]
    if not sources:
        raise ValueError("tidak ada berkas untuk di-ingest")
    run.ensure()

    warnings: list[str] = []
    files: list[IngestedFile] = []
    file_profiles: list[dict[str, Any]] = []
    join_inputs: list[tuple[str, pd.DataFrame, dict[str, int]]] = []
    used_input: set[str] = set()
    used_data: set[str] = set()

    for source in sources:
        if not source.is_file():
            raise FileNotFoundError(f"berkas tidak ditemukan: {source}")

        fmt = _format_for(source)
        raw = source.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()

        stored_name = _reserve(source.name, used_input)
        input_dest = run.input_dir / stored_name
        input_dest.write_bytes(raw)
        os.chmod(input_dest, _READ_ONLY)

        frame, encoding, delimiter = _load_frame(raw, fmt)
        frame = _prepare_frame(frame)

        columns, distinct, duplicate_rows, duplicate_pct, file_warnings = _profile_frame(
            frame, source.name
        )
        warnings.extend(file_warnings)
        candidate_keys = _candidate_keys(frame, distinct)

        data_name = _reserve(f"{source.stem}.csv", used_data)
        data_dest = run.data_dir / data_name
        _write_canonical(frame, data_dest)

        rows = int(len(frame))
        cols = int(frame.shape[1])
        files.append(
            IngestedFile(
                name=source.name,
                input_path=run.relative(input_dest),
                data_path=run.relative(data_dest),
                sha256=digest,
                bytes=len(raw),
                format=fmt,
                encoding=encoding,
                delimiter=delimiter,
                rows=rows,
                cols=cols,
            )
        )
        file_profiles.append(
            {
                "name": source.name,
                "format": fmt,
                "encoding": encoding,
                "delimiter": delimiter,
                "sha256": digest,
                "bytes": len(raw),
                "rows": rows,
                "cols": cols,
                "columns": columns,
                "duplicate_rows": duplicate_rows,
                "duplicate_pct": duplicate_pct,
                "candidate_keys": candidate_keys,
            }
        )
        join_inputs.append((source.name, frame, distinct))

    joins = _join_candidates(join_inputs)
    profile: dict[str, Any] = {
        "generated_at": utc_now(),
        "files": file_profiles,
        "joins": joins,
        "datasets": _datasets(file_profiles, joins),
        "warnings": warnings,
    }
    atomic_write_json(run.profile_file, profile)
    return IngestResult(files=files, profile=profile, warnings=warnings)


# --------------------------------------------------------------------------- #
# Membaca berkas
# --------------------------------------------------------------------------- #


def _format_for(path: Path) -> str:
    fmt = _FORMAT_BY_SUFFIX.get(path.suffix.lower())
    if fmt is None:
        raise ValueError(
            f"format tidak didukung: {path.name} "
            "(dukungan: csv, tsv, xlsx, json, parquet)"
        )
    return fmt


def _decode_text(raw: bytes) -> tuple[str, str]:
    """Dekode bytes dengan urutan kandidat; BOM UTF-8 dilaporkan sebagai utf-8-sig."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    for encoding in _ENCODINGS:
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "\ufffd" not in text:
            return text, encoding
    raise ValueError("tidak ada encoding kandidat yang dapat mendekode berkas")


def _sniff_delimiter(text: str) -> str:
    sample = "\n".join(text.splitlines()[:20])
    if sample:
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            if dialect.delimiter in _DELIMITERS:
                return dialect.delimiter
        except csv.Error:
            pass
    lines = text.splitlines()[:5]
    counts = {d: sum(line.count(d) for line in lines) for d in _DELIMITERS}
    best = max(counts, key=lambda d: counts[d])
    return best if counts[best] > 0 else ","


def _load_frame(raw: bytes, fmt: str) -> tuple[pd.DataFrame, str | None, str | None]:
    if fmt in ("csv", "tsv"):
        text, encoding = _decode_text(raw)
        delimiter = "\t" if fmt == "tsv" else _sniff_delimiter(text)
        return pd.read_csv(io.StringIO(text), sep=delimiter), encoding, delimiter
    if fmt == "json":
        text, encoding = _decode_text(raw)
        return _frame_from_json(text), encoding, None
    if fmt == "xlsx":
        frame = pd.read_excel(io.BytesIO(raw), sheet_name=0, engine="openpyxl")
        return frame, None, None
    if fmt == "parquet":
        return pd.read_parquet(io.BytesIO(raw)), None, None
    raise ValueError(f"format tidak didukung: {fmt}")


def _frame_from_json(text: str) -> pd.DataFrame:
    payload = json.loads(text)
    if isinstance(payload, list):
        if not payload:
            return pd.DataFrame()
        if all(isinstance(item, dict) for item in payload):
            return pd.json_normalize(payload)
        return pd.DataFrame(payload)
    if isinstance(payload, dict):
        if payload and all(isinstance(value, list) for value in payload.values()):
            return pd.DataFrame(payload)
        return pd.DataFrame([payload])
    raise ValueError("JSON harus berupa daftar record atau object")


def _prepare_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Samakan tipe teks ke object agar profil konsisten lintas versi pandas."""
    frame.columns = [str(column) for column in frame.columns]
    for column in frame.columns:
        series = frame[column]
        if isinstance(series.dtype, pd.StringDtype):
            frame[column] = series.astype(object).where(series.notna(), np.nan)
    return frame


def _is_textual(series: pd.Series) -> bool:
    return isinstance(series.dtype, pd.StringDtype) or pd.api.types.is_object_dtype(series)


def _write_canonical(frame: pd.DataFrame, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    frame.to_csv(tmp, index=False, encoding="utf-8", lineterminator="\n")
    os.replace(tmp, dest)
    os.chmod(dest, _READ_ONLY)


def _reserve(filename: str, used: set[str]) -> str:
    stem, suffix = os.path.splitext(filename)
    candidate = filename
    counter = 2
    while candidate in used:
        candidate = f"{stem}_{counter}{suffix}"
        counter += 1
    used.add(candidate)
    return candidate


# --------------------------------------------------------------------------- #
# Profil kolom
# --------------------------------------------------------------------------- #


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _decimal_comma(series: pd.Series) -> tuple[pd.Series, str | None]:
    """Cast kolom desimal koma hanya bila buktinya tidak ambigu.

    Mengembalikan `(series, "decimal_comma")` saat cast diterapkan,
    `(series, "ambiguous_comma")` saat kolom memuat koma ribuan, dan
    `(series, None)` saat kolom dibiarkan apa adanya.
    """
    values = series.dropna()
    if values.empty:
        return series, None

    text = values.astype(str)
    matched = text.str.match(_DECIMAL_COMMA_RE, na=False)
    if float(matched.mean()) < _DECIMAL_COMMA_MIN:
        return series, None
    if text.str.match(_THOUSANDS_GROUP_RE, na=False).any():
        return series, "ambiguous_comma"
    if not text.str.match(_DECIMAL_COMMA_EVIDENCE_RE, na=False).any():
        return series, None

    cleaned = (
        series.astype(str)
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False)
    )
    numeric = pd.to_numeric(cleaned, errors="coerce").astype("float64")
    return numeric, "decimal_comma"


def _samples(series: pd.Series) -> list[str]:
    values = series.dropna().head(200).unique()[: _MAX_SAMPLES * 4]
    samples: list[str] = []
    for value in values:
        text = str(value)[:_MAX_SAMPLE_CHARS]
        if text not in samples:
            samples.append(text)
        if len(samples) >= _MAX_SAMPLES:
            break
    return samples


def _profile_frame(
    frame: pd.DataFrame, name: str
) -> tuple[list[dict[str, Any]], dict[str, int], int, float, list[str]]:
    rows = int(len(frame))
    warnings: list[str] = []
    columns: list[dict[str, Any]] = []
    distinct: dict[str, int] = {}

    for column in frame.columns:
        series = frame[column]
        casts: list[str] = []
        if _is_textual(series):
            converted, cast = _decimal_comma(series)
            if cast == "decimal_comma":
                frame[column] = converted
                casts.append("decimal_comma")
                warnings.append(f"kolom '{column}' dikonversi dari desimal koma")
            elif cast == "ambiguous_comma":
                casts.append("ambiguous_comma")
                warnings.append(
                    f"kolom '{column}' berisi koma ambigu (desimal vs ribuan); "
                    "tidak diubah, periksa manual"
                )

        series = frame[column]
        non_null = int(series.notna().sum())
        null_pct = _ratio(rows - non_null, rows)
        if rows and null_pct > _MISSING_WARN_PCT:
            warnings.append(f"kolom '{column}' {null_pct * 100:.0f}% kosong")
        if _is_textual(series):
            warnings.append(f"kolom '{column}' tetap object (tidak terurai)")

        distinct[column] = int(series.nunique(dropna=True))
        columns.append(
            {
                "name": column,
                "dtype": str(series.dtype),
                "non_null": non_null,
                "null_pct": round(null_pct, 4),
                "distinct": distinct[column],
                "samples": _samples(series),
                "casts": casts,
            }
        )

    duplicate_rows = int(frame.duplicated().sum()) if rows else 0
    duplicate_pct = round(_ratio(duplicate_rows, rows), 4)
    if duplicate_rows:
        warnings.append(f"file '{name}' punya {duplicate_rows} baris duplikat")

    return columns, distinct, duplicate_rows, duplicate_pct, warnings


def _candidate_keys(frame: pd.DataFrame, distinct: dict[str, int]) -> list[dict[str, Any]]:
    rows = int(len(frame))
    if rows == 0:
        return []

    keys: list[dict[str, Any]] = []
    columns = list(frame.columns)
    for column in columns:
        ratio = distinct[column] / rows
        if ratio >= _MIN_UNIQUE_RATIO:
            keys.append({"columns": [column], "unique_ratio": round(ratio, 4)})

    # Pruning: distinct pasangan tidak mungkin melebihi hasil kali distinct kolom.
    threshold = _MIN_UNIQUE_RATIO * rows
    for index, left in enumerate(columns):
        for right in columns[index + 1 :]:
            if distinct[left] * distinct[right] < threshold:
                continue
            combined = int(frame.groupby([left, right], dropna=True, observed=True).ngroups)
            ratio = combined / rows
            if ratio >= _MIN_UNIQUE_RATIO:
                keys.append(
                    {"columns": [left, right], "unique_ratio": round(ratio, 4)}
                )

    keys.sort(key=lambda key: (-key["unique_ratio"], len(key["columns"]), key["columns"]))
    return keys[:_MAX_CANDIDATE_KEYS]


# --------------------------------------------------------------------------- #
# Kandidat join antar berkas
# --------------------------------------------------------------------------- #


def _norm_name(name: str) -> str:
    return re.sub(r"[\s_]+", "", str(name).lower())


def _norm_scalar(value: Any) -> str:
    if isinstance(value, (bool, np.bool_)):
        return "true" if value else "false"
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if math.isnan(number):
            return ""
        if number.is_integer() and abs(number) < 1e15:
            return str(int(number))
        return format(number, ".15g")
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    return str(value).strip()


def _value_sets(frame: pd.DataFrame, distinct: dict[str, int]) -> dict[str, set[str]]:
    sets: dict[str, set[str]] = {}
    for column in frame.columns:
        count = distinct.get(column, 0)
        if not (_JOIN_MIN_DISTINCT <= count <= _JOIN_MAX_DISTINCT):
            continue
        values = {_norm_scalar(value) for value in frame[column].dropna().unique()}
        values.discard("")
        if values:
            sets[column] = values
    return sets


def _cardinality(left_unique: bool, right_unique: bool) -> tuple[str, str]:
    if left_unique and right_unique:
        cardinality = "one_to_one"
    elif left_unique:
        cardinality = "one_to_many"
    elif right_unique:
        cardinality = "many_to_one"
    else:
        cardinality = "many_to_many"

    if cardinality == "many_to_many":
        fanout = "high"
    elif cardinality == "one_to_many":
        fanout = "low"
    else:
        fanout = "none"
    return cardinality, fanout


def _join_candidates(
    frames: list[tuple[str, pd.DataFrame, dict[str, int]]],
) -> list[dict[str, Any]]:
    prepared = [
        (name, frame, _value_sets(frame, distinct)) for name, frame, distinct in frames
    ]
    joins: list[dict[str, Any]] = []
    for index in range(len(prepared)):
        left_name, left_frame, left_sets = prepared[index]
        for other in range(index + 1, len(prepared)):
            right_name, right_frame, right_sets = prepared[other]
            for left_column, left_values in left_sets.items():
                for right_column, right_values in right_sets.items():
                    overlap = len(left_values & right_values) / min(
                        len(left_values), len(right_values)
                    )
                    same_name = _norm_name(left_column) == _norm_name(right_column)
                    if not same_name and overlap < _JOIN_MIN_OVERLAP:
                        continue

                    left_unique = len(left_values) >= _UNIQUE_EPS * len(left_frame)
                    right_unique = len(right_values) >= _UNIQUE_EPS * len(right_frame)
                    cardinality, fanout = _cardinality(left_unique, right_unique)
                    joins.append(
                        {
                            "left": left_name,
                            "right": right_name,
                            "left_columns": [left_column],
                            "right_columns": [right_column],
                            "overlap": round(overlap, 4),
                            "left_distinct": len(left_values),
                            "right_distinct": len(right_values),
                            "cardinality": cardinality,
                            "fanout_risk": fanout,
                        }
                    )
    return joins


# --------------------------------------------------------------------------- #
# Kelompok data (komponen terhubung)
# --------------------------------------------------------------------------- #


def _datasets(
    files: list[dict[str, Any]], joins: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Kelompokkan berkas menjadi komponen terhubung lewat join yang kuat.

    Sepuluh CSV yang tidak berbagi kunci bukan satu dataset yang rusak, tetapi
    sepuluh dataset. Menggabungkannya menghasilkan join kosong dan angka nol
    yang terlihat sah. Kelompok besar diberi nomor lebih dulu supaya `D1`
    adalah kelompok yang paling layak dianalisis.
    """
    names = [str(item.get("name")) for item in files]
    parent = {name: name for name in names}

    def find(name: str) -> str:
        root = name
        while parent[root] != root:
            root = parent[root]
        while parent[name] != root:
            parent[name], name = root, parent[name]
        return root

    keys: dict[str, set[str]] = {name: set() for name in names}
    for join in joins:
        left = str(join.get("left"))
        right = str(join.get("right"))
        if left not in parent or right not in parent:
            continue
        if float(join.get("overlap") or 0.0) < _COMPONENT_MIN_OVERLAP:
            continue
        distinct = min(
            int(join.get("left_distinct") or 0), int(join.get("right_distinct") or 0)
        )
        if distinct < _COMPONENT_MIN_DISTINCT:
            continue
        left_columns = [str(column) for column in join.get("left_columns") or []]
        right_columns = [str(column) for column in join.get("right_columns") or []]
        if all(_DATE_NAME_RE.search(column) for column in left_columns + right_columns):
            continue
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root
        keys[left].update(left_columns)
        keys[right].update(right_columns)

    rows = {str(item.get("name")): int(item.get("rows") or 0) for item in files}
    order = {name: index for index, name in enumerate(names)}
    groups: dict[str, list[str]] = {}
    for name in names:
        groups.setdefault(find(name), []).append(name)

    members_list = list(groups.values())
    members_list.sort(
        key=lambda members: (
            -len(members),
            -sum(rows[name] for name in members),
            order[members[0]],
        )
    )
    return [
        {
            "id": f"D{index}",
            "files": members,
            "rows": sum(rows[name] for name in members),
            "keys": sorted(set().union(*(keys[name] for name in members))),
        }
        for index, members in enumerate(members_list, start=1)
    ]
