# ARCHITECTURE — agent-swarmfold

Status: draft v0.1
Rujukan: `PRD.md`

## 1. Bentuk sistem

Satu container. Satu proses Python. Tidak ada database eksternal, tidak ada
message broker, tidak ada MLflow.

```
┌─────────────────────────── container ───────────────────────────┐
│                                                                  │
│  FastAPI (port 8080)                                             │
│   ├── UI statis (upload, progres, unduh)                          │
│   ├── POST /api/runs          → buat run, simpan file, antre      │
│   ├── GET  /api/runs/{id}     → status + daftar cell              │
│   └── GET  /api/runs/{id}/paket → unduh zip                       │
│                                                                  │
│  Job Runner (satu worker, antrean FIFO)                          │
│   └── Agent Loop                                                 │
│        ├── LLM client (API key dari env)                         │
│        ├── Tool: run_cell / read_file / list_files / write_file  │
│        └── Jupyter kernel (jupyter_client, satu per run)         │
│                                                                  │
│  Artifact Store (filesystem)                                     │
│   └── /runs/<run_id>/…                                           │
│                                                                  │
│  Report Builder                                                  │
│   ├── LLM pass kedua (prosa + slot)                              │
│   ├── Renderer deterministik (isi slot dari evidence.json)       │
│   └── PDF                                                         │
└──────────────────────────────────────────────────────────────────┘
```

Keputusan penting: **tidak ada CodeBuddy**. Agent loop ditulis sendiri, memanggil
API model secara langsung. Ini menghilangkan ketergantungan pada CLI eksternal,
tetapi memindahkan tanggung jawab eksekusi kode ke aplikasi (lihat §3 dan §4).

## 2. Komponen

| Komponen | Tanggung jawab | Batasan |
|---|---|---|
| Ingest | validasi file, hash, deteksi tipe, profil deterministik | tanpa LLM, tanpa biaya token |
| Job Runner | antrean, lifecycle run, pemulihan setelah crash | satu run aktif pada satu waktu |
| Agent Loop | percakapan dengan model, dispatch tool, pencatatan cell | maksimum 5 tool, tanpa shell |
| Kernel | eksekusi Python, tangkap stdout/error/gambar | satu kernel per run, state hidup antar cell |
| Notebook Writer | menambahkan cell + output ke `.ipynb` | format nbformat 4 |
| Evidence Store | simpan `E-###`, validasi rujukan | hanya dari output yang benar-benar ada |
| Report Builder | prosa LLM + pengisian angka deterministik | tidak boleh menghitung ulang |
| Packager | susun zip, verifikasi kelengkapan | menolak publish jika wajib kurang |

## 3. Tool yang diberikan ke model

Hanya enam. Tidak ada `bash`, tidak ada akses jaringan, tidak ada akses
filesystem bebas.

| Tool | Parameter | Kembalian |
|---|---|---|
| `run_cell` | `code: str`, `intent: str` | `stdout`, `error`, `images[]`, `duration_ms` |
| `read_file` | `path: str`, `limit?: int` | isi file (dibatasi ukuran) |
| `list_files` | `dir: str` | daftar nama + ukuran |
| `write_file` | `path: str`, `content: str` | ok / error |
| `advance_phase` | `target: str`, `reason: str` | daftar target yang sah, atau penolakan beralasan |
| `finish` | `status`, `summary` | menutup run |

Aturan:

- `run_cell` selalu menambahkan cell ke notebook, termasuk ketika error.
- `write_file` hanya diizinkan menulis di dalam `runs/<id>/` dan hanya ke
  `evidence/`, `charts/`, `notes/`. `data/` dan `derived/` ditulis lewat kode
  Python di dalam `run_cell`, bukan lewat tool ini.
- `finish` wajib dipanggil; jika model berhenti tanpa memanggilnya, runner
  menutup run dengan status `incomplete`.

### Aturan transisi fase

Model memilih fase berikutnya sendiri lewat `advance_phase`, tetapi controller
yang memutuskan sah atau tidak. Ini yang membedakan otonomi terarah dari model
yang berkeliaran.

