# ODGC Handicap

Disc-golf handicap calculator for the Ottawa Disc Golf Club. Originally a
Visual Studio C++ tool by Ken (Jan 2018); now a Python port backed by a
Cloudflare Worker + Google Apps Script web app.

The original C++ source is preserved under [old/cpp/](old/cpp/) and the
Python port is verified byte-identical against its output (see
[golden/](golden/) and [verify.sh](verify.sh)).

## Live system

| | URL |
| --- | --- |
| Web app (players, courses, doubles) | https://odgc-hc-page.pages.dev |
| Admin / manual ingest | https://odgc-hc-page.pages.dev/admin |
| Worker API | https://odgc-hc.chris-lay9.workers.dev |

### Deploying

```bash
# Worker (Python + wrangler)
cd worker && npx wrangler deploy

# Pages (static HTML — auto-deployed on push to main via CF Pages git integration)
# Or manually:
cd pages && npx wrangler pages deploy . --project-name odgc-hc-page
```

### Auto-ingest

A Cloudflare cron fires daily at **06:00 UTC** (02:00 EDT / 01:00 EST).
It reads the `AutoIngest` tab in the Google Sheet to find configured leagues,
fetches each league's `/schedule` page on UDisc, and ingests any events that
haven't been recorded yet. The tab is bootstrapped automatically on first run.

To trigger manually:

```bash
curl -X POST https://odgc-hc.chris-lay9.workers.dev \
  -H "Content-Type: application/json" \
  -d '{"action":"run_auto_ingest","password":"<shared_password>"}'
```

### Apps Script

`apps_script.gs` in the repo is the source of truth for the Apps Script
deployed to the Google Sheet. After editing, redeploy manually:
**Extensions → Apps Script → Deploy → Manage deployments → pencil → New version → Deploy.**
The deployment URL stays the same; paste it into `gsheets_url.txt` locally.

## Quick start

```bash
# League night: paste in the UDisc URL, get fresh HC files
python3 ingest.py "https://udisc.com/events/.../leaderboard?round=1" \
        --event TOSS05 --year 26

# PDGA tournament: bare event ID is fine
python3 ingest.py 101991 --event LarrimacOpen --year 26

# Just recompute (no new round to ingest)
python3 hc24.py --gsheet
```

Each `ingest.py` run:

1. Pulls the current Sheet state.
2. Matches players (handles diacritics, surname shortenings, common
   nicknames). Auto-adds new players, dedups against rows already in
   the Sheet.
3. Pushes new round row(s) into the Sheet.
4. Runs the handicap algorithm against the freshly-updated Sheet.
5. Drops the 18 output files into the current directory.

Default backend is the Google Sheet via the Apps Script wiring (see
[apps_script.gs](apps_script.gs) and the **Google Sheet setup** section
below). Pass `--xlsx PATH` if you'd rather work against a local
workbook.

`--dry-run` previews everything without modifying the Sheet or running
the recompute. `--skip-recompute` does the ingest only.

## Source types `ingest.py` accepts

| Source | Example | Auto-detected as |
| --- | --- | --- |
| Bare PDGA event ID | `101991` | PDGA |
| PDGA event URL | `https://www.pdga.com/tour/event/101991` | PDGA |
| UDisc leaderboard URL | `https://udisc.com/events/.../leaderboard?round=1` | UDisc |
| UDisc xlsx export | `imports/odgc-toss-2026-05-27.xlsx` | UDisc |

Force one with `--kind pdga` or `--kind udisc` if auto-detection guesses
wrong. The matching/dedup/recompute logic doesn't change.

## Output files

A run produces **eighteen** `*.txt` files in the current directory — nine
under the legacy ODGC convention (lowest HC anchored at 0, no "+"
handicaps) and the same nine with a `_golf` suffix using standard golf
convention (handicaps can be negative, displayed as `+X.X`).

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

## Google Sheet setup (one time, ~5 minutes)

The Sheet wiring uses Google Apps Script as a thin write API — no Google
Cloud Console required.

1. Open the master Sheet → **Extensions → Apps Script**.
2. Paste in the contents of [apps_script.gs](apps_script.gs) (replaces
   the default `Code.gs`).
3. Save (cmd-S). It auto-binds to the parent spreadsheet.
4. **Deploy → New deployment → Type: Web app.**
   - Description: `ODGC HC bot`
   - Execute as: **Me**
   - Who has access: **Anyone**
   Click Deploy. Authorize when prompted (you're authorizing your own
   script to write to your own sheet).
