# LANES — fase analisis

Status: draft v0.1
Rujukan: `PRD.md`, `ARCHITECTURE.md`

## 1. Model eksekusi

Satu run = satu kernel = satu notebook. Tujuh fase berjalan berurutan di dalam
notebook yang sama. Tidak ada proses paralel, tidak ada notebook terpisah.

Alasan: data bersih yang diunduh harus satu versi konsisten, dan notebook yang
dibaca pengguna harus berurutan. Lima agent paralel akan menghasilkan lima versi
kebenaran yang harus direkonsiliasi — biaya yang tidak sepadan dengan manfaatnya.

Independensi sudut pandang tetap dijaga lewat dua mekanisme:

- setiap fase menutup dengan berkas bukti sendiri (`evidence/F{n}.json`);
- F6 (Penantang) secara khusus menyerang temuan lima fase sebelumnya.

### Fase dipilih model, transisi divalidasi controller

Model tidak menjalankan urutan kaku, tetapi juga tidak bebas berkeliaran. Ia
memanggil `advance_phase(target, reason)`; controller memeriksa prasyarat dan
mengembalikan daftar target sah bila ditolak (tabel lengkap di
`ARCHITECTURE.md` §3).

Prasyarat minimum yang tidak bisa dilanggar:

| Prasyarat | Alasan |
|---|---|
| F1 selesai sebelum fase apa pun | tanpa grain dan kualitas data, semua temuan tidak bermakna |
| F3 hanya setelah F2 punya temuan | tidak bisa menjelaskan perubahan yang belum diukur |
| F5 hanya setelah ada temuan F2/F3 | skenario tanpa dasar adalah ramalan |
| F7 hanya setelah F6 | laporan harus memuat temuan yang sudah diuji ulang |
| Kembali ke fase sebelumnya maksimum 2 kali per fase | mencegah osilasi yang menghabiskan biaya |

Konsekuensi untuk prompt: setiap turn menyertakan blok state (fase aktif, cell
terpakai, jumlah `E-###`, transisi sah). Tanpa itu, model memilih fase berdasarkan
tebakan dan akan melompat ke F7 terlalu dini.

## 2. Tujuh fase

| Fase | Nama | Pertanyaan tunggal | Berkas bukti | Blocking |
|---|---|---|---|---|
| F1 | Data Reality | Apakah angka ini layak dipercaya? | `evidence/F1.json` | **ya** |
| F2 | What Happened | Apa yang berubah, di segmen mana? | `evidence/F2.json` | tidak |
| F3 | Why | Kenapa berubah? (volume / mix / rate) | `evidence/F3.json` | tidak |
| F4 | Who & When | Siapa bertahan, di tahap mana putus? | `evidence/F4.json` | tidak |
| F5 | What Next | Kalau dibiarkan jadi apa? Opsinya apa? | `evidence/F5.json` | tidak |
| F6 | Penantang | Temuan mana yang tidak tahan uji? | `evidence/F6.json` | tidak |
| F7 | Writer | Bagaimana menjelaskan ini ke pemilik usaha? | `laporan.md` | tidak |

### F1 — Data Reality (blocking)

- Inventaris file, deteksi tipe, hash.
- Deteksi grain: kandidat primary key, duplikasi persis, duplikasi parsial.
- Peta missingness: berapa persen, pola (acak / sistematis), kolom yang tidak
  dapat dipakai.
- Deteksi tipe salah: angka tersimpan sebagai teks, tanggal sebagai teks,
  pemisah desimal koma, mata uang menempel.
- Deteksi hubungan antar file: kandidat join key, kardinalitas, risiko duplikasi
  saat join.
- Menetapkan metrik mana yang sah dihitung dari data ini, dan metrik mana yang
  **tidak** bisa (contoh: margin tidak bisa tanpa kolom biaya).
- Menulis `data_dictionary.md` awal dan `cleaning_log.json` awal.

Keluaran wajib: daftar kolom siap pakai, daftar kolom yang dibuang beserta alasan,
dan pernyataan eksplisit "pertanyaan apa yang tidak bisa dijawab data ini".

Jika F1 menyimpulkan data tidak layak (mis. tidak ada kolom waktu dan tidak ada
kolom nominal), run berhenti di sini dan menerbitkan laporan "data belum siap"
berisi apa yang perlu dilengkapi pemilik usaha. Ini hasil sah, bukan kegagalan.

### F2 — What Happened

- Tren metrik utama per periode (bulan/kuartal, sesuai granularitas data).
- Dekomposisi per segmen: produk, wilayah, kanal, atau kolom kategorikal lain
  yang tersedia.
- Konsentrasi: berapa persen pendapatan dari 20% item teratas.
- Setiap grafik disertai tabel angka yang dicetak.

### F3 — Why

- Dekomposisi perubahan: volume, mix, rate. Total perubahan harus sama dengan
  jumlah komponennya; residual harus nol dan ditampilkan.
- Kontribusi per segmen terhadap perubahan total, dengan bucket "lainnya" agar
  total tetap 100%.
- Audit Simpson's Paradox sebelum menyimpulkan arah.
- Jika penyebab tidak dapat diidentifikasi dari data, tulis demikian — jangan
  mengarang sebab.

### F4 — Who & When

