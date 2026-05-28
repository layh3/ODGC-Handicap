# ODGC Handicap

Disc-golf handicap calculator for the Ottawa Disc Golf Club. Reads round
scores out of `RoundData.xlsx` and writes per-club handicap lists.

## Quick start

```bash
# from the current season tab
python3 hc24.py --xlsx RoundData.xlsx --sheet active2025

# or from the legacy flat-file input (still supported)
python3 hc24.py
```

That's it. Nine `*.txt` files appear in the current directory:

| Output | Audience |
| --- | --- |
| `rankHC.txt` | Everyone, sorted best-to-worst |
| `alphHC.txt` | Everyone, alphabetical |
| `player_rounds.txt` | Internal — HC + rounds played |
| `odgcHC.txt` | ODGC members, scaled to each ODGC course |
| `odgccaCH.txt` | Stripped list for the ODGC website |
| `atosHC.txt` | TOSS list — ODGC + Atos-list members |
| `evHC.txt` | Ettyville members |
| `kvHC.txt` | Kemptville club |
| `ladiesHC.txt` | Ladies League |

Requirements: Python 3.9+, `openpyxl` (`pip install openpyxl`) for `--xlsx`
input. The `.dat` path has no dependencies.

## How the input is laid out

The `active*` worksheets all follow the same layout. Columns A–C hold row
metadata; columns D onward are one column per player.

| Row | Col A | Col B | Col C | Cols D..i_pl+3 |
| --- | --- | --- | --- | --- |
| 1 | — | — | `PLAYER` | player names |
| 2 | — | `end_2020_hc` | `HC` | seed handicap (`-1` if none) |
| 3–9 | — | — | — | seed differentials (`100` = no data) |
| 10 | — | `ODGCmember` | `status` | `0`/`1` |
| 11 | — | `Atos_List` | `status` | `0`/`1` |
| 12 | — | `EVmember` | `status` | `0`/`1` |
| 13 | — | `LadiesLeague` | `status` | `0`/`1` |
| 14+ | year (e.g. `25`) | event name | course code | raw scores (`0` = did not play) |

To add a round: append a new row in column A/B/C with the year/event/course,
fill in scores for the players who played (leave others at 0), save.

Helper columns to the right of the roster (e.g. a `count` sum column) are
detected and skipped.

## Course codes

The full list lives in `COURSE_ID` in `hc24.py`. Currently recognized:

```
epw epb epy   eiw eib eiy   unq
lmb lmy   alm0 alm   kan   kpv mtn   cur
shr   upi   kvb kvy kvr   ffw rhl
alb aly alr   cf   ctp
```

If a round uses a course code that isn't in this list, the script prints
a `WARNING: unknown course codes` block to stderr and treats those rounds
as par-54 reference (`c_fac = 1.0`). The original C++ tool would silently
divide by zero and corrupt every later round, so the warning matters —
unknown codes are usually a typo or a course that needs adding.

## How the algorithm works

A custom variant of the USGA handicap formula. For each round, in
chronological order:

1. **Course difficulty.** `crs_ref[course]` is a rolling average of the
   top-5 raw scores ever shot on that layout. `c_fac = crs_ref/54` is the
   per-course difficulty multiplier. Events prefixed with `x` (B-tier) do
   not contribute to the course reference.
2. **Stale-HC reset.** At a year boundary, any player whose last round
   was more than two years ago is reset to three pseudo-differentials at
   their current HC.
3. **Scratch + slope.** Adjusted score per player is
   `raw - hc * c_fac`. Outliers ≥ 1.4σ above the mean are dropped. The
   surviving mean is the round's scratch score. Slope comes from a
   least-squares regression of `(score - scratch)` vs HC, normalized to
   113 and clamped to `[95, 165]`.
4. **Differential.** `diff = (raw - scratch) * 113 / slope / c_fac`.
5. **Updated HC.** Sort the player's most recent ≤20 differentials, take
   the lowest *N* (sliding scale: 1 differential for 3 rounds, up to 10
   for 20+ rounds), average, multiply by 0.96, cap at 36.
6. **Sub-zero correction.** If any HC goes negative, anchor the lowest at
   0 and shift everyone else up by the same amount. (Planned future
   change: switch to standard golf conventions and allow negative — i.e.
   "+" — handicaps.)

Course-scaled outputs are `base_HC × crs_ref[N] / 54` for each tee.

## Verifying changes

`golden/` holds the C++ tool's output on `RoundData.dat`, captured at the
time of the Python port. The Python output must remain byte-identical to
this fixture set.

```bash
./verify.sh
```

passes nine `PASS  <file>` lines if nothing has drifted.

## Project layout

```
hc24.py                 the calculator
RoundData.xlsx          the canonical input (current season + history)
RoundData.dat           legacy flat-file export (regression fixture)
verify.sh               regression runner
golden/                 C++ reference outputs from RoundData.dat
old/
  cpp/                  original C++ source + Visual Studio project
  sample_inputs/        per-event xlsx exports the C++ author kept
  sample_outputs/       outputs from old C++ runs (kept for reference)
```

## History

The original handicap tool was a Visual Studio C++ project, manually fed a
tab-separated `RoundData.dat` exported from the spreadsheet each time. This
Python port reproduces that algorithm byte-for-byte (see `golden/`) and
also reads the workbook directly, so the manual export step goes away. The
C++ source is preserved under `old/cpp/` for reference.