5. Copy the deployment URL (`https://script.google.com/macros/s/.../exec`).
6. Paste it into `gsheets_url.txt` next to `hc24.py`.

That file is in `.gitignore` — treat the URL like a write credential
since anyone with it can write to the sheet.

To verify it's working:

```bash
python3 gsheets.py ping
```

You should see the spreadsheet name and current row/column count.

**Re-deploying after Apps Script changes:** Deploy → Manage deployments
→ pencil edit → Version: New version → Deploy. The URL stays the same.

## Direct script invocation (advanced)

`ingest.py` is just a convenience wrapper. Each underlying script can be
run on its own when you want finer control.

```bash
# Import only (no recompute)
python3 import_udisc.py URL_OR_FILE --event LETS05 --year 26 --gsheet
python3 import_pdga.py  101991      --event LarrimacOpen --year 26 --gsheet

# Recompute only
python3 hc24.py --gsheet                       # Google Sheet
python3 hc24.py --xlsx RoundData.xlsx          # local workbook
python3 hc24.py                                # legacy ./RoundData.dat
```

Useful flags:

| Flag | Where | Effect |
| --- | --- | --- |
| `--force` | importers | write rows even if they look like duplicates |
| `--no-add-players` | importers | skip unmatched players instead of auto-adding |
| `--course CODE` | `import_udisc` (URL mode) | override auto-detected course |
| `--course-override DIV/Rn=code` | `import_pdga` | force course for one (division, round) |
| `--division NAME` | `import_pdga` | limit to specific divisions (repeatable) |
| `--no-merge-same-course` | `import_pdga` | one row per (division × round) instead of merging |
| `--dry-run` | both importers | print the plan, write nothing |
| `--odgc-only` | `hc24` | skip the `_golf` set |
| `--golf-cap K` | `hc24` | tanh asymptote for `+` handicaps (default `5.0`) |
| `--export-dat PATH` | `hc24` | round-trip-debug helper |

Requirements: Python 3.9+, `openpyxl` (only needed for `--xlsx` or
UDisc xlsx imports).

## Input layout (active2025 sheet)

The `active*` worksheets all follow the same layout. Columns A–C hold
row metadata; columns D onward are one column per player.

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

To add a round manually: append a new row, fill in the players who
played (others stay at 0), save. Helper columns to the right of the
roster (e.g. a `count` sum column) are detected and skipped.

## Course codes and layout detection

`COURSE_ID` in [hc24.py](hc24.py) — keeps the C++ 0-indexed order:

```
epw epb epy   eiw eib eiy   unq
lmb lmy   alm0 alm   kan   kpv mtn   cur
shr   upi   kvb kvy kvr   ffw rhl
alb aly alr   cf   ctp   sr sro
```

The importers map human-readable layout names from UDisc/PDGA to these
codes via [`guess_course_from_layout()`](import_udisc.py). 22 layout
strings observed in the wild are tested round-trip; common patterns:

| Layout text | Code |
| --- | --- |
| `Almonte Blues`, `Larrimac Blues`, `Ettyville MVP Blue` | `alb`, `lmb`, `epb` |
| `Ferguson Forest Blues`, `Ferguson Forest Wonderbread` | `kvb` |
| `ORANGE Sandy Row`, `Sandy Row Blue`, `Sandy Row Golf Club` | `sro`, `sr`, `sr` |
| `Larrimac Disc Golf Course - YELLOWS` (PDGA verbose) | `lmy` |
| `Philips Screw Driver DGC` (your `Phillips_Screwdriver`) | `mtn` |

A code that isn't in `COURSE_ID` triggers a stderr warning and falls
back to par-54 reference (`c_fac = 1.0`). The C++ silently divides by
zero on that case, so the warning matters.

## How the algorithm works

A custom variant of the USGA handicap formula. For each round, in
chronological order:

1. **Course difficulty.** `crs_ref[course]` is a rolling average of the
   top-5 raw scores ever shot on that layout. `c_fac = crs_ref/54` is
   the per-course difficulty multiplier. Events prefixed with `x`
   (B-tier) don't contribute to the course reference. The `unq` slot
   (index 7) uses just the current round's value.
