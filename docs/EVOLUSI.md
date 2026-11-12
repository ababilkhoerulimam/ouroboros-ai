# Loop evolusi: cara menjalankan dan apa yang menjaganya

Loop ini membandingkan dua versi sistem pada benchmark ber-ground-truth, lalu
memutuskan apakah patch layak dipromosikan. Ia bukan pengganti penilaian
manusia: `main` tetap di tangan manusia, dan loop hanya mempertahankan branch
varian yang terbukti menaikkan skor di tune **dan** tidak menjatuhkan heldout.

## Perintah

```bash
# sekali per perubahan verifier: bekukan alat ukur
python -m swarmfold_verify.cli pin
python -m swarmfold_verify.cli verify-pin

# sebelum loop apa pun
python -m swarmfold_eval.cli selftest --root evals --repo .

# sekali per baseline (10 kasus x 3 replika)
python -m swarmfold_eval.cli baseline --root evals --repo . --worktree .

# per varian
python -m swarmfold_eval.cli evaluate --root evals --repo . --variant evals/variants/v001.json

# usul patch oleh model reviewer, lalu nilai otomatis
python -m swarmfold_eval.cli evolve --root evals --repo . --worktree . --rounds 1
```

`evolve` menjalankan satu putaran penuh: ukur sistem berjalan di split `tune`,
kirim skor + isi berkas dalam jangkauan ke model reviewer, lalu terapkan patch
hasil `revise` sebagai varian dan nilai dengan `evaluate`. Ronde berikutnya
dibangun dari branch yang dipromosikan (`parent = eval/rNN`), bukan dari
`eval/base`, supaya patch bertumpuk di atas perbaikan yang sudah terbukti.
Reviewer memakai `SWARMFOLD_REVIEWER_MODEL` bila diisi, kalau tidak model worker.

Berkas varian:

```json
{
  "variant_id": "v001",
  "parent": "eval/base",
  "layer": "prompt",
  "hypothesis": "aturan rasio sebagai persen menaikkan recall",
  "expected": "recall tune naik >= 0.10 tanpa menaikkan defect_rate",
  "diff_path": "v001.diff"
}
```

`evaluate` keluar dengan kode 0 hanya bila varian dipromosikan; verdict dan
`seq` ledger dicetak sebagai JSON.

## Yang menjaga loop

| Berkas | Menjaga |
|---|---|
| `swarmfold_verify/pins.py` | skor dihitung dari snapshot verifier yang di-commit, bukan dari `src/` yang baru dipatch |
| `swarmfold_eval/patcher.py` | patch hanya boleh menyentuh `prompts/` dan `src/swarmfold/`; path di luar itu, symlink, path yang di-ignore git, rename, dan diff biner ditolak |
| `swarmfold_eval/gate.py` | promosi butuh median tune naik `min_delta`, heldout tidak turun lebih dari `max_regression`, dan guardrail `false_discovery`/`defect_rate` lolos |
| `swarmfold_eval/ledger.py` | satu baris per varian, berantai `prev_sha`; menyunting satu baris memutus rantai sesudahnya |
| `swarmfold_verify/split.py` | `sealed` tidak bisa dipilih untuk seleksi; `splits.json` harus cocok dengan truth |
| `swarmfold_eval/orchestrator.py` | urutan kaku: ledger → pin/split → patch → run → skor → keputusan; baseline diikat ke digest verifier |

## Yang masih manual

- **Promosi** hanya mempertahankan branch `eval/<vid>`. Memindahkan `eval/base`
  ke branch itu, dan menggabungkannya ke `main`, masih dilakukan manusia.
- **Rotasi seed** tiap 10 promosi belum diotomatiskan: ubah `seed` di
  `swarmfold_verify/cases.py`, jalankan `build`, lalu ukur ulang baseline.

## Reviewer tidak bisa menulis ulang dirinya

Instruksi reviewer hidup di `src/swarmfold_eval/reviewer.py`, dan
`src/swarmfold_eval/` ada di `patcher.DENIED`. Varian yang dipromosikan karena
itu tidak bisa melonggarkan penilainya sendiri; satu-satunya cara mengubah
reviewer adalah commit manusia.
