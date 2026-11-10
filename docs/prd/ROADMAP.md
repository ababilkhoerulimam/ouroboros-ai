# ROADMAP — agent-swarmfold

Status: draft v0.1
Rujukan: `PRD.md`

Setiap milestone punya definisi selesai yang dapat diverifikasi tanpa opini.
Tidak ada milestone yang dianggap selesai karena "kodenya sudah ditulis".

## M0 — Kerangka

**Isi:** struktur repo, `pyproject.toml`, `Dockerfile`, `compose.yaml`,
`.env.example`, kerangka FastAPI, health check.

**Selesai bila:**

- `docker compose up` menghasilkan satu container yang sehat;
- `GET /health` mengembalikan `{"status":"ok"}`;
- tidak ada kredensial di dalam image (`docker history` bersih);
- `.env` tidak masuk git.

## M1 — Ingest dan profil

**Isi:** unggah multi-file, deteksi tipe (CSV/TSV/XLSX/JSON/Parquet), hash,
profil deterministik, deteksi kandidat join, `profile.json`.

**Selesai bila:**

- lima format di atas berhasil diprofilkan pada fixture masing-masing;
- file dengan pemisah `;`, encoding non-UTF8, dan angka berkoma terbaca benar;
- dua file dengan join key yang sama menghasilkan kandidat join yang benar;
- profil dibuat tanpa memanggil API model (biaya token nol);
- dataset 100 ribu baris diprofilkan di bawah 30 detik.

## M2 — Agent loop dan kernel

**Isi:** LLM client, enam tool, kernel `jupyter_client`, penulisan cell ke
`.ipynb`, penangkapan output dan gambar, pencatatan `cells/index.json`,
controller transisi fase.

**Selesai bila:**

- satu sesi dapat menulis dan mengeksekusi minimal 10 cell berurutan dengan
  state dataframe hidup antar cell;
- cell yang error tetap tercatat, notebook tetap valid;
- gambar dari `display_data` tersimpan ke `charts/` dan tertanam di notebook;
- notebook hasil dapat dibuka di Jupyter tanpa perbaikan manual;
- tidak ada jalur eksekusi selain `run_cell` (tidak ada shell);
- satu panggilan model pada endpoint default berhasil dengan `stream: false` dan
  mengembalikan `tool_calls` yang valid;
- `reasoning_content` tersimpan terpisah dan tidak bocor ke notebook;
- latensi per panggilan tercatat di `status.json` sebagai dasar estimasi waktu run.

## M3 — Tujuh fase dan bukti

**Isi:** `prompts/system.md`, `phases/F1..F7.md`, deep-dive checkpoint, validator
`evidence`, deteksi stagnasi, `cleaning_log.json`, `data_dictionary.md`.

**Selesai bila:**

- pada 3 dataset fixture, F1 berhasil menolak 1 dataset yang memang tidak layak;
- setiap `E-###` dapat ditelusuri ke cell dan file artefak yang ada;
- validator menolak `E-###` tanpa artefak (diuji dengan data rusak sengaja);
- deep-dive terpicu tepat pada cell ke-10 dan menulis keputusan yang sah;
- tidak ada cell yang menulis ke `data/` (diuji dengan hash check).

## M4 — Laporan

**Isi:** `prompts/report.md`, renderer slot, generator PDF, aturan 3 keputusan.

**Selesai bila:**

- laporan pada 3 fixture lolos renderer tanpa slot menggantung;
- satu fixture dengan slot rusak sengaja menggagalkan penerbitan laporan
  (bukan diam-diam menghasilkan tanda "-");
- angka di laporan identik dengan `evidence.json` (dibandingkan otomatis);
- laporan ≤ 3 keputusan dan ≤ 6 chart di badan (dihitung otomatis);
- PDF dapat dibuka dan chart tampil.

## M5 — Verifikasi dan paket

**Isi:** re-run dari kernel bersih, perbandingan angka, packager zip, `done.json`.

**Selesai bila:**

- notebook yang sengaja dirusak (angka diubah manual) terdeteksi sebagai
  `unverified`;
- zip berisi seluruh deliverable wajib;
- `input/` tidak ikut dalam zip;
- run yang gagal di F3 tetap menghasilkan zip berisi status yang jujur.

## M6 — UI

**Isi:** halaman unggah, halaman progres (polling), tombol unduh.

**Selesai bila:**

- operator dapat menyelesaikan satu run penuh tanpa menyentuh terminal;
- progres menampilkan cell yang sedang berjalan dalam ≤ 3 detik setelah terjadi;
- halaman tidak menampilkan isi data klien di luar nama file dan angka agregat.

## M7 — Golden set

**Isi:** 5 dataset sintetis dengan jawaban yang diketahui (tren, segmen
bermasalah, penyebab penurunan, pelanggan hilang, data tidak layak), plus skrip
evaluasi otomatis.

**Selesai bila:**

- setiap perubahan prompt dapat diuji dan menghasilkan skor;
- skor dilaporkan per fase, bukan hanya total;
- regresi terdeteksi: penurunan skor pada satu fase menggagalkan CI lokal.

Catatan: M7 dikerjakan **sebelum** tuning prompt serius. Tanpa golden set,
setiap perubahan prompt adalah tebakan.

## M8 — Kesiapan langganan (tidak diimplementasikan di v1)

**Isi:** kredensial per run, pencatatan biaya per run, pemisahan direktori per
tenant, kuota.

**Selesai bila:** dapat dijalankan untuk dua klien berbeda tanpa kebocoran artefak
dan biaya tiap run tercatat.

## Urutan pengerjaan

```
M0 → M1 → M2 → M3 → M4 → M5 → M6 → M7 → (M8)
```

M7 boleh dimulai paralel dengan M3 (fixture-nya tidak bergantung pada UI).

## Yang sengaja ditunda

| Item | Alasan |
|---|---|
| Multi-user / login | v1 satu operator |
| Antrean paralel | satu run pada satu waktu cukup |
| Prediksi deret waktu | fase analisis, bukan pemodelan |
| Koneksi database klien | menambah permukaan keamanan besar |
| Penjadwalan otomatis | belum ada klien berulang |
| Edit laporan di UI | laporan dihasilkan, bukan diedit |
