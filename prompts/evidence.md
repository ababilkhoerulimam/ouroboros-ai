<!-- source: LANES.md §4, CONTRACTS.md §4, my-da-brain/SKILL.md (Evidence ID Hygiene, Evidence and Validation Gates), my-da-brain/references/metric-contract.md (Validation Checks), origin: product (append protocol, ratio vs percentage point) -->

# Evidence

Evidence is the only thing the report may cite. If a number is not in an evidence
file, it does not exist for the rest of the run, even if you remember printing it.

## Three kinds

| Kind | Use it for | Report may cite |
|---|---|---|
| `E-###` | a value printed by a cell that ran successfully | yes |
| `H-###` | an explanation you believe but cannot print | no |
| `AN-###` | something in the data that is wrong, extreme, or unexplained | no |

An `E` is a measurement. An `H` is a story. An `AN` is a defect. Mixing them is how
a run produces a confident report about nothing.

## The four-part test

A printed number becomes `E-###` only if all four hold:

1. **Printed.** The value appears in the output of the cell that produced it.
2. **Clean.** That cell has `status=ok`. A cell that raised an error and printed a
   partial number afterwards is not evidence.
3. **Based.** The value carries a unit, or a ratio carries its denominator.
   "0,124" is not evidence; "12,4% dari 3.320 pesanan" is.
4. **Traceable.** `cell` exists in `cells/index.json`, and `artifact` is the
   `.out.txt` that contains the number.

Fail any one and it is an `H` at best.

## Arithmetic is not measurement

Do not derive a number in your head from two printed values and record it. If the
report needs a percentage, a cell must print that percentage. A cell that prints
`revenue_q2` and `revenue_q3` but not the change has not measured the change.

The same applies to rounding: a number you rounded yourself is a new number. Print
the rounded form, or do not use it.

## Writing an entry

```json
{
  "id": "E-004",
  "pillar": "fact",
  "statement": "pendapatan turun 12,4% pada Q3 2025 dibanding Q2 2025",
  "value": -0.124,
  "unit": "ratio",
  "display": "-12,4%",
  "cell": 19,
  "artifact": "cells/019.out.txt",
  "chart": "charts/F3_02_dekomposisi.png",
  "dataset_hash": "sha256:...",
  "confidence": "high",
  "verified": true
}
```

| Field | Rule |
|---|---|
| `id` | unique in the run, sequential, never reused for a different statement |
| `statement` | one sentence, in Indonesian, contains the period and the comparison base |
| `value` | a number, never a string; percentages are ratios, `0.124` not `12.4` |
| `unit` | `ratio`, `IDR`, `count`, `days`, `pp`, `measure` |
| `display` | what the reader sees, Indonesian format |
| `cell` | must be `status=ok` |
| `artifact` | must contain the value |
| `chart` | optional; if present the file must exist |
| `dataset_hash` | the hash from `status.json`, unchanged |
| `confidence` | `high` full population printed directly, `medium` subset or small n, `low` proxy column or heavy exclusion |
| `verified` | `true` when written; only F6 may set it to `false` |

## `display` and `unit`

| `value` | `unit` | `display` |
|---|---|---|
| `-0.124` | `ratio` | `-12,4%` |
| `362400000` | `IDR` | `Rp 362,4 juta` |
| `3320` | `count` | `3.320 pesanan` |
| `-5.0` | `pp` | `-5 poin persentase` |
| `14` | `days` | `14 hari` |
| `14.2` | `measure` | `14,2 cm` |

`measure` is for a number whose unit belongs to the data itself: centimetres,
kilograms, seconds, a score. Write the unit in `display` exactly as the data writes
it. Never convert it to another unit, and never attach a currency the data does not
have.

**Ratio is not percentage point.** A share moving from 40% to 35% is `-0.05` ratio,
displayed as `-5 poin persentase`. It is not `-12,5%`. The relative change of a
share is a different quantity, and quoting the wrong one is the most common way a
correct measurement becomes a wrong claim. When both matter, record both as
separate findings with separate ids.

## Statement rules

- One sentence, falsifiable, with period and base.
- Bad: "pendapatan turun". No base, no period, cannot be checked.
- Good: "pendapatan Q3 2025 turun 12,4% dibanding Q2 2025".
- No causal verbs. "turun karena" needs a decomposition behind it, and that is F3.
- "sekitar" is allowed only when `value` is a bound and `display` shows the range.

## Hypotheses

Every explanation you cannot print goes here, never into findings.

| Status | Meaning |
|---|---|
| `unresolved` | no test yet, or the test was inconclusive |
| `supported` | a cell printed the discriminating number; name that `E-###` in the statement |
| `rejected` | tested and failed; keep it with the reason |

A rejected hypothesis that is deleted will be reinvented in a later phase. Keep it.

## Anomalies

Negative values, impossible dates, extreme outliers, unexplained gaps.

- `handled: true` only when a `cleaning_log.json` entry exists for it, or when it was
  deliberately kept and analysed separately.
- An anomaly never becomes an `E-###`. It is either handled or reported as a
  limitation in the report.
- An unhandled anomaly that touches a cited number invalidates that number. Record
  it before you cite anything built on the same column.

## cannot_answer

Phrase it as the question that cannot be answered, plus what is missing:

```
margin per produk: tidak ada kolom biaya
retensi pelanggan: tidak ada identifier pelanggan
```

Sources: the F1 metric or column-role table, F4 with no entity key, any phase closed on
a stall.
These lines feed the report section "Yang tidak bisa dijawab". Keep them short and
in Indonesian.

## The file protocol

`write_file` overwrites. So:

1. First finding in a phase: write a new file with `phase`, `question`, and one
   finding.
2. Later findings: `read_file` the current file, add the entry, write the whole
   object back. Never write a file that contains only the newest finding.
3. Before `advance_phase`: read the file once and confirm every finding you intend
   to report is present.

The validator rejects a malformed file. It cannot know which finding you forgot.
Only you can.

## One number, one id

If a later phase re-measures the same quantity over the same population and period,
cite the existing id. Do not mint a second one.

Mint a new id only when the population, the period, or the definition changed, and
say what changed in the statement. Two ids for one measurement produce a report that
contradicts itself in two sections.

## Verification lifecycle

- `verified: true` when written.
- F6 re-checks every `E-###`: is the number still printed, is the base the same, does
  a subgroup reverse the direction.
- F6 may set `verified: false`. The entry stays for audit, and the report renderer
  refuses to fill its slot.
- A demoted finding becomes an `H-###` with the reason attached. It does not vanish.

## Anti-patterns

| Pattern | Consequence |
|---|---|
| writing evidence from memory at the end of a phase | numbers drift, validator rejects |
| one id reused for two statements | the report cites the wrong number |
| `E-###` for a method choice ("saya memakai median") | method notes belong in `notes/` |
| `E-###` for a chart ("grafik menunjukkan penurunan") | a chart is not a number |
| `value` written as a string | schema violation, slot cannot render |
| a percentage with no base | cannot be verified or compared |
| recording an old phase's number under a new id | two ids, one measurement, contradictory report |
| citing an `H-###` in the report | renderer refuses, whole report fails |
