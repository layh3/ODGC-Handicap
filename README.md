# ODGC Handicap

Disc-golf handicap calculator for the Ottawa Disc Golf Club. Originally a
Visual Studio C++ tool by Ken (Jan 2018); now a Python port that reads
`RoundData.xlsx` directly, produces both the legacy ODGC handicap list and a
standard golf-style list with soft-capped `+` handicaps, and supports importing
UDisc league round exports in one command.

The original C++ source is preserved under [old/cpp/](old/cpp/) and the
Python port is verified byte-identical against its output (see
[golden/](golden/) and [verify.sh](verify.sh)).

## Quick start

```bash
# from the current season tab (default behavior)
python3 hc24.py --xlsx RoundData.xlsx --sheet active2025

# legacy flat-file input still works
python3 hc24.py                              # reads ./RoundData.dat

# import tonight's UDisc round and recompute
python3 import_udisc.py imports/lets-larrimac-evening-tags-series-lets-5-2026-06-03.xlsx \
        --event LETS05 --year 26
python3 hc24.py --xlsx RoundData.xlsx --sheet active2025
```

A run produces **eighteen** `*.txt` files in the current directory — nine
under the legacy ODGC convention (lowest HC anchored at 0, no "+" handicaps)
and the same nine with a `_golf` suffix using standard golf convention
(handicaps can be negative, displayed as `+X.X`).

| Output | Audience |
| --- | --- |
| `rankHC.txt` / `rankHC_golf.txt` | Everyone, sorted best-to-worst |
| `alphHC.txt` / `alphHC_golf.txt` | Everyone, alphabetical |
| `player_rounds.txt` / `player_rounds_golf.txt` | Internal — HC + rounds played |
| `odgcHC.txt` / `odgcHC_golf.txt` | ODGC members, scaled to each ODGC course |
| `odgccaCH.txt` / `odgccaCH_golf.txt` | Stripped list for the odgc.ca website |
| `atosHC.txt` / `atosHC_golf.txt` | TOSS list — ODGC + Atos-list members |
| `evHC.txt` / `evHC_golf.txt` | Ettyville (EV + ODGC + TOSS members) |
| `kvHC.txt` / `kvHC_golf.txt` | Kemptville club |
| `ladiesHC.txt` / `ladiesHC_golf.txt` | Ladies League |

Flags:
- `--odgc-only` — skip the `_golf` set
- `--golf-cap K` — tune the tanh soft cap (default `5.0`; `0` disables)
- `--export-dat PATH` — also write the parsed input out as a `.dat` (round-trip debugging)

Requirements: Python 3.9+, `openpyxl` (`pip install openpyxl`) for `--xlsx`
input. The `.dat` path has no dependencies.

## Input layout

The `active*` worksheets all follow the same layout. Columns A–C hold row
metadata; columns D onward are one column per player.

| Row | Col A | Col B | Col C | Cols D..D+i_pl |
| --- | --- | --- | --- | --- |
| 1 | — | — | `PLAYER` | player names |
| 2 | — | `end_2020_hc` | `HC` | seed handicap (`-1` if none) |
| 3–9 | — | — | — | seed differentials (`100` = no data) |
| 10 | — | `ODGCmember` | `status` | `0`/`1` |
| 11 | — | `Atos_List` | `status` | `0`/`1` |
| 12 | — | `EVmember` | `status` | `0`/`1` |
| 13 | — | `LadiesLeague` | `status` | `0`/`1` |
| 14+ | year (e.g. `26`) | event name | course code | raw scores (`0` = did not play) |

To add a round manually: append a new row, fill in the players who played
(others stay at 0), save. Helper columns to the right of the roster (e.g.
a `count` sum column) are detected and skipped.

## Course codes

`COURSE_ID` in [hc24.py](hc24.py) — keeps the C++ 0-indexed order exactly:

```
epw epb epy   eiw eib eiy   unq
lmb lmy   alm0 alm   kan   kpv mtn   cur
shr   upi   kvb kvy kvr   ffw rhl
alb aly alr   cf   ctp   sr sro
```

If a round uses a code that isn't in this list, the script prints a
`WARNING: unknown course codes` block to stderr and treats those rounds as
par-54 reference (`c_fac = 1.0`). The original C++ tool would silently
divide by zero on `crs_ref[0]` and corrupt every later round, so the
warning matters — unknown codes need a real fix.

## How the algorithm works

A custom variant of the USGA handicap formula. For each round, in
chronological order:

1. **Course difficulty.** `crs_ref[course]` is a rolling average of the
   top-5 raw scores ever shot on that layout. `c_fac = crs_ref/54` is the
   per-course difficulty multiplier. Events prefixed with `x` (B-tier)
   don't contribute to the course reference. The `unq` slot (index 7)
   uses just the current round's value.
2. **Stale-HC reset.** At a year boundary, any player whose last round
   was more than two years ago is reset to three pseudo-differentials at
   their current HC.
3. **Scratch + slope.** Adjusted score per player is `raw - hc * c_fac`.
   Outliers ≥ 1.4σ above the mean are dropped. The surviving mean is the
   round's scratch score. Slope comes from a least-squares regression of
   `(score - scratch)` vs HC, normalized to 113 and clamped to `[95, 165]`.
4. **Differential.** `diff = (raw - scratch) × 113 / slope / c_fac`.
5. **Updated HC.** Sort the player's most recent ≤20 differentials, take
   the lowest *N* (sliding scale: 1 for 3 rounds, up to 10 for 20+ rounds),
   average, multiply by 0.96, cap at 36.
6. **Sub-zero correction (ODGC mode only).** If any HC goes negative, the
   lowest is anchored at 0 and every player's HC + diffs shift up by the
   same amount. The `_golf` outputs skip this step entirely.

Course-scaled outputs are `base_HC × crs_ref[N] / 54` for each tee.

## ODGC vs. golf — two output sets

Both sets come out of one run. They differ only in the post-processing of HC.

| | ODGC (`*.txt`) | Golf (`*_golf.txt`) |
| --- | --- | --- |
| Sub-zero behavior | Anchor lowest HC at 0, shift others up | Allow negative HCs |
| Display | `0.00`, `1.23`, ..., `36.00` | `+4.71`, `0.83`, `5.45`, ..., `36.00` |
| `+` handicap compression | n/a | tanh soft-cap at `+K` (default `K=5`) |
| Use case | What the league has used for years | Standard golf convention; matches what new players expect |

### Why the golf side has compression

Disc-golf scoring volatility (one bad hole can be a +4) makes the natural
handicap formula produce eye-catching `+9` and `+10` numbers for top
players. That overstates the actual consistent skill gap.

The compression applies only to negative HCs:

```
hc_display = -K × tanh(|hc| / K)         if hc < 0
hc_display = hc                          if hc >= 0
```

With `K=5`:
- `+1` natural → `+0.99` displayed (untouched)
- `+4` natural → `+3.32` displayed (mild compression)
- `+8` natural → `+4.61` displayed
- `+12` natural → `+4.92` displayed (asymptotic; never reaches +5)

No hard ceiling: the function approaches `+K` but never reaches it.
High-handicap players are never affected.

`--golf-cap 0` disables compression. `--golf-cap 4` tightens it to `+4`
asymptote. `--golf-cap 6` loosens it. Compression is purely a display
layer; round-to-round HC calculation always uses the natural value, so
fairness and dynamics aren't touched.

### Why the two modes can rank players differently

The ODGC anchoring isn't a flat shift. Each time a player drops below
zero, the algorithm zeroes out their `numcz` most-recent diffs and adjusts
every other player's stored diffs. That permanently bakes the shift into
all subsequent rounds — even after old rounds roll off the 20-round
window, the system stays in the shifted state because each round's
scratch is computed from currently-anchored HCs.

In practice, the rank orderings differ by at most a couple of swaps near
the top. Within each list, ranks are stable across runs.

## UDisc import workflow

[import_udisc.py](import_udisc.py) reads a UDisc per-round xlsx export and
appends the round(s) directly into `RoundData.xlsx`:

```bash
python3 import_udisc.py imports/<udisc_file>.xlsx --event LETS04 --year 26
```

Matching cascade for each player name:

1. Exact match after Last_First flip
2. Same with diacritics stripped (`Melançon` → `Melancon`)
3. Case-insensitive
4. Unique-surname match (one `Last_*` in roster)
5. First-name shortening (`Christopher` → `Chris`)
6. Fuzzy match (`difflib`, ≥0.75 similarity)

Players that don't match are skipped (the round still imports, that
player's score stays `0` = did not play) and printed at the end so you
can decide whether to add them as new roster columns later.

Default UDisc division → course code mapping:

```
GOLD → lmy   (Larrimac Yellow tees, "shorter")
BLUE → lmb   (Larrimac Blue tees, "longer")
```

Override on a per-run basis with `--division-map NAME=code`.

Run `python3 import_udisc.py --dry-run ...` first to preview the matches.
A `RoundData.xlsx.bak` is created on the first real run.

