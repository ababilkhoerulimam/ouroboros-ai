# PROMPT-MAP — reverse engineering dari tiga skill

Status: draft v0.1
Rujukan: `LANES.md` §6, `ROADMAP.md` M2/M3

Dokumen ini menetapkan bagian mana dari tiga skill sumber yang masuk ke modul
prompt produk, mana yang diubah, dan mana yang dibuang. Tujuannya agar prompt
produk dapat diaudit terhadap sumbernya, bukan ditulis dari nol tanpa jejak.

## 1. Sumber

| Skill | Ukuran | Peran di produk |
|---|---|---|
| `my-da-brain` | SKILL 142 baris + 6 referensi (± 530 baris) | isi analisis: metode, metrik, dekomposisi, jebakan statistik, chart |
| `coding-rules` | SKILL 61 baris + referensi | gaya kode dan larangan artefak AI |
| `deep-dive` | SKILL + rubrik + template + skrip | checkpoint tiap 10 cell |
| `notebook-paper` | SKILL 168 baris + panduan anti-AI-writing + framework insight | gaya laporan: larangan em-dash, kata terlarang, caption temuan, angka exact |

Ketiganya **tidak dipanggil saat runtime**. Isinya disalin ke `prompts/` supaya
versi produk tidak berubah diam-diam ketika skill global diperbarui.

## 2. Pemetaan bagian ke modul

### my-da-brain

| Bagian sumber | Modul target | Tindakan | Alasan |
|---|---|---|---|
| Core Invariants | `system.md` | salin hampir utuh | ini yang membuat laporan dapat dipercaya |
| Notebook and Code Contract | `style.md` | ubah | aturan "satu cell per turn" diganti "jalankan sendiri lalu lanjut" |
| Select the Operating Mode (9 mode) | dihapus sebagai mode, isinya disebar | pecah | mode adalah konsep percakapan manusia; produk memakai fase |
| Session Start (inventaris, ANALYSIS_STATE, konfirmasi) | `phases/F1.md` | tulis ulang | intake deterministik menggantikan tanya-jawab |
| Decision Policy ("tanya user bila ambigu") | `system.md` | **ganti** | tidak ada manusia; lihat konflik K1 |
| Phase Routing / handoff ke skill lain | dihapus | buang | produk tidak memuat skill lain |
| Evidence and Validation Gates | `phases/*.md` + `evidence.md` | salin sebagai kriteria selesai fase | |
| State Updates + sinkronisasi Notion | dihapus | buang | privasi; lihat konflik K5 |
| `references/metric-contract.md` | `phases/F1.md` | salin | grain, denominator, validasi metrik |
| `references/analysis-methods.md` | `phases/F2.md`, `phases/F4.md` | salin sebagian | tren, konsentrasi, cohort, funnel |
| `references/root-cause-and-decomposition.md` | `phases/F3.md` | salin | PVM, Adtributor, residual nol |
| `references/statistical-traps-and-guardrails.md` | `phases/F6.md` + `phases/F3.md` | salin | Simpson, denominator, sampel kecil |
| `references/visualization-and-delivery.md` | `style.md` (bagian chart) | salin | label langsung, sumbu jujur, tanpa chartjunk |
| `references/interactive-analysis.md` | `style.md` | ubah | template 4-pillar dipertahankan, aturan numbering diganti |

### coding-rules

| Bagian sumber | Modul target | Tindakan | Alasan |
|---|---|---|---|
| Keep code free of generated-looking decoration | `style.md` | salin utuh | berlaku langsung untuk kode cell |
| Make comments earn their place | `style.md` | salin | |
| Deliver complete behavior | `system.md` | salin | melarang TODO dan placeholder di kode analisis |
| Establish the local contract | `system.md` | ubah | tidak ada repo di workspace; diganti "ikuti gaya cell sebelumnya" |
| Report work with evidence | `report.md` | ubah | audiens berubah dari developer ke pemilik usaha |
| Inspect the result (diff, formatter, tests) | `loop.md` | ubah | diganti "baca ulang output dan cocokkan angka" |

### deep-dive

| Bagian sumber | Modul target | Tindakan | Alasan |
|---|---|---|---|
| Non-negotiables | `deepdive.md` | salin | maks 3 kandidat, kill criterion wajib |
| Seven lenses | `deepdive.md` | salin | |
| Scoring 4 sumbu | `deepdive.md` | salin | |
| Verdict CONTINUE/DEEPEN/PIVOT | `deepdive.md` | salin | |
| Anti-patterns + rejection log | `deepdive.md` | salin | mencegah kerjaan palsu |
| "When this runs" (dipicu user) | `loop.md` | ganti | dipicu otomatis tiap 10 cell |
| `scripts/scan_cells.py` | dipakai runner, bukan prompt | tetap | prompt hanya menerima ringkasannya |

### notebook-paper

