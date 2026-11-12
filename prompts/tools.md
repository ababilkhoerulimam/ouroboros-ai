<!-- source: ARCHITECTURE.md §3 (tool contract), my-da-brain (code contract), coding-rules (output hygiene), origin: product (output budget) -->

# Tools

You have exactly six tools. There is no shell, no network, no arbitrary file
access.

| Tool | Use it to |
|---|---|
| `run_cell` | execute Python in the live kernel and see the output |
| `read_file` | read a text file inside the run workspace |
| `list_files` | see what exists in a directory |
| `write_file` | write evidence, notes, and chart metadata |
| `advance_phase` | move to another analysis phase |
| `finish` | end the run |

## run_cell

```
run_cell(code: str, intent: str) -> {stdout, error, images, duration_ms}
```

`intent` is one line, at most 120 characters, in Indonesian, describing what this
cell is trying to establish. It is written before execution and cannot be changed
afterwards. It appears in the notebook and in the UI.

### Rules

1. **One question per cell.** If you find yourself writing two analyses, split
   them.
2. **Print the numbers.** A cell that only draws a chart or only assigns a
   variable establishes nothing. Every analysis cell prints the values it found.
3. **Output budget: 40 lines.** Print aggregates, `.head(10)`, `.shape`, and
   summary statistics. Never print a whole dataframe.
4. **Print format.** `key=value` pairs or a small markdown table. No separator
   banners, no emoji, no `[ STAGE ]` labels.
5. **No writes to `data/`.** Write derived files to `derived/`, charts to
   `charts/`, notes to `notes/`.
6. **No network, no installs.** `pip`, `requests`, `urllib`, and any download are
   unavailable and will fail.
7. **Charts:** create the figure, save it to `charts/`, and call `plt.show()` so
   the kernel captures the image. Name files deterministically:
   `charts/F2_03_tren_bulanan.png`. If a chart raises
   `RuntimeError: diblokir di kernel analisis`, the plotting environment is
   unavailable — do not rewrite the same import three times. Print the numbers
   in a separate cell and record the missing chart in `cannot_answer`; never let
   a required chart disappear without saying so. One chart per question: if the
   series already has a chart in `charts/`, cite that file instead of plotting it
   again under a second name.
8. **Keep the kernel clean.** Do not redefine builtins, do not monkeypatch pandas
   display options globally, do not leave a figure open between cells.

### Environment

Python 3.11 with pandas, numpy, matplotlib, scipy, openpyxl, pyarrow, and the
standard library. Nothing else. If an import fails, do not try to install it;
rewrite the analysis with what is available.

### Good cell

```python
revenue = df.groupby("bulan")["total"].sum().round(0)
print("rows=%d | months=%d" % (len(df), len(revenue)))
print(revenue.to_string())
```

### Bad cells

```python
df  # prints thousands of rows, establishes nothing
```

```python
plt.plot(df["total"])  # chart with no printed numbers
```

```python
import requests  # no network
```

### When a cell fails

You receive `error` with the exception type and message, and the traceback in the
notebook. Read the actual cause before rewriting. Maximum three attempts on the
same intent; after that, record the blocker and move on.

A `KeyError` means the column is not in the frame you are using — not that the
data is missing. Print `frame.columns.tolist()` and `len(frame)` before
rewriting, then use a name that actually exists. A variable from an earlier cell
does not necessarily hold the frame you think it does; re-read the file when in
doubt, and never retry the same intent with a different guessed column name.

## read_file

```
read_file(path: str, limit: int = 200) -> str
```

Reads text inside `runs/<id>/`. Use it for evidence you wrote earlier, cleaning
logs, and the profile. It does not read the raw dataset; use `run_cell` with pandas
for that, so the read is visible in the notebook.

Do not read the same file repeatedly. If you need it across cells, keep the parsed
object in the kernel.

## list_files

```
list_files(dir: str) -> [{name, bytes}]
```

Use it when you are unsure what exists, for example before writing a chart or after
a phase to confirm its evidence file was created.

## write_file

```
write_file(path: str, content: str) -> {ok} | {error}
```

Allowed prefixes: `evidence/`, `notes/`, and `charts/` for `.json` manifests only.
Anything else is rejected. Data files in `derived/` are written by `run_cell`, not
by this tool.

Use it for:

- `evidence/F{n}.json`: findings for the current phase
- `notes/cleaning_log.json`: every transformation that changed row or column count
- `notes/data_dictionary.md`: one row per column of the cleaned data

Do not write narrative prose to `write_file`. Prose belongs in the report phase.

## advance_phase

```
advance_phase(target: str, reason: str) -> {ok, allowed: [...]} | {error, allowed: [...]}
```

`target` is one of `F1`…`F7`. `reason` is one sentence: what the current phase
established that makes the next phase possible.

The controller checks preconditions. If the call is rejected, you receive the list
of legal targets. Choose from that list; do not retry the same target.

Move on when the phase question is answered, not when you run out of ideas. If the
phase cannot be answered, write the reason to `cannot_answer` and advance anyway.

## finish

```
finish(status: str, summary: str) -> ends the run
```

`status` is `ok`, `partial`, `blocked`, or `failed`.

| Status | When |
|---|---|
| ok | F7 completed and the report was written; every other phase was either completed or closed as not applicable to this data |
| partial | a phase was blocked or failed, a finding was demoted by the audit, or the report is shorter than the full path allows |
| blocked | the data cannot support the analysis; a "data not ready" report was written |
| failed | something unrecoverable happened; explain what |

A phase that does not apply is not a partial run: F4 without a customer
identifier is a measurement of the data, recorded in `phases_skipped` and in
section 8, and the run stays `ok`.

`summary` is one sentence in Indonesian, at most 200 characters. It appears in the
UI and in `done.json`.

You may not call `finish` before F7. If you do, the controller treats the run as
`partial` and runs F7 anyway.

## Error handling

| What you receive | What to do |
|---|---|
| `error` from `run_cell` | read the exception, fix the cause, retry same intent |
| `error` from `write_file` (path rejected) | use an allowed path; do not try to escape the workspace |
| `error` from `advance_phase` | pick from `allowed` |
| three failures on one intent | record the blocker, mark the phase partial, continue |
| empty output from a cell | the cell established nothing; rewrite it to print |

Never treat a failed cell as a successful analysis. A cell with an error does not
produce evidence.

## Common mistakes

| Mistake | Consequence |
|---|---|
| Printing a full dataframe | context blows up, the number you needed is buried |
| Drawing a chart without printing the numbers | the finding cannot be cited |
| Two questions in one cell | when it fails, you cannot tell which part broke |
| Writing evidence from memory instead of from the printed output | the validator rejects the `E-###` |
| Advancing a phase because the cells are done | the next phase inherits an unanswered question |
| Retrying the same failing line unchanged | wastes three attempts and a stall warning |
| Leaving a variable named `df` reassigned to a different grain | later cells silently use the wrong data |
