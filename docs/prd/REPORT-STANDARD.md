# REPORT-STANDARD — standar laporan

Status: draft v0.1
Rujukan: `LANES.md` F7, `PRD.md` §8, `PROMPT-MAP.md`

Dokumen ini menetapkan bagaimana laporan ditulis. Sumbernya dua: skill
`notebook-paper` (yang sudah terbukti menghasilkan naskah rapi) dan riset tentang
keterbacaan untuk pembaca non-teknis.

Tidak ada batas halaman. Yang membatasi adalah jumlah keputusan dan disiplin
berhenti saat pertanyaan terjawab.

## 1. Apa yang diambil dari `notebook-paper`

| Bagian sumber | Tindakan | Alasan |
|---|---|---|
| Larangan em-dash (`—`) | **salin** | tidak lazim di bahasa Indonesia formal, penanda tulisan mesin |
| Kamus hitam kata AI (menyelami, krusial, rajutan, saksi bisu, mulus) | **salin** | |
| Larangan rule-of-three dan negative parallelism | **salin** | |
| Larangan pembuka basa-basi ("Penting untuk dicatat bahwa...") | **salin** | |
| Angka exact dicetak tebal | **salin** | |
| Zero orphan figures (setiap gambar dirujuk di paragraf) | **salin** | |
| Caption yang menyatakan temuan, bukan "Gambar 1" | **salin** | |
| Format DOCX/PDF (font, tabel, caption) | **adaptasi** | gaya akademik diganti gaya dokumen bisnis |
| 4 Pilar Rekomendasi | **adaptasi** | pilar aktuaria diganti 3 keputusan bisnis |
| Sitasi jurnal dan grounding literatur | **buang** | pemilik UMKM tidak butuh daftar pustaka; bukti ada di lampiran |
| Struktur 4 bab akademik (Pendahuluan/Metodologi/Hasil/Penutup) | **buang** | terlalu formal untuk pembaca yang tidak membaca laporan |
| "Setiap visualisasi wajib 2–3 paragraf substantif" | **buang** | untuk UMKM ini justru pemborosan; lihat §6 |
| Rumus OMML / LaTeX | **buang** | tidak ada rumus di laporan bisnis |

## 2. Temuan riset yang mengubah desain

| Temuan | Sumber | Konsekuensi untuk laporan |
|---|---|---|
| Plain language berarti pembaca dapat **menemukan, memahami, dan menggunakan** informasi pada bacaan pertama | ISO 24495-1:2023 | struktur harus bisa dipakai, bukan hanya dibaca; ada bagian "apa yang harus dilakukan" |
| Pembaca memindai, tidak membaca. Jika inti tidak tertangkap dalam 30 detik, laporan gagal | praktik penulisan laporan bisnis (BLUF) | kesimpulan di halaman pertama, bukan di akhir |
| Frekuensi alami (jumlah kasus) lebih dipahami daripada persentase sendirian; pada eksperimen klasik, penalaran benar naik dari 16% (probabilitas) ke 46% (frekuensi) | Gigerenzer & Hoffrage, 1995 | setiap persentase wajib disertai angka aslinya |
| UMKM menghadapi kendala sumber daya dan pengetahuan dalam menyusun serta memahami laporan keuangan | studi pelatihan laporan keuangan UMKM (jurnal pengabdian, 2023) | istilah teknis harus diterjemahkan, bukan dijelaskan sekali lalu dipakai terus |
| Caption yang menyatakan kesimpulan lebih membantu daripada label netral | praktik penulisan laporan bisnis | judul chart adalah temuan, bukan nama variabel |

Catatan kejujuran: ISO dan Gigerenzer adalah sumber kuat. BLUF/SPARK dan aturan
caption adalah praktik profesional, bukan hasil eksperimen terkontrol. Jangan
menyitirnya sebagai bukti ilmiah.

## 3. Struktur

Urutan ini mengikat. Bagian boleh kosong jika datanya tidak mendukung, tetapi
tidak boleh dihilangkan tanpa alasan yang ditulis.