- Cohort retensi (jika ada identifier pelanggan).
- Funnel tahap demi tahap (jika ada status / tahapan).
- Drop-off per tahap, bukan rata-rata global.
- Jika tidak ada identifier pelanggan, fase ini menyatakan tidak berlaku dan
  melewati diri sendiri.

### F5 — What Next

- Skenario, bukan satu angka ramalan: pesimis / dasar / optimis, dengan asumsi
  tertulis.
- Rentang ketidakpastian dari variasi historis, bukan dari model.
- Daftar aksi yang dapat diuji minggu depan, masing-masing dengan metrik
  pengukurnya.
- Dilarang memakai model prediktif; ini fase analisis, bukan pemodelan.

### F6 — Penantang

Tugasnya menyerang, bukan melengkapi:

- Cek ulang setiap `E-###` yang diklaim sebagai temuan: apakah angkanya benar-
  benar tercetak di output, atau hasil interpretasi?
- Cari pembalikan arah (Simpson's Paradox), denominator yang bergeser, sampel
  terlalu kecil, periode yang tidak sebanding.
- Temuan yang tidak lolos diturunkan statusnya menjadi hipotesis (`H-###`) dan
  **tidak boleh** masuk laporan.
- Menulis `evidence/F6.json` berisi daftar temuan yang gugur beserta alasannya.

### F7 — Writer

- Membaca hanya `evidence/*.json`, bukan notebook, bukan data mentah.
- Menulis prosa dengan slot `{{E-###}}`; tidak mengetik angka sendiri.
- Struktur: maksimal 3 keputusan, tiap keputusan memuat temuan, angka, mengapa
  penting, aksi, batasan.
- Struktur bagian, aturan bahasa, aturan angka, dan checklist mutu mengikuti
  `REPORT-STANDARD.md`.
- Wajib ada bagian "Yang tidak bisa dijawab dari data ini".
- Wajib ada bagian "Cara membaca angka ini" (satu paragraf, bahasa awam).

## 3. Deep-dive checkpoint

Setiap 10 cell (dapat dikonfigurasi lewat `SWARMFOLD_DEEPDIVE_EVERY`), agent
berhenti menulis cell analisis baru dan menjalankan satu putaran refleksi:

1. Apa temuan baru sejak checkpoint terakhir?
2. Apakah ada pertanyaan lanjutan yang lebih bernilai daripada melanjutkan fase?
3. Apakah ada anomali yang belum dijelaskan?
4. Apakah ada segmen/kolom yang belum disentuh?

Hasilnya ditulis ke `evidence/deepdive/NN.json` berisi keputusan: `continue`,
`insert`, atau `pivot`. Jika `insert`, agent menambahkan cell tambahan sebelum
melanjutkan fase. Maksimum 3 cell tambahan per checkpoint, agar tidak melebar.

Deep-dive juga dipicu paksa oleh deteksi stagnasi (`SWARMFOLD_STALL_CELLS`).

## 4. Aturan bukti

Berlaku di semua fase.

| Aturan | Penegakan |
|---|---|
| `E-###` hanya untuk temuan yang angkanya tercetak di output cell | validator menolak `E-###` tanpa `cell` + `artifact` |
| `H-###` untuk hipotesis, `AN-###` untuk anomali | tidak boleh dirujuk laporan |
| Setiap transformasi data mencetak before/after (baris, kolom, null) | cell tanpa angka dianggap tidak menghasilkan bukti |
| Cell tanpa output numerik tidak dihitung sebagai kemajuan | dipakai deteksi stagnasi |
| Chart selalu disertai tabel angka yang sama | chart tanpa angka tidak diterima |
| Angka di laporan hanya lewat slot `{{E-###}}` | renderer menolak slot tanpa bukti |

## 5. Chart

Chart adalah **keluaran**, bukan masukan penalaran. Agent tidak pernah membaca
gambar; seluruh keputusan diambil dari angka yang tercetak.

Syarat setiap chart:

- disimpan ke `charts/F{n}_{nn}_{slug}.png`, minimal 150 dpi;
- tertanam di notebook pada cell yang sama;
- memiliki judul, label sumbu dengan satuan, dan anotasi langsung pada titik
  penting (tanpa legenda yang harus ditebak);
- sumbu nominal mulai dari nol kecuali ada alasan yang ditulis;
- didahului atau diikuti tabel angka yang identik dengan isi chart.

## 6. Prompt

Prompt tidak memakai skill global yang terpasang di mesin. Seluruh perilaku
didefinisikan di dalam repo:

```
prompts/
  system.md            peran, prinsip, larangan
  phases/F1.md … F7.md brief tiap fase
  deepdive.md          aturan checkpoint
  report.md            aturan penulisan laporan + struktur slot
  tools.md             dokumentasi tool untuk model
```

Alasan: skill global berubah di luar kendali repo dan memuat perilaku yang tidak
relevan (sinkronisasi eksternal, pemodelan, kompetisi). Prompt di repo dapat
di-diff, diuji, dan dipin per versi.

Aturan yang wajib ada di `prompts/system.md`:

- eksekusi sendiri, jangan menunggu manusia;
- jangan pernah mengarang angka; jika tidak tercetak, tidak ada;
- jangan menulis ke `data/`;
- setiap cell harus punya `intent` satu baris;
- hentikan fase ketika pertanyaannya terjawab, jangan menambah cell demi terlihat
  produktif.
