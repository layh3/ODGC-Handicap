# Build plan — net results, recaps, courses, doubles, auto-ingest, cleanup

Detailed enough to execute unattended. Phases are ordered by dependency:
0 → 1 → 2 are sequential; 3 and 4 are independent of each other (both need 0);
5 builds on the ingest refactor in 1–2; 6 is last.

**Ground rules for every phase**

- `./verify.sh` must pass before every commit (golden byte-parity with the C++).
- Worker deploy: `cd worker && make deploy` (Makefile syncs the shared modules first).
- Pages deploy: `cd pages && wrangler pages deploy . --project-name=odgc-hc-page --commit-dirty=true`.
- Smoke-test live endpoints with `curl -X POST https://odgc-hc.chris-lay9.workers.dev -H "Content-Type: application/json" -d '...'` after each worker deploy.
- Commit + push at the end of each phase (one commit per phase, or two if a bugfix lands separately).
- **No Apps Script changes in any phase.** Everything here works through the
  existing actions (`pull`, `append_rows`, `replace_sheet`). Apps Script
  redeploys are manual-only and we avoid needing one.
- New sheet tabs created via `replace_sheet` (it creates the tab if missing).
- Style for any new page/card: copy the theme tokens + card/table/typeahead CSS
  from `pages/players.html`. Dark bg, lime `--accent: #84e1bc`, glass cards,
  Inter + JetBrains Mono. Every page gets the shared `nav.tabs` block.

---

## Phase 0 — algorithm groundwork: record HC-entering-the-round

Net scoring needs each player's HC *as it stood when they teed off*, plus the
course factor used that round. The algorithm already computes both (`hc0[]`,
`c_fac`); we just record them.

**`hc_algorithm.py`** (root; worker copy is synced by the Makefile):

1. Next to the existing `played_at` init, add:
   ```python
   hc_entering = [[0.0] * 600 for _ in range(i_pl + 2)]   # hc0 at tee-off, per slot
   est_entering = [[False] * 600 for _ in range(i_pl + 2)] # had an established HC?
   round_c_fac = [0.0] * n_rounds_cap                      # c_fac used per round r
   ```
2. In the main round loop, right after `c_fac` / `oc_fac` are computed, add
   `round_c_fac[r] = c_fac`.
3. In the **first** participant loop (`for j in ...: sc = score[r][j]; if sc > 0:`),
   immediately after `rnd_count[j] += 1`, add:
   ```python
   hc_entering[j][rnd_count[j]] = hc0[j]
   est_entering[j][rnd_count[j]] = has_hc[j]
   ```
   Note `hc0[j]` is frozen at round start so ordering inside the loop is safe.
   Wait — `hc0` is copied *before* this loop (the `for j ...: hc0[j] = hc[j]`
   block); confirm the recording lines come after that copy.
4. Add `"hc_entering"`, `"est_entering"`, `"round_c_fac"` to the return dict
   (comment: lookup/net-results only, never read by the algorithm itself).

**Verification:** `./verify.sh` → all PASS (only added keys, no output change).

Commit: `hc_algorithm: record per-slot HC-entering and per-round c_fac`.

---

## Phase 1 — net results after every ingest

The point of handicaps: net score = gross − HC×course_factor. Show the net
leaderboard for each ingested round, push it to a Results tab, and expose an
on-demand action for past events.

### 1a. Shared compute helper in the worker

`worker/src/entry.py` currently pulls + tokenizes + computes in both
`_run_ingest` and `_run_lookup`. Factor:

```python
async def _pull_and_compute(apps_url, sheet):
    data = await gs.pull(apps_url, sheet)
    player_arr, i_pl, tokens = _data_to_tokens(data)
    res_odgc = compute_handicaps(..., anchor_at_zero=True, verbose=False)
    res_golf = compute_handicaps(..., anchor_at_zero=False, verbose=False)
    return data, res_odgc, res_golf
```
Update `_run_lookup` to use it. (`_run_ingest` keeps its own flow since it
pulls twice — before and after appending.)

### 1b. Net-results builder

New function in `worker/src/entry.py`:

```python
def _build_net_results(res, round_idx):
    """Net leaderboard for round r: [{rank, name, gross, hc, net, is_new}]."""
```
- For each player `j` with `score[round_idx][j] > 0`:
  find their slot `k` where `res["played_at"][j][k] == round_idx`
  (walk `k` from `rnd_count[j]` downward; it's near the end).
  - `gross = score[round_idx][j]`
  - `hc_in = res["hc_entering"][j][k]`, `est = res["est_entering"][j][k]`
  - `c_fac = res["round_c_fac"][round_idx]`
  - established: `net = gross - hc_in * c_fac`
  - not established (`est == False`): `net = None`, `is_new = True` — list
    them at the bottom, unranked (they have no HC yet; ranking them on gross
    would be wrong).
  - If a player's slot can't be found (round was skipped by the <2-established
    check), return an empty list — the caller logs "net results unavailable".
- Sort established ascending by net; ties share a rank (1,2,2,4).
- Round display values: net to 1 decimal, hc to 1 decimal.

Finding `round_idx` for an ingested pool: after the post-append recompute,
scan `r` from `res["i_rc"]` downward for
`event[r] == pool_event_name and course[r] == pool_course and ry[r] == year`;
take the first hit (the newest).

### 1c. Wire into `_run_ingest`

After the HC tabs are pushed, for each pool that was actually appended (not
dedup-skipped):

- compute net results, append log lines:
  ```
  net results — Lets02_lmb @ lmb:
    1. Arch_Jerry  net 49.3  (64 − 14.7)
    ...
    NEW (no HC yet): Walker_Glenn 65
  ```
- add to the return dict: `"net_results": [{event, course, players: [...]}, ...]`.

Push a **"Results" sheet tab** (replace_sheet, freeze_rows=2): title row
("Latest results — generated <stamp>"), blank, then per pool: a header row
(event/course), column header `Rank | Player | Gross | HC | Net`, rows, blank.
The tab always shows only the most recent ingest (history lives in the data).

### 1d. Public `event_results` action

In `on_fetch`, alongside `lookup`/`roster` (public, no password):

```json
{"action": "event_results", "event": "Lets02_lmb", "year": 26}
```
- `_pull_and_compute`, find **all** rounds with that event name (and year if
  given), return `{ok, results: [{event, course, year, players: [...]}]}`.
- 404-style error if no round matches.

### 1e. Frontend — results card on the ingest page

`pages/index.html`: new card `id="results-panel"` (hidden by default) between
the Output card and Recent. After a successful ingest where
`result.net_results` is non-empty, render one table per pool (same
`rounds-table` styling as players.html — copy the CSS block). Counted/winner
row gets the accent highlight. New players shown dimmed with "NEW" badge.

**Verification:**
- `./verify.sh` passes.
- Deploy worker; `curl` `event_results` for a known past event (e.g.
  `{"action":"event_results","event":"Lets02_lmb"}`) and eyeball the net math
  against the dossier HCs.
- Deploy pages.

Commit: `Net results — per-round net leaderboard on ingest + Results tab + event_results action`.

---

## Phase 2 — event recap blurb

Paste-ready group-chat summary returned with every ingest.

### 2a. Pre/post HC delta

`_run_ingest` already pulls `data` (pre-state) at the start. Before appending
rows, tokenize the PRE data and compute ODGC handicaps once:
`res_before = compute_handicaps(...)` → build `{name: hc}` for qualified
players. After the post-append recompute (`res_odgc`), build the same map.
Movers = players **in the ingested pools** with `|after − before| ≥ 0.05`,
sorted by |delta| desc, top 5.

(Cost: one extra compute per ingest — fine, it's ~1s.)

### 2b. Personal bests

From the PRE data (before the new rows): for each participant in each
appended pool, their best previous gross at that course code =
min over data rows 14+ where row course == pool course and their column > 0.
If the new gross beats it (or they had no prior round there, skip — first
round isn't a "PB"), record `(name, new, prev)`.

### 2c. Compose the recap

New `_build_recap(pools_appended, net_results, movers, pbs, new_players)`
returning plain text, e.g.:

```
🥏 Lets02 @ Larrimac Blue (lmb) — 7 players
🏆 Net: 1. Arch_Jerry 49.3 · 2. Lay_Chris 50.1 · 3. Gyre_Pier-luc 50.4
📈 HC movers: Lay_Chris 0.44→0.31 (▼0.13) · Harvey_Alan 4.9→5.1 (▲0.2)
🔥 PBs: Gyre_Pier-luc 58 at lmb (prev 60)
👋 First tracked round: Walker_Glenn
Full standings: https://odgc-hc-page.pages.dev/players
```
One block per appended pool. Keep each line short; skip empty sections.

Return as `"recap"` in the ingest result JSON.

### 2d. Frontend

`pages/index.html`: inside the results card from Phase 1, add a recap `<pre>`
with a **Copy** button (`navigator.clipboard.writeText`; flip button label to
"Copied ✓" for 1.5s).

**Verification:** deploy, run a real ingest (or re-run one that fully dedups —
recap should then say nothing was added and the card stays hidden). Check the
copy button in the browser.

Commit: `Event recap — paste-ready summary with net podium, HC movers, PBs`.

---

## Phase 3 — course leaderboards + PB badges

### 3a. Course display names (shared module)

Add to `hc_matching.py` (it's already synced to the worker):

```python
COURSE_NAMES = {
  "epw": "Ettyville MVP White",  "epb": "Ettyville MVP Blue",  "epy": "Ettyville MVP Yellow",
  "eiw": "Ettyville Axiom White","eib": "Ettyville Axiom Blue","eiy": "Ettyville Axiom Yellow",
  "lmb": "Larrimac Blue",  "lmy": "Larrimac Yellow",
  "alm": "Almonte", "alb": "Almonte Blue", "aly": "Almonte Yellow", "alr": "Almonte Red", "alm0": "Almonte (old)",
  "kan": "Kanata",  "mtn": "Mountain", "cur": "Currie",
  "shr": "The Shire", "upi": "UPI", "ffw": "Franktown",
  "kvb": "Ferguson Blue", "kvy": "Ferguson Yellow", "kvr": "Ferguson Red", "kpv": "Kemptville (old)",
  "cf": "Camp Fortune", "rhl": "Rockhill", "ctp": "Centrepointe",
  "sr": "Sandy Row Blue", "sro": "Sandy Row Orange",
  "unq": "One-off layout", "jeu": "(unused)",
}
```
(Verify each guess against `COURSE_ID` comments + `odgccaCH` block in
`hc24.py` during implementation; correct any that are wrong.)

### 3b. Worker action `course_records` (public)

- Pull the sheet once. For every round row (rows 14+), for each player column
  with score > 0, accumulate `(course, player, gross, event, year)`.
- Skip `unq` and any `x`-prefixed event rows (excluded layouts).
- Per course: sort by gross asc, take top 10 (include ties at the cut).
- Return `{ok, records: {code: {name, top: [{player, gross, event, year}]}}}`
  ordered by course name.

### 3c. `/courses` page

New `pages/courses.html` (copy theme from players.html). Nav becomes
`Ingest / Players / Courses / Doubles / Admin` — **update the nav block in all
pages** (doubles link can 404 until Phase 4; or add both nav entries in
Phase 4 — implementer's choice, just end consistent).

- On load, fetch `course_records`, render a card per course: course name,
  top-10 table (`Rank | Player | Score | Event | Yr`). Rank 1 row highlighted.
- A course filter input at the top (client-side, hides non-matching cards).

### 3d. PB badge on the player dossier

In `_build_dossier`: compute the player's best gross per course across all
their rounds (`score[r][j]` grouped by `course[r]`). For each `last_20` entry
whose gross equals their best at that course, add `"pb": true`.
`pages/players.html`: render a small `PB` chip (accent style) next to the
score in those rows.

**Verification:** deploy worker + pages, curl `course_records`, confirm
Larrimac Blue's record looks sane against the sheet. Load `/courses` and
`/players?player=Lay_Chris` (his sro 60 should likely flag PB).

Commit: `Course leaderboards — /courses page, course_records action, PB badges`.

---

## Phase 4 — doubles team generator

### 4a. Worker action `hc_list` (public)

Reuses `_pull_and_compute`. Returns qualified players sorted by HC:
`{ok, players: [{name, hc, hc_golf, rounds}]}` (hc 2dp, golf compressed via
`compress_plus_hc(·, 5.0)` and 2dp with `+` convention).

### 4b. `/doubles` page

New `pages/doubles.html`, nav tab everywhere.

- On load fetch `hc_list` (show a loading state; cache in `localStorage`
  `odgc-hc-hclist` with a timestamp, background-refresh like the roster).
- **Player picker:** typeahead (copy `wireTypeahead` from admin.html) → adds a
  chip to a "Tonight's field" list. Chips show `name (hc)` with an × to
  remove. Count displayed.
- **Pairing method** (radio):
  1. *High–low* (default): sort selected by HC asc; pair best↔worst inward.
  2. *Snake draft*: for team-of-2: seeds 1..N/2 get partners N/2+1..N in
     reverse — equivalent to high-low for pairs; offer team size 2 or 3
     (dropdown). For size 3 use snake order across 3 rounds of picks.
  3. *Balanced shuffle*: random restarts (200 iterations): shuffle, pair
     sequentially, keep the assignment minimizing the spread (max−min team HC).
- Odd player out: last team becomes a triple, marked "(cali — best 2 of 3 or
  local rule)".
- **Output:** team cards: members + each HC + combined HC, plus
  "strokes given vs lowest team" = round(team_HC_sum − min_team_HC_sum).
  A Copy button produces a plain-text version for the group chat.
- All pairing logic is client-side; no password.

**Verification:** deploy pages; curl `hc_list`; load `/doubles`, select ~7
players, generate with each method, confirm odd-count handling.

Commit: `Doubles generator — /doubles page with HC-balanced pairing`.

---

## Phase 5 — scheduled auto-ingest

Goal: weekly league rounds (LETS, TOSS, kvTags…) ingest themselves.

### 5a. Investigation (do first; adjust 5b–5e to findings)

- Fetch a UDisc **league page** with the desktop UA (a LETS league URL is in
  the user's browser history / earlier chat: the events live under
  `https://udisc.com/leagues/<slug>/...`). Inspect the React Router stream
  payload (same `streamController.enqueue` format as event pages — the
  decoder from `_extract_udisc_layouts` generalizes).
- Deliverable: `parse_udisc_league_events(html) -> [{title, url, date}]`
  in `hc_parsing.py`, newest first, where `url` is the event leaderboard URL.
- If league pages turn out to be client-side-only (no event list in the
  payload), fall back: config rows hold the *event* URL and auto-ingest only
  re-checks known URLs for new rounds (`?round=N`). Note whichever reality
  holds in the code comments.

### 5b. Config tab

Sheet tab `AutoIngest`, user-maintained (create it once via `replace_sheet`
with a header + example row, then never replace it again — read-only from
then on):

```
league_url | event_prefix | year | enabled
https://udisc.com/leagues/lets-... | LETS | 26 | 1
```

### 5c. Refactor `_run_ingest` for reuse

Split into:
- `_ingest_pools(apps_url, pools, event, year, sheet, log)` — the
  match/dedup/append part, returns (rows_added, skipped, new_players).
- `_recompute_and_push(apps_url, sheet, log)` — pull, compute both, push HC +
  subset tabs, return (res_odgc, res_golf).
The POST path and the cron path both call these.

### 5d. The scheduled handler

- `worker/wrangler.toml`: add
  ```toml
  [triggers]
  crons = ["0 6 * * *"]   # daily 06:00 UTC ≈ 01:00 Ottawa, after league nights
  ```
- `worker/src/entry.py`: add the Python Workers scheduled hook (verify the
  exact signature against current CF Python Workers docs at implementation
  time — expected `async def on_scheduled(event, env, ctx)`).
- Flow:
  1. Pull `AutoIngest` tab; for each enabled row:
  2. Fetch league page → `parse_udisc_league_events` → take the 3 newest.
  3. For each event: fetch leaderboard, parse pools, run the existing dedup
     check per pool against the data tab. If every pool is a dup → skip.
  4. Event name: extract the number from the title (`LETS #7` →
     `LETS07`); fallback: count existing rows starting with the prefix + 1.
     Mixed-tee events get the `_<course>` suffix automatically (existing
     behavior).
  5. `_ingest_pools` + (if anything added) `_recompute_and_push`.
  6. Append one line per outcome to a `Log` sheet tab via `append_rows`
     (`[iso_timestamp, event, course(s), rows_added, "auto"]`). Create the
     Log tab once via `replace_sheet` with a header if `pull` says it's
     missing (pull error → create).
  7. Per-league try/except: an error logs to the Log tab and continues.

### 5e. Manual trigger for testing

Password-gated action `{"action": "run_auto_ingest", "password": ...}` that
runs the same function and returns the log. The cron handler shares it. (This
is also the workaround for not being able to run `wrangler dev` on this Mac.)

**Verification:** deploy; curl `run_auto_ingest` with the password; confirm
it skips already-ingested events (dedup) and writes the Log tab. Wait a day
(or leave it) for the cron to fire; check Log tab afterwards.

Commit: `Auto-ingest — daily cron polls configured leagues, manual trigger action`.

---

## Phase 6 — repo cleanup

1. **Outputs → `out/`**: `hc24.py` gets `--out-dir` (default `out/`, created
   on demand). `verify.sh` updated to diff `out/` files against `golden/`.
   `.gitignore`: drop the nine root `/…HC*.txt` patterns, keep `/out/`.
   Delete the stray root txt files + `demo_compare/` + `py_out/`.
2. **Archive the C++**: `old/` → `archive/cpp-original/` with a one-line
   README inside ("reference implementation the Python port was verified
   against; see golden/"). `git mv` so history follows. `imports/` (one xlsx
   download) → delete; it's reproducible from UDisc.
3. **Tests**: `tests/` with pytest:
   - `tests/fixtures/lets2.html` (copy from `/tmp/lets2.html` if still there,
     else re-fetch the LETS #2 page with `UDISC_USER_AGENT`).
   - `test_parsing.py`: mixed-tee page → 2 pools (10 Yellow / 7 Blue, spot-check
     two named players); strip the stream payload from a copy → 1 pool
     fallback.
   - `test_matching.py`: `guess_course_from_layout` table-driven cases
     (Larrimac yellow/blue, Sandy Row orange default, Ferguson, Almonte);
     `match_player` cascade: exact, accent, case, surname+initial, fuzzy.
   - `test_gsheets.py`: `find_duplicate_row_in_data` hit/miss/threshold;
     `load_roster_from_data` helper-column stop.
   - `test_algorithm.py`: token-parse `RoundData.dat`, run `compute_handicaps`,
     assert 3–4 known player HCs from `golden/rankHC.txt` (parse golden at
     test time, don't hardcode).
   - Run with `python3 -m pytest tests/ -q` — confirm green.
4. **Root Makefile**: targets `verify`, `test`, `deploy-worker`,
   `deploy-pages`, `deploy` (both).
5. **README rewrite**: what it is (1 para), architecture sketch
   (sheet ⇄ Apps Script ⇄ worker ⇄ pages, CLI on the side), live URLs
   (pages.dev + workers.dev + the Google Sheet), the four pages and what they
   do, deploy commands, Apps Script update procedure (manual redeploy steps),
   the sheet data model (row 1 roster, row 2 seed HC, rows 3–9 seed diffs,
   rows 10–13 club flags, rows 14+ rounds; course codes table from
   `COURSE_NAMES`), dev workflow (`make verify`, `make test`), and the
   worker actions list (public vs password-gated).
6. Update `ROADMAP.md`: mark shipped items (player lookup ✅, admin ✅, plus
   whatever of phases 1–5 are done), keep remaining ideas.

**Verification:** `make verify && make test` green; `git status` clean after
commit; deploys unaffected (no worker/pages changes in this phase except the
Makefile convenience).

Commit: `Repo cleanup — out/ for generated files, pytest suite, archived C++, README rewrite, root Makefile`.

---

## Execution notes for auto mode

- If a live ingest is needed to test Phase 1/2 end-to-end and no new league
  round exists, use `event_results` (1d) against an existing event instead —
  it exercises the same net-math path without writing anything.
- The Apps Script deployment is already at the version with
  `set_membership`/`rename_player` (user confirmed the admin page works).
  Nothing here needs another redeploy; if an Apps Script error like
  "unknown action" ever appears, stop and tell the user instead of editing
  apps_script.gs.
- Worker version IDs and pages preview URLs go in the end-of-phase summary so
  the user can spot-check.
- If `verify.sh` fails at any point: the algorithm change is wrong — fix it
  before proceeding; never update golden/ to match.
