<!-- source: agentic-coding-skill/deep-dive/SKILL.md (reconstruction, seven lenses, four-axis scoring, verdicts), LANES.md §3, PROMPT-MAP.md §5, CONTRACTS.md §1, evidence.md (verified lifecycle), origin: product (stall trigger, contested instead of demoted, phase-boundary checkpoint) -->

# Deep Dive

A checkpoint is a judgement, not an analysis. You stop writing cells, look at what the
last batch actually established, and decide whether the next planned cell is still the
best move.

The value comes from looking across a batch. A single cell is too small to show a
pattern, and a checkpoint after every cell is overhead with no information.

## When it runs

| Trigger | Setting | Notes |
|---|---|---|
| every N cells | `SWARMFOLD_DEEPDIVE_EVERY`, default 10 | counted from the last checkpoint, not from the run start |
| stall | `SWARMFOLD_STALL_CELLS`, default 3 | consecutive cells with no numeric output |
| before leaving a phase | always | the cheapest moment to notice the phase question is not actually answered |

A forced checkpoint is not a special kind of checkpoint. The same file, the same
verdicts, one difference: the stall must be addressed by name in the reconstruction.

The checkpoint itself writes no analysis cell. It costs one turn and produces one
small file.

## Non-negotiables

1. **Numbers only.** Every claim in the reconstruction quotes a value that a cell
   printed. A cell with no numeric output established nothing.
2. **No candidate without a test.** If the data already loaded cannot answer it in one
   cell, it is not a candidate.
3. **At most three candidates.** More than three means the ranking failed.
4. **Every candidate carries a kill criterion.** A detour without a stop rule becomes
   an expedition.
5. **"Nothing worth adding" is the normal answer.** Most checkpoints should end in
   `continue`. Inventing work to look productive is the failure this module exists to
   prevent.
6. **No modelling, ever.** No prediction, no clustering for its own sake, no
   significance test on a sample already known to be small.

## Step 1: reconstruct the batch

One row per cell since the last checkpoint:

| cell | intent | numbers printed | status |
|---|---|---|---|

Status is one of:

| Status | Meaning |
|---|---|
| `established` | a number answers the question and holds under the obvious alternative definition |
| `partial` | a number exists but the comparison is incomplete: no baseline, one period, mixed grain |
| `open` | the cell raised a question and answered none |
| `empty` | no numeric output; it established nothing |

Count the `empty` rows first. If more than a third of the batch is empty, that is the
finding, and it outranks every candidate: the next cell must have an intent whose
output is a number, and the verdict is `continue` with that cell named.

## Step 2: seven lenses

Each lens is a question, not a technique. Apply all seven to the reconstruction; report
only the ones that produced a candidate or a contested finding.

| Lens | Question |
|---|---|
| Assumption audit | which load-bearing assumption is still untested: grain, deduplication, currency, timezone, missingness mechanism |
| Anomaly residue | which outlier, spike, zero block, or negative value is still unexplained |
| Aggregate reversal | does any subgroup move opposite to the total |
| Denominator drift | did the population change between periods in a way that inflates or deflates a rate |
| Signal versus noise | is the effect larger than normal period-to-period variation, or inside it |
| Missing comparison | is there a conclusion with no baseline, no control segment, no counterfactual |
| Untouched dimension | which loaded column has never been used and could plausibly carry the explanation |

A lens that fires but yields no testable cell is recorded under "not proposed", with
the reason. That record is what keeps the next checkpoint from re-raising it.

## Step 3: score and filter

Score every surviving candidate from 1 to 3 on four axes:

| Axis | 1 | 3 |
|---|---|---|
| decision impact | changes a chart | could change a recommendation |
| testability | needs data not present | one cell with data already loaded |
| prior signal | no hint in any output | a printed number already points at it |
| rabbit-hole risk | unbounded | bounded by a clear stop rule |

Keep a candidate only if `decision_impact >= 2`, `testability == 3`, and
`rabbit_hole_risk <= 2`. Rank the survivors by `impact + prior_signal - risk`.

Take at most three. If the list is longer, the ranking failed, not the cap.

## Step 4: verdict

Three verdicts, and only three:

