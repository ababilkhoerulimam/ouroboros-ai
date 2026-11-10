# PRD — agent-swarmfold

Status: draft v0.1
Tanggal: 2026-11-10
Pemilik: operator tunggal (pengguna repo ini)

## 1. Ringkasan

Aplikasi lokal berbentuk satu container. Pengguna mengunggah file data penjualan
(CSV, XLSX, TSV, JSON, Parquet — satu atau banyak file sekaligus), lalu agent
otonom menganalisis data tersebut persis seperti cara seorang analis bekerja:
menulis satu cell kode, mengeksekusinya, membaca output angka, mengevaluasi, lalu
menulis cell berikutnya, sampai analisis selesai.

Hasil akhir yang dapat diunduh dalam satu paket:

1. `analysis.ipynb` — notebook yang sudah dieksekusi, seluruh output dan chart tertanam.
2. `laporan.md` + `laporan.pdf` — laporan 2 halaman berbahasa Indonesia untuk pemilik usaha.
3. `data_bersih.csv` + `data_dictionary.md` + `cleaning_log.json` — data siap pakai.
4. `audit/` — jejak bukti: setiap angka di laporan dapat ditelusuri ke cell asalnya.

Tidak ada gate, tidak ada konfirmasi di tengah jalan. Interaksi pengguna hanya dua:
unggah, lalu unduh.

## 2. Masalah

Usaha kecil menengah memiliki data penjualan tetapi tidak memiliki kemampuan
maupun anggaran untuk analisis data. Analisis yang mereka butuhkan sebenarnya
tidak rumit: tren, segmen yang bermasalah, penyebab penurunan, pelanggan yang
hilang, dan langkah berikutnya. Namun hasilnya harus dalam bahasa yang dapat
dipahami tanpa latar belakang statistik, dan harus dapat dipercaya.

Masalah kedua ada pada sisi operator: pekerjaan analisis yang sama diulang dari
nol untuk setiap klien. Waktu habis pada hal yang berulang, bukan pada penilaian.

## 3. Pengguna

| Peran | Siapa | Yang dilakukan |
|---|---|---|
| Operator | pemilik repo ini | menjalankan container, mengunggah data klien, mengunduh paket hasil, menyerahkan ke klien |
| Konsumen akhir | pemilik usaha kecil | membaca laporan; tidak pernah menyentuh aplikasi |

Konsekuensi: antarmuka dioptimalkan untuk kecepatan operator, sedangkan laporan
dioptimalkan untuk pemahaman konsumen akhir. Keduanya adalah audiens berbeda dan
tidak boleh dicampur dalam satu dokumen.

## 4. Model bisnis

- **v1 (sekarang):** lokal, satu operator, dijalankan lewat Docker di laptop.
- **v2 (nanti):** langganan bulanan. Operator menyediakan API key dan kuota.
  Persyaratan teknis untuk v2 (pemisahan kredensial, pencatatan pemakaian per run,
  isolasi per run) sudah disiapkan sejak v1 agar tidak perlu ditulis ulang.

## 5. Prinsip desain

Prinsip di bawah ini mengikat. Jika sebuah implementasi melanggar salah satunya,
implementasi itu yang salah, bukan prinsipnya.

1. **Angka adalah sumber kebenaran.** Seluruh penalaran agent bersumber dari output
   numerik yang tercetak. Chart tidak pernah menjadi masukan penalaran — chart
   adalah artefak keluaran untuk pembaca manusia.
2. **Tidak ada kegagalan senyap.** Setiap run selalu menghasilkan paket yang dapat
   diunduh, minimal berisi profil data dan laporan status yang menyatakan apa yang
   gagal dan mengapa. Paket kosong tidak diperbolehkan.
3. **Data mentah tidak pernah ditulis.** Direktori `data/` bersifat read-only dan
   hash-nya diverifikasi sebelum setiap cell dieksekusi.
4. **Setiap angka di laporan punya bukti.** Angka yang tidak memiliki `E-###` tidak
   boleh muncul di laporan. Pelanggaran ini menggagalkan penerbitan laporan.
5. **Dua audiens, dua dokumen.** Laporan untuk pemilik usaha; jejak bukti untuk
   operator. Laporan tidak memuat istilah statistik di badan utama.
