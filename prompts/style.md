<!-- source: my-da-brain/SKILL.md (Notebook and Code Contract, Core Invariants), my-da-brain/references/visualization-and-delivery.md, my-da-brain/references/interactive-analysis.md (Cell Shape), coding-rules/SKILL.md, LANES.md §5, origin: product (no cell numbering, chart text in Indonesian) -->

# Style

This file governs the code you write into cells and the charts those cells produce.
Prose is governed by `report.md` and only applies in F7.

## Cell shape

A cell is a question with an answer printed at the bottom. Nothing else.

- Do not number cells in code. There is no `# Cell 7 - ...` header. Order comes from
  `cells/index.json`, and the runner places your `intent` above the code as a
  markdown cell.
- Do not restate the intent as a comment. The intent is a tool argument. A comment
  that repeats it is noise.
- One question per cell. If describing the cell needs the word "and", split it.
- Import in the cell that needs it, once. An import-only cell establishes nothing
  and counts as a stall.

## Code hygiene

| Forbidden | Why | Instead |
|---|---|---|
| `print("=" * 60)` | decorative chrome | nothing, or a blank line |
| `print("[ STAGE 1 ]")` | unparseable in a log | `print("step=grain_check")` |
| emoji, arrows, symbols | noise in a document the owner reads | plain words |
| `# loop over each row` | translates the next line | delete it |
| `# TODO`, `pass`, `...` | incomplete behavior | finish the branch or drop it |
| `df.head(50)` | buries the number you needed | `.head(10)` plus `.shape` |
| `print(df.describe())` on 40 columns | 300 lines of context | select the columns you will cite |

Comments earn their place by explaining a reason, an invariant, an edge case, or a
tradeoff. They never label an assignment or announce a loop.

## Print discipline

- `key=value` pairs separated by `|`, one line per subject.
- Every rate prints its base. `rate=0.124` is not evidence;
  `refund_rate=0.124 refunds=412 orders=3320` is.
- Every mean prints `n`. Every total prints the row count behind it.
- Print the value in the unit the evidence file will use. The validator accepts a
  numerically equivalent value, so `change_pct=-12.4` backs `display: "-12,4%"`.
- Round for reading: two decimals for ratios, no decimals for rupiah above a
  thousand. Do not round so far that two different segments print the same number.

## Naming in the kernel

- One frame per grain. `df` is the source and is never reassigned to something else.
- Names carry the grain: `lines`, `invoices`, `monthly`, `by_product`.
- No names that need memory: `t1`, `x2`, `tmp`, `df2`.
- Derived files are numbered in creation order: `derived/01_clean.csv` is the
  deliverable, later files follow.

A frame whose grain you cannot state in one sentence will silently produce a wrong
average three cells later. Rename it before you use it.

## Charts

### Non-negotiables

1. A chart is output, never input. You reason from the printed table.
2. One chart, one message. Two questions means two figures.
3. The title states the finding, not the variable: "Pendapatan turun sejak Maret
   2025", not "Pendapatan per bulan".
4. The same cell prints the numbers plotted. A chart cell with no table is rejected.
5. A chart in the report must be referenced by a paragraph. An unreferenced chart
   is deleted, so do not draw it.

### File and embedding

- Path: `charts/F{n}_{nn}_{slug}.png`, for example `charts/F2_01_tren_bulanan.png`.
- Minimum 150 dpi, `bbox_inches="tight"`.
- `fig.savefig(...)` and `plt.show()` in the same cell. Saving without showing means
  the notebook has no image; showing without saving means the report has no file.
- Close the figure before the cell ends so the next cell starts clean.

### Text inside the chart

- Indonesian, because the owner reads the notebook too.
- Axis labels carry the unit: "Pendapatan (Rp juta)", "Jumlah pesanan".
- The subtitle or first annotation states the period and the comparison base.
- Numbers on the chart use the same rounding as the printed table.

### Axes

- Bars start at zero. A truncated bar chart exaggerates differences, and the reader
  cannot tell.
- A line chart may start above zero only when the variation is small against a high
  baseline, and only with the break annotated in the chart.
- No dual y-axes. Use two panels sharing the time axis instead.
- Time flows left to right, with no gaps for months that have no data. A missing
  month is annotated, not skipped silently.

### Labels and colour

- Label series at the end of the line or the end of the bar. A legend the reader has
  to match against colours is a defect, not a style choice.
- Maximum five series. More than five means aggregate or facet.
- Focal series in one accent colour; comparison series in muted grey. Directional
  change uses muted green and red, never neon.
- Categorical palettes must be readable for colour-blind readers. Never a rainbow
  or jet colormap.

### Chartjunk

No 3D, no gradient fills, no dark background, no heavy borders, no vertical
gridlines in a time series, no more than two decimals on a tick.

## Chart selection

| Intent | Chart | Guardrail |
|---|---|---|
| comparison across categories | horizontal bar, sorted | zero baseline, sorted descending |
| trend over time | line with markers | annotate breaks and partial periods |
| distribution | box plot with jittered points | print median, IQR, and n |
| parts of a whole | 100 percent stacked bar, max 5 parts | waterfall for decomposition |
| funnel | horizontal bars with step rates | print counts and step conversion |
| cohort retention | heatmap with printed percentages | future periods masked, never zero |
| correlation | scatter with transparency | only when both axes are continuous |

Pie charts only for two or three slices, and only when the parts really do sum to a
whole. Default to a bar.

## A compliant chart cell

```python
monthly = lines.groupby("bulan")["total"].sum().sort_index()
print(monthly.to_string())
print("months=%d total=%.0f" % (len(monthly), monthly.sum()))

fig, ax = plt.subplots(figsize=(7, 3.5))
ax.plot(monthly.index, monthly.values, color="#2563eb", linewidth=2, marker="o")
ax.set_title("Pendapatan turun sejak Maret 2025", loc="left")
ax.set_ylabel("Pendapatan (Rp juta)")
ax.set_ylim(bottom=0)
ax.grid(axis="y", alpha=0.2)
fig.savefig("charts/F2_01_tren_bulanan.png", dpi=150, bbox_inches="tight")
plt.show()
plt.close(fig)
```

Numbers first, chart second. The table is what the evidence file cites; the image is
what the owner looks at.

## Prohibited

- A chart in F1. F1 produces numbers, not pictures.
- A chart whose cell prints no numbers.
- A legend for three series that could be labelled directly.
- An axis without a unit.
- A title naming the column instead of the finding.
- `plt.show()` without `savefig`, or `savefig` without `plt.show()`.
- Drawing a chart you will not cite in the report.

## Self-check before the cell runs

1. Does the output contain the number that answers the intent?
2. Is the base printed next to every rate?
3. If there is a figure, is the table printed in the same cell?
4. Is any decorative output left in the code?
