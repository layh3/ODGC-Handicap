#!/usr/bin/env python3
"""Import a UDisc league round into RoundData.xlsx.

Accepts either:
  * an xlsx exported from the UDisc app (one sheet per pool/division), or
  * a UDisc leaderboard URL (e.g. https://udisc.com/events/.../leaderboard?round=1&view=scores)

Workflow:
  1. Read scores (from xlsx sheets or by scraping the URL)
  2. Map division/layout → a course code (GOLD=lmy, BLUE=lmb by default)
  3. Match each player against the active2025 roster (handles accents,
     surname-only matches, common first-name shortenings)
  4. Append one new round row per pool into active2025
  5. Save the workbook (a `.bak` backup is created on first run)

Unmatched players are added to the roster as new columns by default; pass
`--no-add-players` to fall back to the old "skip and warn" behavior.
Re-run hc24.py after to recompute handicaps.

Usage:
    python3 import_udisc.py FILE_OR_URL --event LETS04 --year 26 [--dry-run]
"""

from __future__ import annotations

import argparse
import html
import re
import shutil
import sys
import urllib.request
from pathlib import Path

from openpyxl import load_workbook

# Player matching + course-code lookup live in hc_matching so the
# Cloudflare Worker shares them with the CLI.
from hc_matching import (
    FIRST_NAME_ALIASES,
    strip_accents,
    to_lastname_first,
    match_player,
    guess_course_from_layout,
)


# Map UDisc division name (xlsx mode) → course code in RoundData.xlsx.
# Edit if the league uses different division names.
DIVISION_TO_COURSE = {
    "GOLD": "lmy",   # Larrimac Yellow tees
    "BLUE": "lmb",   # Larrimac Blue tees
}

# (No flat lookup table — guess_course_from_layout() below does context-aware
# matching that handles both UDisc's compact phrasing ("Almonte Blues")
# and PDGA's verbose layout strings ("Larrimac Disc Golf Course - YELLOWS").)

# match_player, strip_accents, to_lastname_first, FIRST_NAME_ALIASES are
# imported from hc_matching (shared with the Cloudflare Worker).


def load_roster(ws) -> list[tuple[int, str]]:
    """Return [(col_index, player_name), ...] from row 1 of active2025.

    Stops at the first None or known helper-column label ('count', 'total')."""
    HELPERS = {"count", "total", "sum", "tally", "n", "#"}
    roster = []
    for c in range(4, ws.max_column + 1):
        v = ws.cell(row=1, column=c).value
        if v is None:
            break
        s = str(v).strip()
        if s.lower() in HELPERS:
            break
        roster.append((c, s))
    return roster


def next_empty_row(ws, start_row: int = 14) -> int:
    """Return the row number of the first empty round row in col A."""
    r = start_row
    while ws.cell(row=r, column=1).value is not None:
        r += 1
    return r


def find_duplicate_row(ws, year: int, candidate_scores: dict, *,
                       min_matches: int = 3) -> tuple | None:
    """Look for an existing row in `ws` that already records this round.

    Two rows represent the same round when, for the same year, enough of
    the per-player scores match exactly. We require ≥ ``min_matches``
    identical (player_column, score) pairs — this catches re-imports even
    when event names and course codes diverge (manual `LariOpenR1y` /
    `lmy` vs scripted `LarrimacOpen_R1` / `lmy`, or `sro` vs `sr`).

    Returns ``(row_num, n_matches, n_in_candidate, event, course)`` for
    the best-matching existing row, or ``None`` if no row hits the
    threshold.
    """
    if not candidate_scores:
        return None

    best: tuple | None = None
    for r in range(14, ws.max_row + 1):
        existing_year = ws.cell(row=r, column=1).value
        if existing_year is None:
            break
        try:
            if int(existing_year) != year:
                continue
        except (TypeError, ValueError):
            continue

        n_matches = 0
        for col, score in candidate_scores.items():
            existing = ws.cell(row=r, column=col).value
            if existing in (None, 0, "0"):
                continue
            try:
                if int(existing) == score:
                    n_matches += 1
            except (TypeError, ValueError):
                continue

        if n_matches >= min_matches and (best is None or n_matches > best[1]):
            event = ws.cell(row=r, column=2).value
            course = ws.cell(row=r, column=3).value
            best = (r, n_matches, len(candidate_scores), event, course)

    return best