| Bagian sumber | Modul target | Tindakan | Alasan |
|---|---|---|---|
| Aturan anti-AI-writing (em-dash, kata terlarang, rule-of-three, negative parallelism) | `report.md` | salin | berlaku untuk semua prosa laporan |
| Zero orphan figures + caption yang menyatakan temuan | `report.md` | salin | |
| Angka exact dicetak tebal | `report.md` | salin | |
| Framework business insight ("so what?") | `report.md` | adaptasi | dipakai sebagai uji kelayakan tiap temuan |
| 4 Pilar Rekomendasi | `report.md` | ganti | menjadi 3 keputusan bisnis |
| Grounding literatur dan sitasi | dihapus | buang | pembaca UMKM tidak membaca daftar pustaka |
| Struktur 4 bab akademik | dihapus | buang | diganti struktur 9 bagian di `REPORT-STANDARD.md` |
| Kuota "2–3 paragraf per visualisasi" | `report.md` | **batalkan** | untuk pembaca awam ini pengulangan; diganti 1 paragraf maks 5 kalimat |
| Rumus OMML / LaTeX, template kompetisi | dihapus | buang | tidak relevan |

## 3. Konflik yang harus diselesaikan

Ini bagian terpenting: aturan skill sumber yang **akan mematikan** mode otonom
kalau disalin apa adanya.

| Kode | Aturan sumber | Konflik | Keputusan |
|---|---|---|---|
| K1 | "Ask the user to decide when metric definitions differ" | tidak ada manusia di tengah run | pilih default yang paling dapat dipertahankan, catat di `warnings` dan `cannot_answer`; dilarang berhenti |
| K2 | "Return exactly one cell, pause for execution output" | run berjalan otonom | jalankan sendiri lewat `run_cell`, baca output, lanjut |
| K3 | "Do not silently inspect dataset contents during setup" | F1 justru harus membaca isi data | izin inspeksi hanya di F1, dicatat di `cleaning_log` |
| K4 | "Before writing METHODOLOGY.md, ask permission" | tidak ada yang bisa ditanya | tidak ada dokumen metodologi terpisah; keputusan dicatat di `notes/` |
| K5 | "Sync findings to Notion" | data klien keluar dari mesin | dihapus total; tidak ada panggilan jaringan selain model |
| K6 | "Phase routing ke my-ds-brain / notebook-review" | produk tidak memuat skill lain | dihapus |
| K7 | "Cell N - description" numbering | lima fase berbagi satu notebook, nomor bertabrakan | numbering dihapus dari kode; urutan ditentukan `cells/index.json` |
| K8 | coding-rules "read AGENTS.md, run formatter/tests" | workspace run bukan repo | diganti: cocokkan gaya cell sebelumnya, jalankan ulang cell untuk verifikasi |

## 4. Yang sengaja dibuang

| Dibuang | Alasan |
|---|---|
| 9 operating mode sebagai konsep | membingungkan model; fase sudah menggantikannya |
| Sinkronisasi Notion dan state file eksternal | privasi, dan `status.json` sudah cukup |
| Handoff antar skill | produk hanya punya satu agent |
| Aturan numbering cell | digantikan urutan file |
| Instruksi pemodelan/prediksi dari my-da-brain | produk ini analisis, bukan pemodelan (F5 hanya skenario) |

## 5. Anggaran token per turn

Gateway model sudah menambahkan ± 2.000 token sebelum prompt kita dihitung
(diukur 2026-11-10). Karena itu modul dimuat selektif:

| Modul | Kapan dimuat | Perkiraan |
|---|---|---|
| `system.md` | setiap turn | ± 1.200 token |
| `tools.md` | setiap turn | ± 700 token |
| `loop.md` | setiap turn | ± 600 token |
| blok state | setiap turn | ± 300 token |
| `phases/F{n}.md` | hanya fase aktif | ± 500 token |
| `deepdive.md` | hanya saat checkpoint | ± 800 token |
| `report.md` | hanya F7 | ± 900 token |
| `style.md`, `evidence.md` | setiap turn | ± 800 token |

Total per turn biasa: ± 4.100 token prompt + 2.000 overhead gateway.

Yang **tidak** boleh terjadi: memuat seluruh `phases/` sekaligus, atau menyalin
skill sumber utuh ke satu `system.md` (akan menjadi ± 9.000 token dan mendorong
model mengikuti aturan yang saling bertentangan).

## 6. Urutan penulisan

| Urutan | Modul | Alasan urutan |
|---|---|---|
| 1 | `system.md` | semua modul lain merujuk padanya |
| 2 | `tools.md` | dibutuhkan sebelum loop dapat diuji |
| 3 | `loop.md` | mendefinisikan kapan tiap modul dimuat |
| 4 | `phases/F1.md` | fase pertama yang diuji end-to-end |
| 5 | `style.md`, `evidence.md` | menstabilkan bentuk keluaran |
| 6 | `phases/F2..F7.md` | pola sudah terbukti di F1 |
| 7 | `deepdive.md`, `report.md` | butuh `evidence.json` nyata untuk diuji |

## 7. Aturan pemeliharaan

- Setiap modul menyebut sumbernya di komentar HTML di baris pertama, contoh
  `<!-- source: my-da-brain/references/metric-contract.md -->`.
- Perubahan pada skill sumber **tidak** otomatis masuk ke produk. Harus disalin
  manual dan dicatat di dokumen ini.
- Jika sebuah aturan produk tidak ada di sumber mana pun, tandai sebagai
  `origin: product` agar jelas mana yang keputusan baru.