| # | Bagian | Isi | Batas |
|---|---|---|---|
| 1 | **Ringkasan** | maksimum 3 keputusan; tiap keputusan: temuan, angka, dampak, aksi | 1 halaman |
| 2 | **Apa yang diperiksa** | file, periode, jumlah baris, kolom yang dipakai, kolom yang dibuang | 1 paragraf + 1 tabel kecil |
| 3 | **Apa yang terjadi** | tren dan segmen | maks 3 chart |
| 4 | **Kenapa** | dekomposisi volume/mix/rate, residual nol | maks 2 chart |
| 5 | **Siapa dan kapan** | cohort, funnel, drop-off | maks 1 chart |
| 6 | **Kalau dibiarkan** | 3 skenario dengan asumsi tertulis | 1 tabel |
| 7 | **Yang perlu dilakukan** | 3 aksi: apa, siapa, kapan, diukur dengan apa | 1 halaman |
| 8 | **Yang tidak bisa dijawab** | daftar bullet, jujur | maks 5 bullet |
| 9 | **Lampiran** | kamus kolom, log pembersihan, tabel bukti `E-###`, metode | tanpa batas |

Aturan tambahan:

- Bagian 1 harus bisa dibaca sendirian. Jika halaman itu dipotong dan dikirim ke
  pemilik usaha, dia tetap tahu harus apa.
- Bagian 7 tidak boleh memuat aksi yang tidak muncul di bagian 1.
- Lampiran tidak dihitung dalam penilaian "terlalu panjang".

## 4. Bahasa

| Aturan | Contoh salah | Contoh benar |
|---|---|---|
| Kalimat maksimal 20 kata | "Berdasarkan hasil dekomposisi yang telah dilakukan terhadap komponen volume dan harga, dapat disimpulkan bahwa..." | "Penjualan turun karena jumlah transaksi berkurang, bukan karena harga." |
| Satu paragraf maksimal 4 baris | paragraf 10 baris | 3 kalimat |
| Istilah teknis wajib diterjemahkan saat dipakai | "terjadi penurunan pada komponen mix" | "pelanggan beralih ke produk yang lebih murah" |
| Tanpa istilah statistik di badan utama | "signifikan secara statistik (p = 0,003)" | "perbedaannya cukup besar untuk dipercaya, bukan kebetulan" |
| Tanpa em-dash | "turun — meski iklan naik" | "turun, meski iklan naik" |
| Tanpa kata terlarang | menyelami, krusial, rajutan, saksi bisu, mulus, komprehensif | menganalisis, mengukur, menentukan, menunjukkan |
| Tanpa rule-of-three | "cepat, akurat, dan andal" | "selisih 12,4% dari Rp 412 juta" |
| Tanpa pembuka basa-basi | "Penting untuk dicatat bahwa penjualan turun" | "Penjualan turun 12,4%." |

Nada: netral dan spesifik. Tidak menyalahkan orang ("tim penjualan gagal"
diganti "target tidak tercapai 20%"). Tidak melebih-lebihkan ("sangat penting"
diganti dengan angka).

## 5. Angka

Ini aturan yang paling sering dilanggar dan paling merusak kepercayaan.

1. **Setiap persentase disertai angka aslinya.** Bukan "turun 12%", tetapi
   "turun 12% (dari Rp 412 juta menjadi Rp 362 juta)".
2. **Setiap angka di badan laporan adalah slot `{{E-###}}`.** Model tidak mengetik
   angka; renderer yang mengisi dari `evidence.json`.
3. **Pembulatan untuk manusia, ketelitian untuk lampiran.** Badan laporan: dua
   angka penting. Lampiran: nilai penuh.
4. **Selalu sebutkan pembanding.** "Rp 362 juta" tanpa "dibanding Rp 412 juta
   bulan lalu" tidak berarti apa pun.
5. **Rentang lebih jujur daripada titik.** Untuk skenario dan ketidakpastian,
   tulis rentang, bukan satu angka.
6. **Format Indonesia.** Koma untuk desimal, titik untuk ribuan, `Rp` di depan.
   `evidence.json` tetap menyimpan nilai mesin.

## 6. Chart

Diambil dari `my-da-brain/references/visualization-and-delivery.md`, dengan
batas jumlah.

