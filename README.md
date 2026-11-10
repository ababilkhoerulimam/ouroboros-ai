# agent-swarmfold

Aplikasi lokal yang mengubah file data penjualan menjadi tiga hal sekaligus:
notebook analisis yang sudah dieksekusi, laporan dua halaman untuk pemilik usaha,
dan data bersih beserta kamusnya.

Agent berjalan otonom: menulis satu cell, mengeksekusinya, membaca output angka,
lalu melanjutkan ke cell berikutnya sampai analisis selesai. Tidak ada konfirmasi
di tengah jalan. Pengguna hanya mengunggah, lalu mengunduh paket hasil.

Ditujukan untuk usaha kecil yang membutuhkan analisis data tetapi tidak memiliki
kemampuan maupun anggaran untuk itu.

## Status

Tahap desain. Belum ada implementasi. Dokumen produk menjadi acuan sebelum kode
pertama ditulis.

## Dokumentasi

| Dokumen | Isi |
|---|---|
| [docs/prd/PRD.md](docs/prd/PRD.md) | masalah, pengguna, cakupan, prinsip, metrik, risiko |
| [docs/prd/ARCHITECTURE.md](docs/prd/ARCHITECTURE.md) | komponen, tool, kernel, Docker, kredensial, ketahanan |
| [docs/prd/LANES.md](docs/prd/LANES.md) | tujuh fase analisis, deep-dive, aturan bukti, chart |
| [docs/prd/CONTRACTS.md](docs/prd/CONTRACTS.md) | skema `cell`, `evidence`, `done`, slot laporan, tata letak run |
| [docs/prd/ROADMAP.md](docs/prd/ROADMAP.md) | milestone dan definisi selesai |

## Prinsip inti

1. Angka adalah sumber kebenaran; chart adalah keluaran, bukan masukan penalaran.
2. Tidak ada kegagalan senyap: setiap run menghasilkan paket yang dapat diunduh.
3. Data mentah tidak pernah ditulis; hash diverifikasi sebelum setiap cell.
4. Setiap angka di laporan memiliki `E-###` yang dapat ditelusuri ke cell asalnya.
5. Satu notebook, tujuh fase, satu versi kebenaran.

## Lisensi

MIT. Lihat [LICENSE](LICENSE).