2. **Stale-HC reset.** At a year boundary, any player whose last round
   was more than two years ago is reset to three pseudo-differentials
   at their current HC.
3. **Scratch + slope.** Adjusted score per player is
   `raw - hc * c_fac`. Outliers ≥ 1.4σ above the mean are dropped. The
   surviving mean is the round's scratch score. Slope comes from a
   least-squares regression of `(score - scratch)` vs HC, normalized
   to 113 and clamped to `[95, 165]`.
4. **Differential.** `diff = (raw - scratch) × 113 / slope / c_fac`.
5. **Updated HC.** Sort the player's most recent ≤20 differentials,
   take the lowest *N* (sliding scale: 1 for 3 rounds, up to 10 for
   20+ rounds), average, multiply by 0.96, cap at 36.
6. **Sub-zero correction (ODGC mode only).** If any HC goes negative,
   the lowest is anchored at 0 and every player's HC + diffs shift up
   by the same amount. The `_golf` outputs skip this step entirely.

Rounds with fewer than two players holding established HCs are skipped
(the round-scratch and stddev calc need at least two samples).

Course-scaled outputs are `base_HC × crs_ref[N] / 54` for each tee.

## ODGC vs. golf — two output sets

Both sets come out of one run. They differ only in the post-processing
of HC.

| | ODGC (`*.txt`) | Golf (`*_golf.txt`) |
| --- | --- | --- |
| Sub-zero behavior | Anchor lowest HC at 0, shift others up | Allow negative HCs |
| Display | `0.00`, `1.23`, …, `36.00` | `+4.71`, `0.83`, `5.45`, …, `36.00` |
| `+` handicap compression | n/a | tanh soft-cap at `+K` (default `K=5`) |
| Use case | What the league has used for years | Standard golf convention; what new players expect |

### Why the golf side has compression

Disc-golf scoring volatility (one bad hole can be a +4) makes the
natural handicap formula produce eye-catching `+9` and `+10` numbers
for top players. That overstates the actual consistent skill gap.

The compression applies only to negative HCs:

```
hc_display = -K × tanh(|hc| / K)         if hc < 0
hc_display = hc                          if hc >= 0
```

With `K=5`:
- `+1` natural → `+0.99` displayed (untouched)
- `+4` natural → `+3.32` displayed (mild)
- `+8` natural → `+4.61` displayed (strong)
- `+12` natural → `+4.92` displayed (asymptotic; never reaches +5)

No hard ceiling — the function approaches `+K` but never reaches it.
High-handicap players are never affected.

Compression is a display layer; round-to-round HC calculation always
uses the natural value, so fairness and dynamics aren't touched.
`--golf-cap 0` disables. `--golf-cap 4` tightens to `+4`. `--golf-cap 6`
loosens.

### Why the two modes can rank players differently

The ODGC anchoring isn't a flat shift. Each time a player drops below
zero, the algorithm zeroes out their `numcz` most-recent diffs and
adjusts every other player's stored diffs. That permanently bakes the
shift into all subsequent rounds — even after old rounds roll off the
20-round window, the system stays in the shifted state because each
round's scratch is computed from currently-anchored HCs.

In practice, the rank orderings differ by at most a couple of swaps
near the top. Within each list, ranks are stable across runs.

## Import details

### Player matching cascade

Each imported name is mapped to a roster entry through:

1. Exact match after `Last_First` flip
2. Same with diacritics stripped (`Melançon` → `Melancon`)
3. Case-insensitive
4. Unique-surname **and** first-name initial match (so `Amber Correia`
   doesn't get auto-mapped to a roster `Correia_Justin`)
5. First-name shortening (`Christopher` → `Chris`, `Maxime` → `Max`)
6. Fuzzy match (`difflib`, ≥0.75 similarity)

Players that don't match are added to the roster automatically as new
columns (with `-1` seed HC, `100` seed-diff sentinels, all membership
flags `0`). Pass `--no-add-players` to skip them and warn instead.

### Dedup

Before writing any new round row, the importer scans existing rows
with the same year for matching player-score overlap. **3+ identical
(player_column, score) pairs** → flagged as a duplicate, skipped. This
catches re-imports even when event names diverge (manual `LariOpenR1y`
vs scripted `LarrimacOpen_R1`) or course codes disagree (`sro` vs `sr`).
`--force` overrides.

### PDGA merge-same-course

Two PDGA divisions playing the same round on the same layout get
merged into one row in the active sheet — keeps single-player
divisions from hitting the round-size guard in `hc24.py`. Disable
with `--no-merge-same-course` if you want one row per division
× round.

## Backends side-by-side

| | Google Sheet (`--gsheet`) | Local xlsx (`--xlsx PATH`) | Legacy .dat |
| --- | --- | --- | --- |
| Source of truth | yes (default) | optional | regression fixture only |
| Setup needed | Apps Script web app once | none | none |
| Reads from | Sheets API via Apps Script | openpyxl | text parser |
| Writes back | yes (via append_rows / add_player) | yes (saves the workbook) | n/a |
| Speed per round-trip | 3–5 sec | ~1 sec | ~1 sec |
| Offline | no | yes | yes |

The Google Sheet workflow is preferred because it eliminates the
manual "export xlsx → run script → re-upload" loop and gives everyone
collaborating on the Sheet the same view of current data.

## Differences from the C++ source

The Python port is **byte-identical** to the C++ output on the same
`.dat` input (proven by [verify.sh](verify.sh) against
[golden/](golden/), captured from the latest C++ binary). Differences
below are extras the Python adds to support workflows the C++ doesn't
have, not changes to the core algorithm.

### Extras on top of the original algorithm

1. **Google Sheet I/O.** `--gsheet` reads and writes the master Sheet
   directly via Apps Script. No manual xlsx export step.
2. **xlsx I/O.** `--xlsx RoundData.xlsx` reads the spreadsheet
   directly. Older workflow, still supported.
3. **Golf-style output set.** Every legacy output also produced with
   `_golf` suffix using standard golf "+" handicap conventions
   (sub-zero correction skipped; HCs can be negative).
4. **Tanh `+` handicap compression.** Soft-caps the golf side at `+K`
   (default 5) to handle disc-golf's score volatility without a hard
   ceiling. Display-only.
5. **UDisc league import** (`import_udisc.py`). xlsx download or
   leaderboard URL. Matches names, detects division → tee, dedups,
   appends round rows.
6. **PDGA tournament import** (`import_pdga.py`). Event ID or URL.
   Per-(division, round) parsing with same-course merging and a
   layout → code lookup that handles both UDisc's compact phrasing and
   PDGA's verbose strings.
7. **One-command flow** (`ingest.py`). URL → import → recompute in a
   single invocation with auto-detection of the source kind.

### Implementation notes worth flagging

- **Helper-column detection.** The parser stops at the first roster
  column whose row-1 label is `count`/`total`/`sum`/etc., so right-edge
  sum columns don't get parsed as fake players.
- **`has_hc[j]` flag.** The C++ uses `hc[j] > -0.9` as the "has an
  established HC" check, which works in ODGC mode (HCs ≥ 0) but
  excludes scratch players in golf mode (real HC of `-1.5` fails the
  check). The Python tracks `has_hc[j]` explicitly so golf mode
  doesn't drop top players from the round pool. ODGC mode is
  unaffected.

### Robustness note (still relevant to the new C++)

When a round uses a course code not in `COURSE_ID`, the C++ sets
`i_c = 0`, computes `c_fac = crs_ref[0] / 54 = 0`, then divides by it
→ every subsequent round inherits `±inf`/`NaN` and the algorithm
cascades to garbage (final HCs all cap at 36). Adding `sr` and `sro`
to the new C++ fixed the immediate symptom on the current data, but
the same trap fires whenever a new course code appears before it's
added.

The Python guards `c_fac = 1.0` when no course matches and prints a
stderr warning so the operator notices.

### Upstream changes synced in May 2026

Cross-checked against the May 28, 2026 C++ snapshot. Five behavioral
changes brought into the Python:

- Added `sr` (Sandy Row) at course index 28, `sro` (alt layout) at 29.
- `num_crs` bumped 28 → 30.
- `atosHC.txt` gained a `Sandy_Row` column (`crs_ref[28]`).
- `evHC.txt` qualification widened from `EV || ODGC` to
  `EV || ODGC || TOSS`.
- Course-catalog `cnm[]` gained `"Sandy_Row"` but `nnm` wasn't bumped
  to match — Python matches the C++ exactly (entry sits unused in the
  array; no new row in `odgccaCH.txt` catalog). One-line fix on either
  side if intent was to display it.

### Other observations from the read-through

- The `i_zfc > 55` branch in the sub-zero handler
  ([hc24.cpp](old/cpp/hc24.cpp)) appears to never fire — `i_zfc` is
  per-round and bounded by the `ss_id[10]` array size. The Python
  omits it on the assumption it was dead code.
- The `r == 204` multi-subzero special case is hard-coded to that one
  round number; effectively dead on any dataset that didn't go through
  that exact sequence. Also omitted.

## Verifying changes

`golden/` holds the C++ tool's output on `RoundData.dat`, captured from
the latest C++ binary. The Python output must remain byte-identical:

```bash
./verify.sh
```

passes nine `PASS  <file>` lines if nothing has drifted.

The `_golf` and `--gsheet`/`--xlsx` paths don't have golden fixtures —
they're new behavior with no C++ reference. Their correctness is
implicit: `verify.sh` proves the algorithm core; the Sheet/xlsx parsers
produce the same token stream as the .dat parser (`hc24 --export-dat`
proves this round-trip).

## Project layout

```
worker/                 Cloudflare Worker (Python, Pyodide runtime)
  src/entry.py          request handler — all actions, ingest flow, auto-ingest
  src/hc_algorithm.py   handicap algorithm (synced from repo root)
  src/hc_matching.py    player-name matching + course code lookup (synced)
  src/hc_parsing.py     UDisc/PDGA HTML parsers (synced)
  src/gsheets_worker.py Apps Script client (worker-side, uses js.fetch)
  src/worker_io.py      fetch_text / post_json shims for Pyodide
  wrangler.toml         worker config + cron trigger

pages/                  Cloudflare Pages (static HTML)
  index.html            HC leaderboard + player lookup
  players.html          player detail (round history, dossier)
  courses.html          all-time top scores per course
  doubles.html          HC-balanced doubles team generator
  admin.html            manual ingest + roster management

hc_algorithm.py         handicap algorithm (source of truth; synced to worker/src/)
hc_matching.py          player-name matching + course code lookup (source of truth)
hc_parsing.py           UDisc/PDGA HTML parsers (source of truth)
hc24.py                 CLI calculator (read .dat, .xlsx, or Sheet; write 18 txt files)
ingest.py               CLI: URL → import → recompute, one command
import_udisc.py         CLI: UDisc xlsx or leaderboard URL → append rounds
import_pdga.py          CLI: PDGA event ID or URL → append rounds
gsheets.py              CLI: Python client for the Apps Script web app

apps_script.gs          Google Apps Script source (deploy manually to the Sheet)
gsheets_url.txt         Apps Script deployment URL (gitignored — write credential)
verify.sh               regression runner: Python output vs golden/ fixtures
tests/                  pytest unit tests for parsers and dedup logic

RoundData.dat           legacy flat-file export (regression fixture only)
RoundData.xlsx          optional local workbook (no longer source of truth)
golden/                 C++ reference outputs from RoundData.dat
imports/                source UDisc/PDGA files retained for audit (gitignored)
out/                    generated txt outputs (gitignored)

old/
  cpp/                  original C++ source + Visual Studio project
  sample_inputs/        per-event xlsx exports kept for historical reference
  sample_outputs/       outputs from old C++ runs
```

## History

**January 2018** — Ken writes the original Visual Studio C++ tool,
manually fed a tab-separated `RoundData.dat` exported from the
spreadsheet each time.

**May 2026** — Port to Python. `verify.sh` proves byte-identical
reproduction. Added direct xlsx reading, golf-style output set, tanh
compression, UDisc league import. Synced upstream changes from Ken's
latest C++.

**May 2026, week 2** — Added PDGA tournament ingestion, dedup
protection, the same-course merge for multi-division events. Updated
the UDisc layout lookup against every event in the 2025–26 ODGC TOSS
schedule so course codes round-trip cleanly.

**May 2026, week 3** — Google Sheet integration via Apps Script web
app. The Sheet becomes the source of truth; the manual xlsx export
loop goes away. `ingest.py` collapses the URL → import → recompute
sequence into one command.

**June 2026** — Cloudflare Worker + Pages web app. Player lookup,
course leaderboards, doubles team generator, admin ingest UI. Daily
cron auto-ingests new UDisc league events (LETS, Almonte, TOSS, KDGC Tags)
from configured league schedule URLs without manual intervention.