| Dari | Target yang sah | Syarat |
|---|---|---|
| awal | F1 | selalu |
| F1 | F2 | F1 selesai dengan status ok |
| F2 | F3, F4 | F2 punya ≥ 1 `E-###` |
| F3 | F2, F4, F5 | F3 punya dekomposisi dengan residual 0 |
| F4 | F5 | F4 selesai atau menandai diri tidak berlaku |
| F5 | F3, F6 | F5 punya ≥ 1 skenario |
| F6 | F2, F3, F5, F7 | F6 sudah memeriksa seluruh `E-###` |
| F7 | — | F7 adalah fase terakhir |

Aturan tambahan:

- Kembali ke fase sebelumnya diperbolehkan (mis. F3 → F2) hanya bila disertai
  `reason`, maksimum 2 kali per fase. Lebih dari itu dianggap osilasi dan ditolak.
- `advance_phase` yang ditolak mengembalikan daftar target sah beserta alasannya;
  model wajib memilih dari daftar itu.
- F7 wajib dijalankan walau `finish` dipanggil lebih awal; controller mengubah
  status menjadi `partial` dan tetap menjalankan F7 agar laporan terbit.
- Setiap turn, konteks model memuat blok state: fase aktif, cell terpakai, jumlah
  `E-###`, dan daftar transisi yang sah. Tanpa blok ini model akan menebak.

## 4. Kernel

- `jupyter_client` dengan `KernelManager`, satu kernel per run, dijalankan di
  dalam container yang sama.
- `nbformat` untuk menulis `.ipynb`. Output cell ditulis apa adanya (stream,
  error, `display_data`), sehingga notebook dapat dibuka di Jupyter dan dijalankan
  ulang.
- Gambar ditangkap dari `display_data` (`image/png`), disimpan ke `charts/`, dan
  tetap tertanam di notebook.
- Interrupt: jika satu cell melewati batas eksekusi per cell (default 300 detik),
  kernel di-interrupt, error dikembalikan ke model sebagai kegagalan cell, bukan
  kegagalan run.

Catatan: tidak ada batas waktu total run. Yang ada adalah deteksi stagnasi
(lihat §6).

### Klien model

- HTTP langsung ke endpoint OpenAI-compatible, tanpa SDK pihak ketiga.
- Selalu mengirim `"stream": false`; gateway menjadikan streaming sebagai default
  dan akan membalas SSE bila parameter ini tidak ada.
- `timeout` request 600 detik. Latensi terukur ± 150 detik per panggilan, jadi
  timeout kecil akan menggagalkan hampir semua panggilan.
- `reasoning_content` disimpan terpisah di `cells/NNN.reasoning.txt`, tidak
  digabungkan ke jawaban dan tidak masuk notebook.
- Nama model pada respons diabaikan; yang dicatat adalah nama dari permintaan.
- Retry: maksimum 2 kali untuk error jaringan/5xx, jeda 5 dan 15 detik. Tidak ada
  retry untuk 4xx. Karena satu panggilan ± 150 detik, tiga percobaan berarti
  ± 8 menit untuk satu cell — ini harus terlihat di UI, bukan tersembunyi.

## 5. Konfigurasi

Seluruh konfigurasi lewat environment. Tidak ada nilai rahasia di dalam image.

| Variabel | Wajib | Default | Keterangan |
|---|---|---|---|
| `SWARMFOLD_API_KEY` | ya | — | kredensial model |
| `SWARMFOLD_BASE_URL` | tidak | `http://207.180.238.59:30015/v1` | endpoint OpenAI-compatible |
| `SWARMFOLD_MODEL` | tidak | `ag/gemini-3.8-flash-high` | model utama |
| `SWARMFOLD_MAX_CELLS` | tidak | 120 | pengaman biaya |
| `SWARMFOLD_CELL_TIMEOUT_S` | tidak | 300 | batas per cell |
| `SWARMFOLD_STALL_CELLS` | tidak | 3 | pemicu deep-dive paksa |
| `SWARMFOLD_DEEPDIVE_EVERY` | tidak | 10 | interval deep-dive normal |
| `SWARMFOLD_DATA_ROOT` | tidak | `/runs` | lokasi artefak |