6. **Satu notebook, tujuh fase.** Analisis berjalan dalam satu kernel dan satu
   notebook yang berurutan, bukan beberapa proses paralel.
7. **Otonom penuh.** Tidak ada titik konfirmasi manusia di tengah eksekusi.
   Pengaman bersifat struktural, bukan bergantung pada kewaspadaan operator.
8. **Kode sekali, eksekusi berulang.** Agent menulis pipeline; pipeline yang
   dijalankan ulang harus menghasilkan angka yang sama.

## 6. Alur pengguna

```
1. Operator membuka http://localhost:8080
2. Unggah satu atau beberapa file (drag & drop)
3. Isi brief singkat: keputusan apa yang ingin diambil, KPI utama, periode
   (opsional — jika kosong, agent menyimpulkan dari data dan mencatat asumsinya)
4. Klik "Analisis"
5. Halaman progres menampilkan cell yang sedang berjalan (hanya-baca)
6. Setelah selesai, tombol "Unduh paket" aktif
7. Operator mengunduh satu file zip
```

Tidak ada langkah lain. Tidak ada approval, tidak ada interupsi.

## 7. Cakupan v1

### Termasuk

- Ingest multi-file: CSV, TSV, XLSX, JSON, Parquet.
- Deteksi otomatis hubungan antar file (kandidat join key) dan penggabungan.
- Profiling deterministik sebelum LLM dipanggil (tanpa biaya token).
- Tujuh fase analisis otonom (lihat `LANES.md`).
- Deep-dive checkpoint setiap 10 cell.
- Notebook tereksekusi + chart tertanam.
- Laporan 2 halaman dengan pengisian angka deterministik.
- Data bersih + kamus data + log pembersihan.
- Antrean job sederhana (satu run aktif pada satu waktu).
- Docker compose satu service.

### Tidak termasuk (v1)

- Multi-user, login, hak akses.
- Antrean terdistribusi / beberapa worker paralel.
- Prediksi deret waktu produksi atau pemodelan ML.
- Koneksi langsung ke database klien atau API marketplace.
- Penjadwalan otomatis (analisis berulang tiap minggu).
- Pengiriman laporan via email/WhatsApp.
- Edit laporan secara manual di dalam aplikasi.

## 8. Deliverable

Satu file `paket-<run_id>.zip`:

| Path | Isi | Wajib |
|---|---|---|
| `analysis.ipynb` | notebook tereksekusi, output + chart tertanam | ya |
| `laporan.md` | laporan 2 halaman, bahasa Indonesia | ya |
| `laporan.pdf` | versi cetak dari laporan | ya |
| `data_bersih.csv` | data hasil pembersihan | ya |
| `data_dictionary.md` | arti kolom, satuan, asal | ya |
| `cleaning_log.json` | setiap transformasi: kolom, baris terpengaruh, alasan | ya |
| `audit/evidence.json` | seluruh `E-###` beserta cell dan artefaknya | ya |
| `audit/cells/` | kode dan output tiap cell | ya |
| `audit/status.json` | status akhir, fase yang selesai, yang terlewat | ya |
| `charts/` | PNG resolusi tinggi tiap chart | ya |

## 9. Metrik keberhasilan

| Metrik | Target |
|---|---|
| Run yang menghasilkan paket lengkap | ≥ 90% dari run yang dimulai |
| Laporan dapat dibaca pemilik usaha tanpa penjelasan tambahan | ≥ 8/10 pada uji 5 pembaca |
| Angka di laporan cocok dengan notebook | 100% (dijamin secara struktural) |
| Notebook dapat dijalankan ulang dari kernel bersih | 100% |
| Waktu run pada dataset 5.000 baris | tanpa batas keras; perkiraan realistis 45–90 menit pada model default (lihat §10) |
| Biaya token per run | dicatat, belum dibatasi di v1 |

## 10. Risiko