| Verdict | When | What it must name |
|---|---|---|
| `continue` | the next planned cell is still the highest-value move | that cell and the number it should print |
| `insert` | at least one candidate beats the plan | one candidate, its exact `intent`, its kill criterion, and the cap |
| `pivot` | the batch invalidated the direction | what is abandoned, and the printed number that caused it |

`insert` costs at most three cells, default three. After the detour, return to the
plan. Do not chain checkpoints into open-ended exploration: a second checkpoint that
again says `insert` at the same phase is a signal that the phase question was
misunderstood, not that the data is rich.

Every checkpoint also records what it deliberately did not propose, with the reason.
An empty `not_proposed` usually means the lenses were not applied.

## Contested is not demoted

`pivot` does not change any `verified` flag. Under `evidence.md` only F6 may set a
finding to `verified: false`, and a checkpoint is not an audit.

What a pivot does instead: it lists the findings whose basis is now in doubt under
`contested`, with the number that raised the doubt. Those entries stay verified, F6
attacks them first, and F7 may not write a decision built on a contested finding until
F6 resolves it.

This split matters. A checkpoint that demotes turns a reflection into an audit and
duplicates F6; a checkpoint that says nothing lets a broken finding reach the report.

## Stall

When the trigger is `stall`:

- the reconstruction names the consecutive cells with no numeric output, and why:
  exception, wrong grain, a cell that printed prose, a query that returned nothing
- the verdict cannot be `insert` unless the inserted cell prints a number
- after three failed attempts at the same step, close the phase with `cannot_answer`.
  A fourth attempt is the same failure with more tokens spent

## Output file

One file per checkpoint, numbered in order, never overwriting an earlier one:

```
evidence/deepdive/01.json
```

```json
{
  "checkpoint": 2,
  "after_cell": 20,
  "trigger": "every_10|stall|phase_boundary",
  "reconstruction": [
    {"cell": 11, "intent": "tren pendapatan bulanan", "numbers": ["revenue_q3=362.4m"], "status": "established"}
  ],
  "candidates": [
    {"question": "apakah penurunan terpusat di satu kanal", "impact": 3, "testability": 3, "prior_signal": 2, "risk": 1, "score": 4, "kill": "jika selisih antar kanal di bawah 2 poin persentase, tutup"}
  ],
  "decision": "insert",
  "next_intent": "pendapatan per kanal per bulan, satu baris per kanal",
  "cap_cells": 3,
  "contested": [],
  "not_proposed": [
    {"idea": "heatmap korelasi semua kolom", "why": "tidak menjawab pertanyaan fase dan tidak mengubah keputusan"}
  ]
}
```

Rules:

- Keys in English, values may be Indonesian, consistent with the rest of the run.
- `next_intent` follows the same rule as `cells/index.json`: one line, at most 120
  characters, because it is copied there verbatim.
- `cap_cells` never exceeds three.
- `contested` holds `E-###` ids only. No other field may carry a verification change.
- The file stays small: one line per cell, one line per candidate.

## Anti-patterns

Reject these even when they sound productive:

- a correlation heatmap of all columns: no question, no decision
- more visualisations of the same cut: the same number drawn twice
- a significance test when the sample is already known to be small
- sentiment analysis when no text column exists
- any predictive model, clustering, or segmentation for its own sake
- restating an established finding as a candidate ("cek apakah pendapatan turun")
- a kill criterion of "sampai tidak menarik lagi"
- deepening after the phase question is already answered. `LANES.md` says stop then,
  and this module is not exempt

## Exit check

All of these must be true before the next analysis cell:

- the file is written under the next free `NN`, with no earlier file overwritten
- reconstruction covers every cell since the last checkpoint, one row each
- the `empty` count and its ratio are printed in the reconstruction
- at most three candidates, each scored on four axes, each with a kill criterion
- `decision` is one of the three, and `next_intent` is present for `continue` and
  `insert`
- `insert` carries `cap_cells <= 3`, and the detour counter resets when the plan
  resumes
- `contested` is populated when a pivot happened, and no `verified` flag was touched
- `not_proposed` is non-empty whenever a lens fired without producing a cell
- no analysis cell was written during the checkpoint itself
