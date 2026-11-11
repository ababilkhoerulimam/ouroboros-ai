# CONTRACTS — skema dan tata letak

Status: draft v0.1
Rujukan: `PRD.md`, `ARCHITECTURE.md`, `LANES.md`

Semua berkas ditulis atomik (`.tmp` lalu `rename`). Semua JSON memakai UTF-8 dan
kunci bahasa Inggris; isi teks boleh bahasa Indonesia.

## 1. Tata letak run

```
runs/<run_id>/
  input/                     file asli yang diunggah (read-only setelah ingest)
  data/                      salinan kerja, read-only, di-hash
  profile.json               profil deterministik (tanpa LLM)
  derived/
    01_clean.csv             data bersih (deliverable)
  cells/
    index.json               daftar cell: id, fase, intent, durasi, status
    001.py / 001.out.txt     kode dan output mentah
  charts/
    F2_03_tren_bulanan.png
  evidence/
    F1.json … F6.json
    deepdive/01.json
  notes/
    cleaning_log.json
    data_dictionary.md
  analysis.ipynb             notebook tereksekusi
  laporan.md
  laporan.pdf
  status.json
  done.json                  sentinel
```

### `profile.json`

Dibuat `ingest` tanpa model, lalu `triage` menambahkan satu kunci.

```json
{
  "generated_at": "2026-11-10T10:00:00Z",
  "files": [
    {"name": "penjualan.csv", "format": "csv", "rows": 12, "cols": 5,
     "sha256": "…", "bytes": 512, "columns": [{"name": "total", "dtype": "int64"}],
     "candidate_keys": [{"columns": ["tanggal"], "unique_ratio": 1.0}]}
  ],
  "joins": [
    {"left": "pesanan.csv", "right": "pelanggan.csv",
     "left_columns": ["customer_id"], "right_columns": ["id"],
     "overlap": 1.0, "left_distinct": 50, "right_distinct": 93,
     "cardinality": "many_to_one", "fanout_risk": "none"}
  ],
  "datasets": [
    {"id": "D1", "files": ["pesanan.csv", "pelanggan.csv"], "rows": 193,
     "keys": ["customer_id", "id"]}
  ],
  "triage": {"mode": "full", "reasons": ["…"], "missing": []},
  "warnings": ["…"]
}
```

Aturan:

- `joins` adalah **kandidat**, termasuk pasangan yang hanya kebetulan punya nama
  kolom sama; `overlap` adalah bagian nilai kiri yang juga ada di kanan.
- `datasets` adalah komponen terhubung dari kandidat yang kuat (`overlap ≥ 0,80`,
  minimal 3 nilai berbeda, dan bukan pasangan kolom bertanggal semata). Berkas
  tanpa kunci bersama menjadi dataset sendiri, bukan dibuang.
- Berkas hanya boleh di-join di dalam satu `datasets`; join lintas dataset
  menghasilkan tabel kosong atau fan-out.
- `datasets` diurutkan: kelompok dengan berkas terbanyak lebih dulu, sehingga
  `D1` adalah kelompok terbesar.
- `triage.mode` ∈ `full | cleaning_only | insufficient`; `insufficient`
  menghentikan run sebelum kernel dijalankan.

## 2. `status.json`

Diperbarui setiap transisi state.

```json
{
  "run_id": "2026-11-10-a1b2c3",
  "state": "queued|running|verifying|packaging|done|failed",
  "phase": "F3",
  "cell": 27,
  "started_at": "2026-11-10T10:00:00Z",
  "updated_at": "2026-11-10T10:12:41Z",
  "inputs": [{"name": "penjualan.xlsx", "sha256": "…", "bytes": 48211}],
  "dataset_hash": "sha256:…",
  "env": {"pandas": "2.2.2", "numpy": "1.26.4", "python": "3.11.9"},
  "model": {"requested": "ag/gemini-3.8-flash-high", "returned": "gemini-3.8-flash-n"},
  "usage": {"tokens_in": 0, "tokens_out": 0, "cost_estimate": 0.0},
  "counts": {"cells": 27, "evidence": 14, "charts": 5},
  "warnings": ["kolom 'diskon' 62% kosong"]
}
```

Aturan:

- `state` hanya boleh bergerak maju, kecuali ke `failed`.
- `phase` dan `cell` adalah posisi saat ini, bukan hasil akhir.
- `dataset_hash` adalah sha256 dari peta `{nama berkas di data/: sha256}`, dibekukan saat run mulai. `dataset_hash` pada finding harus sama persis dengan nilai ini, sehingga run multi-berkas tidak bisa memakai hash salah satu berkas saja.
- `warnings` tidak pernah dikosongkan; peringatan bersifat akumulatif.

## 3. `cells/index.json`

```json
{
  "cells": [
    {
      "n": 1,
      "phase": "F1",
      "intent": "profil awal dan deteksi tipe kolom",
      "status": "ok|error|timeout",
      "duration_ms": 812,
      "evidence": [],
      "charts": []
    }
  ]
}
```

`intent` wajib satu baris, maksimal 120 karakter, ditulis sebelum eksekusi.
Cell dengan `status != "ok"` tetap dicatat dan tetap masuk notebook.

## 4. `evidence/F{n}.json`