| Risiko | Dampak | Mitigasi |
|---|---|---|
| Agent berputar tanpa kemajuan | biaya membengkak | deteksi stagnasi: 3 cell berturut tanpa bukti baru memicu deep-dive paksa |
| Data klien terlalu berantakan | analisis menyesatkan | F1 bersifat blocking; hasil sah berupa laporan "data belum siap" |
| Angka laporan menyimpang | kepercayaan hilang | slot `{{E-###}}` diisi kode, bukan oleh LLM |
| Notebook error di tengah | paket tidak dapat dipakai | re-run dari kernel bersih sebelum publikasi; gagal → tandai, jangan kirim sebagai sukses |
| API key bocor | biaya & reputasi | key hanya lewat env, tidak pernah masuk image atau log |
| Data klien sensitif | pelanggaran privasi | mode lokal; sinkronisasi eksternal dimatikan keras |
| Latensi model ± 150 detik per panggilan | run 25 cell menjadi ± 60 menit; operator menunggu lama, antrean menumpuk | benchmark model alternatif di endpoint yang sama; tampilkan progres per cell agar tidak terasa hang; pertimbangkan model cepat untuk cell rutin dan model kuat hanya untuk F3/F6 |
| Endpoint tanpa TLS | token dan data klien transit terbuka | hanya untuk lingkungan lokal; wajib TLS/tunnel sebelum v2 |

## 11. Provider model

Endpoint: `http://207.180.238.59:30015/v1` — OpenAI-compatible.
Autentikasi: bearer token dari environment (`SWARMFOLD_API_KEY`), tidak pernah
masuk image, log, atau artefak run.

Model default: **`ag/gemini-3.8-flash-high`**.

Model yang tersedia pada endpoint ini (diverifikasi 2026-11-10):

| Model | tools | vision | context | max output |
|---|---|---|---|---|
| `ag/gemini-3.8-flash-high` | ya | ya | 1.048.576 | 65.536 |
| `ag/claude-sonnet-4-6` | ya | ya | 1.000.000 | 128.000 |
| `ag/claude-opus-4-6-thinking` | ya | ya | 200.000 | 64.000 |
| `mmf/mimo-auto` | ya | ya | 262.144 | 131.072 |
| `oc/jev-1.13-free` | ya | tidak | 200.000 | 64.000 |

### Perilaku gateway yang harus ditangani klien

Diukur langsung pada endpoint ini, bukan asumsi dari dokumentasi:

| Perilaku | Konsekuensi |
|---|---|
| Streaming adalah default; tanpa `"stream": false` respons keluar sebagai SSE | klien wajib mengirim `stream: false` untuk mendapat JSON utuh |
| `model` pada respons tidak sama dengan yang diminta (`ag/gemini-3.8-flash-high` → `gemini-3.8-flash-n`) | jangan memvalidasi nama model dari respons; percayai permintaan |
| Field `reasoning_content` muncul di luar `content` | jangan menggabungkannya ke jawaban; simpan terpisah untuk audit |
| Overhead prompt ± 2.000 token untuk prompt sependek satu kalimat | perhitungkan dalam estimasi biaya; jangan asumsikan prompt kecil = murah |
| Latensi terukur ± 140–160 detik per panggilan, termasuk prompt trivial | lihat risiko di §10 |

Tool calling berfungsi: permintaan `ping` mengembalikan `finish_reason: tool_calls`
dengan argumen `{"value": 7}`.

### Catatan keamanan

Endpoint memakai **HTTP tanpa TLS** ke alamat IP publik. Konsekuensi: bearer token
dan isi data klien transit dalam teks biasa. Untuk v1 (lokal, operator tunggal)
ini diterima sebagai keterbatasan lingkungan, tetapi **tidak boleh** dipakai untuk
v2 (langganan) sebelum ada TLS atau tunnel. Key yang dipakai saat pengujian
sebaiknya dirotasi karena sempat tertulis di transkrip.

## 12. Pertanyaan terbuka

1. Benchmark latensi antar model: apakah `oc/jev-1.13-free` atau
   `mmf/mimo-auto` cukup lebih cepat untuk menurunkan waktu run secara material.
2. Batas biaya per run untuk v1 (belum dibatasi, tetapi perlu dicatat).
3. Format PDF: dibuat dari markdown (mis. via typst/weasyprint) atau langsung.
4. Apakah laporan perlu logo/nama usaha klien pada v1.
5. Apakah endpoint akan diberi TLS sebelum v2.

## 13. Dokumen terkait

- `ARCHITECTURE.md` — runtime, tool, kernel, Docker, kredensial.
- `LANES.md` — tujuh fase, deep-dive, aturan bukti.
- `CONTRACTS.md` — skema `cell`, `evidence`, `done`, slot laporan.
- `ROADMAP.md` — urutan pengerjaan dan definisi selesai per milestone.