def add_new_player(ws, name: str, last_player_col: int):
    """Append a new player column right after the existing roster.

    Writes the name in row 1, '-1' seed HC in row 2, '100' (no-data sentinels)
    in the 7 seed-differential rows (3-9), and '0' membership flags in rows
    10-13. The roster's count/total helper column (if any) is left where it
    is — the operator can manually re-extend its SUM range later.

    Returns the column index of the new player.
    """
    new_col = last_player_col + 1
    # If there's something at new_col (e.g. a 'count' helper), bump it right
    # by inserting a column. openpyxl's insert_cols preserves cell values and
    # adjusts ranges in formulas where possible.
    if ws.cell(row=1, column=new_col).value is not None:
        ws.insert_cols(new_col)
    ws.cell(row=1, column=new_col, value=name)
    ws.cell(row=2, column=new_col, value=-1)     # seed HC sentinel
    for r in range(3, 10):                       # 7 seed differential rows
        ws.cell(row=r, column=new_col, value=100)
    for r in range(10, 14):                      # membership flags
        ws.cell(row=r, column=new_col, value=0)
    return new_col


def read_udisc_pool(ws) -> tuple[str, list[tuple[str, int]]]:
    """Return (division_name, [(player_name, round_total_score), ...])."""
    div = ws.cell(row=2, column=1).value
    rows = []
    for r in range(2, ws.max_row + 1):
        name = ws.cell(row=r, column=4).value
        score = ws.cell(row=r, column=10).value  # round_total_score
        if name is None or score is None:
            continue
        rows.append((str(name).strip(), int(score)))
    return str(div).strip(), rows