```json
{
  "phase": "F3",
  "question": "kenapa pendapatan turun di kuartal ketiga",
  "findings": [
    {
      "id": "E-004",
      "pillar": "fact",
      "statement": "pendapatan turun 12,4% dibanding kuartal sebelumnya",
      "value": -0.124,
      "unit": "ratio",
      "display": "-12,4%",
      "cell": 19,
      "artifact": "cells/019.out.txt",
      "chart": "charts/F3_02_dekomposisi.png",
      "dataset_hash": "sha256:…",
      "confidence": "high|medium|low",
      "verified": true
    }
  ],
  "hypotheses": [
    {"id": "H-002", "statement": "penurunan disebabkan kenaikan harga", "status": "unresolved|supported|rejected"}
  ],
  "anomalies": [
    {"id": "AN-001", "statement": "transaksi negatif 37 baris", "handled": true}
  ],
  "cannot_answer": ["margin per produk: tidak ada kolom biaya"]
}
```

Aturan validasi (menolak publish jika dilanggar):

| Field | Aturan |
|---|---|
| `id` | unik dalam satu run, format `E-###` / `H-###` / `AN-###` |
| `value` | angka, bukan string |
| `cell` | harus ada di `cells/index.json` dengan `status == "ok"` |
| `artifact` | file harus ada dan memuat `display` (atau nilai numerik setara) |
| `dataset_hash` | harus sama dengan hash di `status.json` |
| `verified` | hanya `true` jika F6 tidak menggugurkannya |
| `chart` | opsional; jika ada, file harus ada |

`findings` dengan `verified: false` tidak boleh dirujuk laporan, tetapi tetap
disimpan untuk audit.

## 5. `notes/cleaning_log.json`

Satu entri per transformasi yang mengubah jumlah baris atau kolom.

```json
{
  "operations": [
    {
      "seq": 1,
      "type": "drop_duplicates|drop_column|filter_rows|cast_type|fill_missing|rename|join|derive",
      "target": "invoice_id",
      "rows_before": 5412,
      "rows_after": 5398,
      "cols_before": 11,
      "cols_after": 11,
      "reason": "duplikat persis pada invoice_id",
      "cell": 4,
      "reversible": true
    }
  ]
}
```

Aturan: setiap operasi wajib punya `reason`. Operasi tanpa `reason` menggagalkan
publish. Operasi dengan `reversible: false` (mis. drop kolom) wajib muncul di
`warnings` laporan.

## 6. `notes/data_dictionary.md`

Satu tabel, satu baris per kolom pada `derived/01_clean.csv`:

| kolom | tipe | satuan | asal | catatan |
|---|---|---|---|---|
| `tanggal` | date | — | `penjualan.xlsx:Tanggal` | format asal campur, dinormalisasi |
| `total` | float | IDR | `penjualan.xlsx:Total` | sudah bersih dari "Rp" dan titik ribuan |

Kolom yang dibuang tidak dihapus dari kamus; diberi status `dibuang` beserta alasan.

## 7. `done.json`

Ditulis sebagai aksi terakhir.

```json
{
  "status": "ok|partial|blocked|failed",
  "phases_completed": ["F1", "F2", "F3"],
  "phases_skipped": [{"phase": "F4", "reason": "tidak ada identifier pelanggan"}],
  "deliverables": {
    "notebook": "analysis.ipynb",
    "report_md": "laporan.md",
    "report_pdf": "laporan.pdf",
    "clean_data": "derived/01_clean.csv"
  },
  "verification": {"rerun": "pass|fail|skipped", "mismatches": []},
  "summary": "tiga keputusan, satu peringatan data"
}
```

`status: failed` tetap menghasilkan paket, berisi `status.json`, `profile.json`,
dan `laporan.md` versi "data belum siap" atau "analisis terhenti".

## 8. Slot laporan

Laporan ditulis sebagai markdown dengan slot. Renderer mengganti slot dengan
nilai dari `evidence/*.json`.

```
Pendapatan turun {{E-004}} dibanding kuartal sebelumnya, terutama dari
{{E-006}}.
```

Aturan renderer:

| Slot | Diganti dengan | Gagal jika |
|---|---|---|
| `{{E-###}}` | `display` dari finding | id tidak ada, `verified: false`, atau fase tidak selesai |
| `{{E-###.chart}}` | path gambar relatif | finding tidak punya `chart` |
| `{{E-###.value}}` | angka mentah + satuan | `unit` kosong |

Jika satu slot gagal, **seluruh laporan gagal terbit**. Tidak ada penggantian
diam-diam dengan tanda "-" atau teks lain. Kegagalan ini tercatat di `done.json`.

Larangan pada tahap penulisan laporan:

- mengetik angka secara literal di luar slot;
- menambah klaim yang tidak punya `E-###`;
- memakai istilah statistik di badan utama (bootstrap, p-value, regresi);
- melebihi 3 keputusan, atau melanggar `REPORT-STANDARD.md` §7.

## 9. Paket unduhan

`paket-<run_id>.zip` berisi seluruh direktori run kecuali `input/` (file asli
klien tidak ikut, agar paket tidak membocorkan data mentah ke pihak ketiga).
Packager menolak membuat zip jika salah satu deliverable wajib tidak ada, kecuali
`done.json` berstatus `failed` — dalam kasus itu zip tetap dibuat dengan isi
minimal dan `status.json` sebagai penjelas.
