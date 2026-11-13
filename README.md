<div align="center">
  <img src="logo.png" alt="ouroboros-ai Logo" width="180">

  <h1>ouroboros-ai</h1>
  <p><strong>Autonomous Data Analyst & Continuous Self-Evolving Benchmark Engine</strong></p>

  <p align="center">
    <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
    <img src="https://img.shields.io/badge/FastAPI-0.115+-005571?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI">
    <img src="https://img.shields.io/badge/Jupyter-Kernel-F37626?style=flat-square&logo=jupyter&logoColor=white" alt="Jupyter">
    <img src="https://img.shields.io/badge/Tests-342%20Passed-success?style=flat-square" alt="Tests">
    <img src="https://img.shields.io/badge/License-MIT-blue?style=flat-square" alt="License">
    <img src="https://img.shields.io/badge/Status-Production%20Ready-success?style=flat-square" alt="Status">
  </p>

  <p align="center">
    Aplikasi lokal otonom berbasis kontainer yang mengubah dataset bisnis mentah menjadi tiga luaran siap pakai: notebook analisis tereksekusi, laporan bisnis bebas jargon untuk pengambil keputusan, serta dataset bersih beserta kamus data dan audit bukti numerik.
  </p>
</div>

## Tech Stack

![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)
![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)
![Pandas](https://img.shields.io/badge/pandas-%23150458.svg?style=for-the-badge&logo=pandas&logoColor=white)
![NumPy](https://img.shields.io/badge/numpy-%23013243.svg?style=for-the-badge&logo=numpy&logoColor=white)
![Matplotlib](https://img.shields.io/badge/Matplotlib-%23ffffff.svg?style=for-the-badge&logo=Matplotlib&logoColor=black)
![Markdown](https://img.shields.io/badge/markdown-%23000000.svg?style=for-the-badge&logo=markdown&logoColor=white)
![Git](https://img.shields.io/badge/git-%23F05033.svg?style=for-the-badge&logo=git&logoColor=white)

## Ringkasan Proyek

ouroboros-ai dirancang untuk menyelesaikan kesenjangan kapabilitas analitik pada usaha kecil dan menengah (UMKM). Sistem ini bertindak sebagai analis data otonom yang bekerja langsung di dalam satu kernel Jupyter: menulis kode Python cell per cell, mengeksekusi, membaca keluaran numerik mentah, menalar temuan, dan melanjutkan ke cell berikutnya hingga analisis tuntas tanpa interupsi manusia.

Interaksi dirancang deterministik dengan alur dua langkah:
1. Operator mengunggah berkas data (CSV, TSV, XLSX, JSON, atau Parquet).
2. Operator mengunduh satu paket arsip ZIP lengkap yang terverifikasi secara matematis.

## Prinsip Integritas Bukti

ouroboros-ai menerapkan aturan struktural ketat untuk menjamin kebenaran analisis:

1. Angka adalah sumber kebenaran tunggal. Seluruh penalaran agen bersumber dari keluaran numerik terkonfirmasi. Grafik hanyalah artefak keluaran untuk manusia dan bukan masukan penalaran agen.
2. Tidak ada kegagalan senyap. Setiap proses selalu menghasilkan paket yang dapat diunduh, minimal berisi profil data dan laporan status transparan mengenai apa yang belum dapat dijawab.
3. Immutability data mentah. Direktori data asli dikunci sebagai read-only. Hash SHA-256 diverifikasi sebelum setiap eksekusi cell. Jika berkas mentah termutasi, proses langsung dihentikan.
4. Keterlacakan bukti E-###. Setiap angka numerik di dalam laporan diwajibkan memiliki penanda bukti yang dapat ditelusuri ke cell asal dan berkas artefak output. Pelanggaran aturan ini membatalkan publikasi laporan.
5. Satu kernel dan satu notebook. Seluruh tujuh fase analisis berjalan berurutan dalam satu kernel komputasi tanpa proses paralel yang menimbulkan fragmentasi versi kebenaran.

## Arsitektur Alur Analisis

Pipeline eksekusi dijalankan melalui tujuh fase terstruktur yang divalidasi oleh pengontrol fase:

1. Fase F1 (Data Reality). Pemeriksaan kualitas data, identifikasi grain dan kandidat primary key, pemetaan missingness, perbaikan inkonsistensi tipe (termasuk format angka desimal koma lokal), serta deteksi relasi multi-berkas. Fase ini bersifat blocking.
2. Fase F2 (What Happened). Analisis tren metrik utama per periode, dekomposisi kontribusi kategori, dan evaluasi konsentrasi penjualan Pareto.
3. Fase F3 (Why). Dekomposisi Price-Volume-Mix (PVM) atau Adtributor dengan syarat residual matematis nol, disertai audit anomali Simpson's Paradox.
4. Fase F4 (Who & When). Analisis retensi kohort pelanggan dan funnel konversi bertahap. Fase ini dilewati secara otomatis jika data tidak memuat identitas entitas pelanggan.
5. Fase F5 (What Next). Perumusan tiga skenario terukur (pesimis, dasar, optimis) berbasis variasi empiris historis tanpa rekayasa model prediktif hitam.
6. Fase F6 (Penantang). Audit kritis independen yang menyerang temuan fase sebelumnya untuk menguji kestabilan denominator, efek ukuran sampel, dan signifikansi. Klaim yang gugur diturunkan menjadi hipotesis dan dilarang masuk ke laporan akhir.
7. Fase F7 (Writer). Penyusunan draf laporan eksekutif berbahasa Indonesia berbasis slot bukti, dioptimalkan untuk keterbacaan pemilik usaha sesuai standar BLUF (Bottom Line Up Front).

Secara berkala setiap sepuluh cell, agen mengaktifkan checkpoint deep-dive untuk mengevaluasi apakah analisis perlu dilanjutkan, diperdalam, atau dipusatkan ulang.

## Luaran Analisis

Setiap proses menghasilkan satu arsip terkompresi dengan isi:

| Berkas | Deskripsi | Status |
|---|---|---|
| `analysis.ipynb` | Notebook Jupyter lengkap dengan seluruh keluaran numerik dan visualisasi tertanam | Wajib |
| `laporan.md` | Laporan eksekutif berbahasa Indonesia dengan batas maksimal tiga keputusan bisnis | Wajib |
| `laporan.docx` | Salinan laporan dalam format dokumen Microsoft Word | Wajib |
| `laporan.pdf` | Salinan laporan cetak siap baca dalam format PDF | Wajib |
| `data_bersih.csv` | Dataset hasil pembersihan kanonik | Wajib |
| `data_dictionary.md` | Kamus data terstruktur yang mendokumentasikan kolom, tipe, satuan, dan asal transformasi | Wajib |
| `cleaning_log.json` | Log audit seluruh transformasi baris dan kolom yang terjadi | Wajib |
| `audit/` | Jejak bukti audit mencakup status, profil deterministik, dan keluaran cell mentah | Wajib |
| `charts/` | Gambar visualisasi beresolusi tinggi yang tertanam pada laporan | Wajib |

## Mesin Evaluasi Mandiri

ouroboros-ai dilengkapi framework verifikasi ground-truth dan loop evolusi otomatis:

- Verifier Terkunci (`swarmfold_verify`). Mengukur performa agen terhadap kasus benchmark ber-ground-truth (kasus tren, Simpson's paradox, heavy-tail, anomali join, missingness, dan gap data). Skor recall, Brier calibration, dan defect rate dihitung tanpa ketergantungan pada model juri. Kode verifier dipin menggunakan hash kriptografis `verify.lock.json`.
- Orkestrator Evolusi (`swarmfold_eval`). Model reviewer menganalisis kegagalan dan mengusulkan patch perbaikan. Lapisan keamanan `patcher.py` membatasi cakupan patch hanya pada direktori prompt dan logika runtime, serta menolak modifikasi pada alat ukur maupun konfigurasi repositori. Promosi patch dicatat dalam buku besar append-only berbasis hash chain.

## Panduan Memulai

### Menjalankan dengan Docker

Sistem dapat dijalankan langsung menggunakan Docker Compose:

```bash
docker compose build
docker compose up -d
```

Aplikasi web dapat diakses melalui peramban di alamat `http://127.0.0.1:8080`.

### Menjalankan di Lingkungan Lokal

Prasyarat lingkungan adalah Python versi 3.11 atau lebih baru.

1. Pasang dependensi proyek:

```bash
pip install -e ".[dev]"
```

2. Konfigurasikan variabel lingkungan pada berkas `.env`:

```env
SWARMFOLD_API_KEY=kunci_api_anda
SWARMFOLD_BASE_URL=http://endpoint-model:port/v1
SWARMFOLD_MODEL=ag/gemini-3.8-flash-high
```

3. Jalankan server aplikasi:

```bash
uvicorn swarmfold.api:app --host 127.0.0.1 --port 8080
```

### Menjalankan Pengujian

Repositori diverifikasi secara ketat melalui test suite otomatis:

```bash
pytest
```

## Dokumentasi

Panduan operasional dan arsitektur pengaman loop evolusi mandiri:
- [docs/EVOLUSI.md](docs/EVOLUSI.md): Panduan menjalankan loop evaluasi mandiri, verifier pinning, dan aturan pembatasan branch.

## Lisensi

Proyek ini didistribusikan di bawah lisensi MIT. Informasi lengkap dapat dilihat pada berkas [LICENSE](LICENSE).