`.env` tidak di-commit. `.env.example` berisi nama variabel tanpa nilai.

Catatan klien untuk endpoint default (lihat `PRD.md` §11): selalu kirim
`"stream": false`, jangan memvalidasi nama model dari respons, dan perlakukan
`reasoning_content` sebagai field terpisah. Latensi per panggilan ± 150 detik,
sehingga `SWARMFOLD_CELL_TIMEOUT_S` mengatur eksekusi kode, bukan panggilan model.

## 6. Ketahanan

Karena tidak boleh gagal, kegagalan didefinisikan ulang: **kegagalan adalah run
yang tidak menghasilkan paket**, bukan run yang menghasilkan paket tidak lengkap.

| Tingkat | Mekanisme |
|---|---|
| Cell | error dikembalikan ke model; model memperbaiki dan mencoba ulang (maks 3 per cell) |
| Fase | fase gagal → dicatat, analisis lanjut ke fase berikutnya bila tidak bergantung padanya |
| Run | setelah fase terakhir, tetap publish paket parsial + `status.json` yang jujur |
| Stagnasi | 3 cell berturut tanpa `E-###` baru dan tanpa output baru → paksa deep-dive; jika tetap stagnan → tutup fase |
| Crash proses | run ditandai `interrupted` saat start ulang; artefak yang ada tetap dipaketkan |
| Timeout cell | interrupt kernel, bukan kill run |

Yang **tidak** dilakukan: menelan error lalu melaporkan sukses. Setiap kegagalan
harus terlihat di `status.json` dan, bila relevan, di bagian "yang tidak bisa
dijawab" pada laporan.

## 7. Reproduksibilitas

1. Setiap file masukan di-hash (sha256) saat ingest; hash ditulis di `status.json`.
2. Sebelum setiap `run_cell`, hash `data/` diverifikasi. Berubah → run gagal keras.
3. `data/` di-mount read-only oleh container.
4. Setelah semua fase selesai, notebook dijalankan ulang dari kernel bersih di
   direktori sementara. Angka kunci (`E-###`) dibandingkan. Berbeda → run ditandai
   `unverified` dan laporan tidak boleh menyebut "terverifikasi".
5. Dependency dipin di image; versi pandas/numpy/matplotlib dicatat di
   `status.json`.

## 8. Docker

Satu service, dua volume.

```yaml
services:
  app:
    build: .
    ports: ["8080:8080"]
    env_file: .env
    volumes:
      - ./runs:/runs
      - ./inbox:/inbox:ro
```

Image berisi: Python 3.11, pandas, numpy, matplotlib, scipy, openpyxl,
pyarrow, jupyter_client, nbformat, fastapi, uvicorn, dan dependensi laporan.

Aturan kredensial:

- API key hanya dari `env_file` atau `-e`, tidak pernah `COPY`/`ARG`.
- `.dockerignore` memuat `.env`, `runs/`, `inbox/`.
- Log tidak pernah mencetak header Authorization atau isi key.

## 9. Kesiapan langganan (v2)

Disiapkan sekarang, tanpa implementasi:

- Kredensial dibaca per run dari konfigurasi run, bukan dari konstanta global.
- Pemakaian token dicatat per run (`tokens_in`, `tokens_out`, `cost_estimate`)
  sejak v1, walau belum dipakai untuk menagih.
- Artefak dipisah per run di direktori sendiri, sehingga isolasi antar tenant
  nanti hanya soal memindahkan direktori, bukan menulis ulang penyimpanan.
- Tidak ada state global yang diasumsikan satu pengguna (kecuali antrean).

## 10. Observabilitas

- `runs/<id>/status.json` diperbarui setiap perubahan state (ditulis atomik:
  tulis `.tmp` lalu rename).
- UI membaca `status.json` dan `audit/cells/index.json` lewat polling 2 detik.
- Log aplikasi: satu baris JSON per event (`run_id`, `phase`, `cell`, `event`,
  `duration_ms`). Tanpa isi data klien.