## Differences from the original C++ source

The Python port is **byte-identical** to the C++ output on the same
`.dat` input (proven by [verify.sh](verify.sh) against [golden/](golden/),
which is captured fresh from the upstream C++ binary). Beyond that, the
following are intentional extensions or fixes:

### Bug fixes the Python silently applies

1. **Unknown-course divide-by-zero.** When a round uses a course code not
   in `COURSE_ID`, the C++ sets `i_c = 0` and computes `c_fac = crs_ref[0]
   / 54 = 0`, then divides by it → every subsequent round inherits the
   `±inf`/`NaN` and the algorithm cascades to garbage (all HCs cap at 36).
   The Python guards `c_fac = 1.0` when no course matches and prints a
   stderr warning so the operator notices.
2. **Helper-column detection.** The xlsx parser stops at the first
   roster column whose row-1 label is `count`, `total`, `sum`, etc.
   (Right-edge helper columns the spreadsheet maintainer adds for tally
   formulas would otherwise be parsed as fake players.)
3. **Regression with golf-mode HCs.** The C++ uses `hc[j] > -0.9` as a
   "has established HC" check — a proxy that holds in ODGC mode (real HCs
   never go negative) but fails in golf mode (a scratch player can sit at
   `-1.5`). The Python tracks `has_hc[j]` explicitly so golf mode doesn't
   spuriously drop top players from the round pool.

### New behavior on top of the original algorithm

1. **xlsx input.** `--xlsx RoundData.xlsx --sheet active2025` reads the
   spreadsheet directly, no manual export to `.dat` needed.
2. **Golf-style output set.** Every legacy output also produced with
   `_golf` suffix using standard golf "+" handicap conventions.
3. **Tanh `+` handicap compression.** Soft-caps the golf side at `+K`
   (default `5`) to handle disc-golf's score volatility without imposing
   a hard ceiling.
4. **UDisc league import.** `import_udisc.py` matches player names,
   detects division→tee, appends rounds to the xlsx in one command.
5. **`--export-dat`.** Useful for verification: parse xlsx → write `.dat`
   → run the C++ on it → diff against the Python output. Used to prove
   the xlsx parser produces an equivalent token stream.

### Upstream changes synced in May 2026

Cross-checked against Ken's `hc24.rar` (May 28, 2026 snapshot). Five real
changes brought over:

- Added `sr` (Sandy Row) at course index 28, `sro` (alt layout) at 29.
- `num_crs` bumped 28 → 30.
- `atosHC.txt` gained a `Sandy_Row` column (`crs_ref[28]`).
- `evHC.txt` qualification widened from `EV || ODGC` to `EV || ODGC || TOSS`.
- Course-catalog `cnm[]` array gained `"Sandy_Row"` but `nnm` wasn't bumped
  to match — the Python matches that exactly (entry sits unused in the
  array, no new row in `odgccaCH.txt`). One-line fix here if you want it
  to appear.

## Verifying changes

`golden/` holds the C++ tool's output on `RoundData.dat`, captured from
the latest C++ binary. The Python output must remain byte-identical:

```bash
./verify.sh
```

passes nine `PASS  <file>` lines if nothing has drifted.

The golf-mode outputs (`*_golf.txt`) don't have golden fixtures — they're
new behavior with no C++ reference to compare against. Their correctness
is implicit: the algorithm in golf mode is the same one minus the
sub-zero shift block, and `verify.sh` proves the rest of the pipeline.

## Project layout

```
hc24.py                 the calculator (read .dat or .xlsx; write 18 files)
import_udisc.py         UDisc league xlsx → append rounds → RoundData.xlsx
RoundData.xlsx          canonical input (current season + history)
RoundData.dat           legacy flat-file export (regression fixture)
verify.sh               regression runner (Python output vs golden/)
README.md               this file

golden/                 C++ reference outputs from RoundData.dat
imports/                source UDisc/PDGA files retained for audit
out/                    generated outputs (gitignored)

old/
  cpp/                  original C++ source + Visual Studio project
  sample_inputs/        per-event xlsx exports the C++ author kept
  sample_outputs/       outputs from old C++ runs (kept for reference)
```

## History

January 2018 — Ken writes the original VS C++ tool, manually fed a
tab-separated `RoundData.dat` exported from the spreadsheet each time.

May 2026 — Port to Python. `verify.sh` proves byte-identical reproduction.
Added direct xlsx reading, golf-style output set, tanh compression,
UDisc league import. Synced upstream changes from Ken's latest C++.
