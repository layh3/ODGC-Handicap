# Roadmap

Working doc. Order is rough priority, not a deadline. Edit freely.

---

## 1. Player lookup page

Anyone can type a name and see their own situation:

- **Last 20 rounds** in a table: year, event, course, score, computed diff.
- **Which are counting** — the best-N diffs (sliding scale, 10 of last 20 in the steady state) highlighted, with the math underneath showing `0.96 × avg = HC`.
- **What it would take to move** — "play a -3.5 or better at any course to displace your 10th-best", or "your -5.46 from round 66 ages out at round 86, +14 plays from now". Already done this analysis for one comparison, can be a 1-line per-player insight.
- **Per-course HC** — same table as the club tabs, but just that player's row, all courses laid out.
- **Membership flags** — which clubs they're in (ODGC, KV, EV, Ladies).

Also on this page:
- **HC trend line** over the last ~50 rounds.
- **"How you compare"** — your rank in each club tab.
- **Head-to-head**: pick another player, see the diff/HC side-by-side over time (e.g. Chris vs Jacob).
- **Public share link** — copy a read-only URL for a specific player; anyone with the link can view that page without the admin password.

Build: new worker action `lookup_player(name)` returns a JSON dossier; new page route or modal renders it. Reuses `compute_handicaps` results — basically the same instrumented run done in chat for Chris vs Jacob, surfaced.

---

## 2. Admin membership management

Logged-in admins (same password gate) can edit a player's club flags. Add/remove someone from ODGC, KV, EV, Ladies. Also add a brand-new player to the roster.

Today this requires editing rows 10-13 of `active2025` directly in the sheet. Friction.

Build:
- Worker action `set_membership(name, flags)` → Apps Script writes the cell.
- Worker action `add_player_to_roster(name)` (already exists; just needs UI surface).
- Worker action `set_player_name(old_name, new_name)` for fixing typos.
- Page: admin sub-page (or expandable section) with a player picker and 4 toggles.

Apps Script needs a `set_cells` or `set_membership` action — small addition to `apps_script.gs`.

---

## 3. Course leaderboards

Per-course best-round table — independent of HC, just a "who's thrown the lowest at each course" view. Probably its own sheet tab (or tabs, one per course family) plus a page section. Cheap because the round data already lives in the sheet; just sort by score per course code.

---

## 4. Repo cleanup

Current state has accumulated some lint:

- **Generated txt files in repo root** — `alphHC.txt`, `atosHC.txt`, `evHC.txt`, `kvHC.txt`, `ladiesHC.txt`, `odgcHC.txt`, `odgccaCH.txt`, `rankHC.txt`, `player_rounds.txt` etc. All gitignored, but they clutter the working dir. Move CLI to write into `out/` by default.
- **CLI scripts duplicated by the worker** — `import_udisc.py`, `import_pdga.py`, `ingest.py` were the original entry points; now the worker covers the same ground. Decide: keep them as the local-dev fallback (they exercise the same shared modules, so they're cheap to maintain), or fold into a thinner `cli.py`.
- **Original C++ source** — was kept for reference during the port. Could move to an `archive/` folder or drop entirely if we're confident the Python is the source of truth.
- **README is stale** — predates the worker + page + Apps Script setup; doesn't mention the live URLs or how to deploy.
- **No real test suite** — `verify.sh` diffs against golden fixtures (great), but nothing exercises the worker code or the new parsers. A `tests/` dir with a few pytest cases (UDisc mixed-tee parser, dedup logic) would prevent regressions.
- **Apps Script versioning** — `apps_script.gs` lives in the repo, but the deployed version is only synced manually. Worth a `scripts/deploy_apps_script.sh` or a note in the README.

---

## Parking lot

Considered and parked (not skipped — but not on the active list).

- CSV export of the HC tabs — not needed; sheet view covers it.
- Worker rate-limit — not needed; password gate is sufficient protection.
