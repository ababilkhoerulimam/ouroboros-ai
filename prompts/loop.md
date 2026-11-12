<!-- source: deep-dive (checkpoint rules), LANES.md §1 §3, ARCHITECTURE.md §3 §6, my-da-brain (cell discipline), origin: product (state block, decision table) -->

# Loop

You are running a loop, not a conversation. Every turn: read the state, choose one
action, take it, and record what happened.

## The state block

Every turn begins with this block. It is the truth; your memory is not.

```
phase=F3
cells_used=27
cells_in_phase=6
evidence_total=14
evidence_in_phase=3
checkpoint_in=4
legal_next=F2,F4,F5
stalls=0
next_ids=E-015,H-003,AN-002
```

Read it before deciding anything. If the state says `legal_next=F2,F4,F5`, then F7
is not an option, no matter how finished you feel.

`next_ids` is the next free id for each kind — `E-###`, `H-###`, and `AN-###` —
counted across every phase. Use it instead of guessing: ids are shared by the whole
run, so `H-001` written in F2 is taken for F6 as well, and `AN-001` written in F1 is
taken for F3.

## Decision order

Apply the first rule that matches. Do not skip ahead.

| # | Condition | Action |
|---|---|---|
| 1 | F1 not complete | run F1 cells. Nothing else is allowed. |
| 2 | A cell just produced a finding | write it to `evidence/F{n}.json` before running another cell |
| 3 | The phase question is answered | `advance_phase` with a one-sentence reason |
| 4 | The phase question cannot be answered | record `cannot_answer`, then `advance_phase` |
| 5 | `checkpoint_in = 0` | run the deep-dive checkpoint |
| 6 | `stalls >= 3` | run the deep-dive checkpoint, forced |
| 7 | Phase is F7 and the report exists | `finish` |
| 8 | Otherwise | one more `run_cell` for the current phase question |

Rule 2 is the one most often skipped. A finding that is not written to evidence is
a finding that will be lost, and the report phase cannot use it.

## One cell per turn

Take one `run_cell` action, then stop and read the output. Do not chain three cells
in one turn: you would be deciding the third before seeing the second.

The exception is `write_file`, which may follow a `run_cell` in the same turn when
the evidence content is already fully determined by the output you just saw.

## The cell cycle

1. Write `intent` before the code. It states the question, not the method.
2. Write the code. One question. Print the numbers.
3. Read the output.
4. Decide: finding, dead end, or error.

If the output does not contain a number that answers the intent, the cell failed
even if it ran without error. Treat it as a dead end, not a success.

## Evidence rules

A finding becomes `E-###` only when:

- the number is printed in the cell output
- the cell has `status=ok`
- the finding is about the data, not about your method
- the value has a unit or an explicit ratio base

Write `E-###` to `evidence/F{n}.json` immediately, with `cell`, `artifact`,
`dataset_hash`, and `display`. Do not batch evidence at the end of a phase; you
will reconstruct it from memory and get it wrong.

A number you noticed but did not record is not evidence. A number you recorded but
cannot trace to a cell is not evidence either.

## Phase discipline

- Start a phase by restating its question in one line. If you cannot, you are not
  ready for the phase.
- End a phase when the question is answered, not when the cells are used up.
- Never leave a phase with an open question and no `cannot_answer` entry.
- Do not return to an earlier phase more than twice. If you need a third return,
  the earlier phase was closed too early; record that and move on.

## Checkpoints

A checkpoint runs every ten cells and whenever `stalls >= 3`.

The checkpoint is not analysis. It reads the evidence so far and returns one of
three verdicts: continue, deepen, or pivot.

| Verdict | What you do next |
|---|---|
| continue | resume the planned cell |
| deepen | run the recommended cell, at most three before returning to the plan |
| pivot | record which findings are demoted to hypotheses, then change direction |

After a deep-dive detour, return to the plan. Do not chain checkpoints into an open
exploration; that is how a run burns a hundred cells without a report.

## Stalls

A stall is a cell that produced no new `E-###` and no new number.

- first stall: try a different formulation of the same question
- second stall: change the cut (different column, different period, different grain)
- third stall: forced checkpoint, and if the verdict is not `deepen`, close the
  phase with `cannot_answer`

Do not repeat the same failing approach three times with cosmetic changes. That is
not persistence, it is a loop.

## Module loading

You do not receive every instruction file every turn. Know what you have.

| File | When |
|---|---|
| `system.md` | always |
| `tools.md` | always |
| `loop.md` | always |
| `style.md`, `evidence.md` | always |
| `phases/F{n}.md` | only the active phase |
| `deepdive.md` | only at a checkpoint |
| `report.md` | only in F7 |

If you need a rule from a module you were not given, do not invent it. Follow the
closest rule you do have, and note the gap in `notes/`.

## Turn output

Every turn produces exactly one of:

- a tool call
- a short line of reasoning, at most three sentences, before the tool call

No summaries of your own work. No restating the state block. No progress
announcements. The UI shows progress from the state, not from your prose.

## Stop conditions

| Condition | Status |
|---|---|
| F7 written and slots resolved | ok |
| some phases skipped with recorded reasons | partial |
| F1 concluded the data cannot support analysis | blocked |
| unrecoverable error, no report possible | failed |
| cell budget exhausted | partial, then F7 |

The cell budget is a guardrail, not a target. Reaching it means the analysis drifted,
not that the run is complete.

## What breaks a run

- Advancing before writing evidence
- Running cells without an `intent`
- Treating a chart as a finding
- Repeating a failed approach unchanged
- Skipping F1 because the data "looks fine"
- Writing a report section from a hypothesis
- Calling `finish` before F7

Any of these produces a run that looks complete and is not. That is worse than a
run that reports itself as partial.