| Aturan | Penjelasan |
|---|---|
| Judul adalah temuan | "Penjualan turun sejak Maret", bukan "Penjualan per bulan" |
| Satu chart satu pesan | jangan gabung tiga pertanyaan dalam satu gambar |
| Maksimal 5 seri | lebih dari itu, pecah atau agregasi |
| Label langsung | angka di ujung garis/batang, bukan legenda yang harus dicocokkan |
| Sumbu jujur | batang mulai dari nol; jika dipotong, tulis alasannya |
| Wajib dirujuk di paragraf | gambar tanpa rujukan dihapus |
| Wajib disertai tabel angka | pembaca yang tidak bisa membaca chart tetap dapat angkanya |
| Maksimal 6 chart di badan | sisanya ke lampiran |

**Batas panjang tiap chart: satu paragraf, maksimal 5 kalimat.** Ini menggantikan
aturan `notebook-paper` yang meminta 2–3 paragraf per visualisasi. Untuk pembaca
awam, paragraf kedua dan ketiga hampir selalu pengulangan.

## 7. Panjang

Tidak ada batas halaman. Yang membatasi:

| Pembatas | Nilai |
|---|---|
| Keputusan di ringkasan | maksimum 3 |
| Chart di badan laporan | maksimum 6 |
| Paragraf per chart | 1 (maks 5 kalimat) |
| Aksi di bagian 7 | maksimum 3 |
| Bagian "tidak bisa dijawab" | maksimum 5 bullet |
| Lampiran | tanpa batas |

Aturan berhenti: **satu bagian selesai ketika pertanyaannya terjawab.** Menambah
paragraf setelah itu adalah pengulangan, dan pengulangan menurunkan kepercayaan.

Panjang wajar untuk dataset UMKM: 5–9 halaman termasuk lampiran. Jika keluar 20
halaman, hampir pasti ada temuan yang seharusnya turun ke lampiran.

## 8. Bukti dan keterlacakan

- Setiap angka di badan laporan menunjuk `E-###`.
- Lampiran memuat tabel: id, pernyataan, nilai, cell, file output.
- Klaim yang tidak punya `E-###` **tidak boleh** masuk laporan. Renderer menolak.
- Temuan yang gugur di F6 masuk lampiran sebagai hipotesis, bukan dibuang diam-diam.
- Bagian "yang tidak bisa dijawab" bersumber dari `cannot_answer` di evidence.

## 9. Checklist mutu

Dipakai sebagai validator otomatis sebelum laporan diterbitkan. Semua harus lulus.

| # | Pemeriksaan | Gagal jika |
|---|---|---|
| 1 | Ringkasan di halaman pertama, memuat ≤ 3 keputusan | keputusan muncul pertama kali di tengah |
| 2 | Setiap keputusan punya aksi | ada temuan tanpa tindakan |
| 3 | Setiap persentase disertai angka asli | ada "%" tanpa nominal |
| 4 | Setiap angka adalah slot `{{E-###}}` | ada angka literal di luar slot |
| 5 | Tidak ada em-dash | ditemukan `—` |
| 6 | Tidak ada kata terlarang | ditemukan salah satu dari daftar §4 |
| 7 | Setiap chart punya judul temuan dan dirujuk | ada gambar tanpa rujukan |
| 8 | Setiap chart disertai tabel angka | gambar tanpa angka |
| 9 | Ada bagian "yang tidak bisa dijawab" | bagian hilang |
| 10 | Lampiran bukti lengkap | ada `E-###` yang tidak punya baris lampiran |
| 11 | Paragraf ≤ 4 baris, kalimat ≤ 20 kata | ada pelanggaran |
| 12 | Tidak ada klaim tanpa pembanding | "naik" tanpa "dari X ke Y" |

## 10. Yang ditolak

- Menyalin notebook ke laporan. Notebook adalah bukti, laporan adalah terjemahan.
- Menjelaskan metode lebih dari satu paragraf. Pembaca tidak membeli metode.
- Grafik tanpa angka pendamping.
- Rekomendasi tanpa penanggung jawab dan tenggat.
- Kalimat penutup motivasi ("mari kita tingkatkan bersama").
- Menyembunyikan keterbatasan data di lampiran. Keterbatasan ada di badan laporan.
- Menambah bagian karena "laporan yang bagus biasanya punya bagian ini".