def fetch_udisc_url(url: str):
    """Scrape a UDisc leaderboard page. Returns (layout_text, players).

    Thin urllib-backed wrapper around hc_parsing.parse_udisc_leaderboard;
    the Cloudflare Worker replaces the fetch with js.fetch and calls the
    shared parser directly."""
    from hc_parsing import parse_udisc_leaderboard, UDISC_USER_AGENT
    req = urllib.request.Request(url, headers={"User-Agent": UDISC_USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        page = resp.read().decode("utf-8", errors="replace")
    return parse_udisc_leaderboard(page)


def _run_gsheet_path(args, pools_to_import):
    """Apps-Script-backed alternative to the xlsx workflow in main().

    Same matching/dedup logic, but reads/writes the Google Sheet via the
    primitives in gsheets.py. Round trips:
        1. one `pull` at the start (reads the entire tab)
        2. local matching/dedup against the pulled snapshot
        3. one `add_player` per new roster column (zero in the steady state)
        4. one `append_rows` containing all surviving round rows

    Total time on a typical import: 3-5 seconds.
    """
    import gsheets

    url = args.gsheet
    if url == "auto":
        url = gsheets.load_url()

    print(f"Pulling current state from Google Sheet…")
    data = gsheets.pull(url, args.sheet)
    roster = gsheets.load_roster_from_data(data)
    roster_names = [n for _, n in roster]
    name_to_col = {n: c for c, n in roster}

    print(f"Master roster: {len(roster_names)} players in {args.sheet!r}")
    print(f"Event: year={args.year}  name={args.event!r}")
    print(f"Source: {args.source}\n")

    # Same pool-by-pool matching loop as the xlsx path; differences are only
    # that add_player is recorded for later (not applied to a live ws) and
    # that find_duplicate_row reads from the pulled `data` array.
    pending_player_inserts: list[tuple[int, str]] = []
    appended: list[dict] = []
    for label, course, pool in pools_to_import:
        print(f"══ {label}  (→ course {course!r}, {len(pool)} players) ══")
        scores_by_col: dict[int, int] = {}
        added: list[tuple] = []
        for udisc_name, score in pool:
            roster_name, why = match_player(udisc_name, roster_names)
            if roster_name is None:
                if args.no_add_players:
                    print(f"  ?? {udisc_name:<32}   skipped (score={score}, {why})")
                    continue
                roster_name = to_lastname_first(udisc_name)
                last_col = max(c for c, _ in roster)
                new_col = last_col + 1
                pending_player_inserts.append((last_col, roster_name))
                roster.append((new_col, roster_name))
                roster_names.append(roster_name)
                name_to_col[roster_name] = new_col
                added.append((udisc_name, roster_name, score))
                col = new_col
                why = "ADDED to roster"
            else:
                col = name_to_col[roster_name]
            scores_by_col[col] = score
            mark = "++" if why == "ADDED to roster" else "  "
            print(f"  {mark}{udisc_name:<32} → {roster_name:<32} (score={score}, {why})")
        appended.append({
            "course": course,
            "scores": scores_by_col,
            "n_matched": len(scores_by_col) - len(added),
            "n_added": len(added),
        })
        print()

    if not appended:
        sys.exit("nothing to append")

    # Dedup against the pulled snapshot.
    print(f"══ Dedup check ══")
    to_write: list[dict] = []
    for entry in appended:
        dup = gsheets.find_duplicate_row_in_data(data, args.year, entry["scores"])
        if dup is None:
            to_write.append(entry)
            continue
        r_dup, n, total, ev_dup, crs_dup = dup
        if args.force:
            print(f"  WARN  pool with {n}/{total} score matches against row {r_dup} "
                  f"({ev_dup!r}, {crs_dup!r}) — writing anyway because --force")
            to_write.append(entry)
        else:
            print(f"  SKIP  duplicate of row {r_dup} (event {ev_dup!r}, "
                  f"course {crs_dup!r}, {n}/{total} scores match) — pass --force "
                  f"to write anyway")
    print()

    if not to_write and not pending_player_inserts:
        print("nothing to write (all candidates flagged as duplicates).")
        return

    print(f"══ Planned writes ══")
    for after_col, name in pending_player_inserts:
        print(f"  add_player {name!r:30s}  at col {after_col + 1}")
    for entry in to_write:
        print(f"  append row  event={args.event!r:14s}  course={entry['course']!r}  "
              f"({entry['n_matched']} matched, {entry['n_added']} new)")

    if args.dry_run:
        print("\n(dry run — Sheet NOT modified)")
        return

    # Push add_player calls first; each one inserts a column and may shift
    # the right edge of the roster. Then build round rows with the final
    # column layout and push them all at once.
    if pending_player_inserts:
        print(f"\n══ Adding {len(pending_player_inserts)} new player(s) to roster ══")
        for after_col, name in pending_player_inserts:
            new_col = gsheets.add_player(url, name, after_col, args.sheet)
            print(f"  + {name!r:30s} at col {new_col}")

    if to_write:
        max_col = max(c for c, _ in roster)
        rows = []
        for entry in to_write:
            row = [0] * max_col
            row[0] = args.year
            row[1] = args.event
            row[2] = entry["course"]
            for col, score in entry["scores"].items():
                row[col - 1] = score
            rows.append(row)
        print(f"\n══ Appending {len(rows)} round row(s) ══")
        result = gsheets.append_rows(url, rows, args.sheet)
        print(f"  written at rows {result['first_row']}-{result['last_row']}")

    print(f"\nNow re-run:  python3 hc24.py --gsheet --sheet {args.sheet}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("source",
                   help="UDisc xlsx file path OR leaderboard URL")
    p.add_argument("--master", type=Path, default=Path("RoundData.xlsx"),
                   help="Master workbook (default: ./RoundData.xlsx)")
    p.add_argument("--gsheet", nargs="?", const="auto", default=None, metavar="URL",
                   help="Write to the Google Sheet via the Apps Script backend "
                        "instead of the local xlsx. With no value, uses "
                        "./gsheets_url.txt.")
    p.add_argument("--sheet", default="active2025",
                   help="Master sheet to append to (default: active2025)")
    p.add_argument("--event", required=True,
                   help='Event name to write into col B (e.g. "LETS04")')
    p.add_argument("--year", type=int, required=True,
                   help='2-digit year for col A (e.g. 26 for 2026)')
    p.add_argument("--division-map", action="append", default=[],
                   help='Override DIVISION_TO_COURSE: --division-map GOLD=lmy')
    p.add_argument("--course", default=None,
                   help='Course code (URL mode only; overrides auto-detection)')
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would be written; do not save the workbook")
    p.add_argument("--no-add-players", action="store_true",
                   help="Skip unmatched players instead of adding them to the roster")
    p.add_argument("--force", action="store_true",
                   help="Write rows even if they look like duplicates of existing ones")
    args = p.parse_args(argv)

    div_map = dict(DIVISION_TO_COURSE)
    for entry in args.division_map:
        k, _, v = entry.partition("=")
        div_map[k.strip()] = v.strip()

    is_url = args.source.startswith(("http://", "https://"))

    # Build a list of (label, course_code, [(name, score), ...]) pools.
    pools_to_import = []
    if is_url:
        layout_text, players = fetch_udisc_url(args.source)
        course = args.course or guess_course_from_layout(layout_text)
        if not course:
            sys.exit(
                f"could not infer course from layout {layout_text!r}; "
                f"pass --course explicitly (e.g. --course lmb)"
            )
        if not players:
            sys.exit(f"no players found at {args.source}")
        pools_to_import.append((layout_text or "url-pool", course, players))
    else:
        udisc_path = Path(args.source)
        if not udisc_path.exists():
            sys.exit(f"file not found: {udisc_path}")
        udisc = load_workbook(udisc_path, data_only=True)
        for sheet_name in udisc.sheetnames:
            ws = udisc[sheet_name]
            division, pool = read_udisc_pool(ws)
            course = div_map.get(division)
            if not course:
                print(f"  SKIP {sheet_name!r}: unknown division {division!r} "
                      f"(map with --division-map {division}=<code>)")
                continue
            pools_to_import.append((f"{sheet_name} [{division}]", course, pool))

    if args.gsheet is not None:
        return _run_gsheet_path(args, pools_to_import)

    master = load_workbook(args.master, data_only=False)
    if args.sheet not in master.sheetnames:
        sys.exit(f"sheet {args.sheet!r} not in {args.master}")
    ms = master[args.sheet]
    roster = load_roster(ms)
    roster_names = [n for _, n in roster]
    name_to_col = {n: c for c, n in roster}

    print(f"Master roster: {len(roster_names)} players in {args.sheet!r}")
    print(f"Event: year={args.year}  name={args.event!r}")
    print(f"Source: {args.source}")
    print()

    appended = []
    for label, course, pool in pools_to_import:
        print(f"══ {label}  (→ course {course!r}, {len(pool)} players) ══")
        scores_by_col: dict[int, int] = {}
        added = []     # (display_name, roster_name, score) for newly-created columns
        for udisc_name, score in pool:
            roster_name, why = match_player(udisc_name, roster_names)
            if roster_name is None:
                if args.no_add_players:
                    print(f"  ?? {udisc_name:<32}   skipped (score={score}, {why})")
                    continue
                # Convert "Jacob Mainville" → "Mainville_Jacob"; if it's a
                # single-token name (no surname), use it as-is.
                roster_name = to_lastname_first(udisc_name)
                last_col = max(c for c, _ in roster)
                if not args.dry_run:
                    new_col = add_new_player(ms, roster_name, last_col)
                else:
                    new_col = last_col + 1
                roster.append((new_col, roster_name))
                roster_names.append(roster_name)
                name_to_col[roster_name] = new_col
                added.append((udisc_name, roster_name, score))
                col = new_col
                why = "ADDED to roster"
            else:
                col = name_to_col[roster_name]
            scores_by_col[col] = score
            mark = "++" if why == "ADDED to roster" else "  "
            print(f"  {mark}{udisc_name:<32} → {roster_name:<32} (score={score}, {why})")

        appended.append({
            "course": course,
            "scores": scores_by_col,
            "n_matched": len(scores_by_col) - len(added),
            "n_added": len(added),
        })
        print()

    if not appended:
        sys.exit("nothing to append")

    # Dedup check: skip any candidate that looks like a re-import of an
    # existing row. Honors --force to write anyway.
    to_write = []
    for entry in appended:
        dup = find_duplicate_row(ms, args.year, entry["scores"])
        if dup is not None:
            r_dup, n, total, ev_dup, crs_dup = dup
            if args.force:
                print(f"  WARN  pool with {n}/{total} score matches against existing "
                      f"row {r_dup} ({ev_dup!r}, course {crs_dup!r}) — writing anyway "
                      f"because of --force")
                to_write.append(entry)
            else:
                print(f"  SKIP duplicate of row {r_dup} "
                      f"(event {ev_dup!r}, course {crs_dup!r}, "
                      f"{n}/{total} scores match) — pass --force to write anyway")
                continue
        else:
            to_write.append(entry)

    if not to_write:
        print("\nnothing to write (all candidates flagged as duplicates).")
        return

    target_row = next_empty_row(ms)
    print(f"══ Writes ══")
    for i, entry in enumerate(to_write):
        r = target_row + i
        print(f"  row {r}: year={args.year}  event={args.event!r}  course={entry['course']!r}"
              f"  ({entry['n_matched']} matched, {entry['n_added']} new players added)")
        if args.dry_run:
            continue
        ms.cell(row=r, column=1, value=args.year)
        ms.cell(row=r, column=2, value=args.event)
        ms.cell(row=r, column=3, value=entry["course"])
        for col_idx, _name in roster:
            sc = entry["scores"].get(col_idx, 0)
            ms.cell(row=r, column=col_idx, value=sc)

    if args.dry_run:
        print("\n(dry run — workbook NOT modified)")
        return

    # Safety backup
    bak = args.master.with_suffix(args.master.suffix + ".bak")
    if not bak.exists():
        shutil.copy(args.master, bak)
        print(f"\nbackup → {bak}")

    master.save(args.master)
    print(f"saved   → {args.master}")
    print(f"\nNow re-run:  python3 hc24.py --xlsx {args.master} --sheet {args.sheet}")


if __name__ == "__main__":
    main()
