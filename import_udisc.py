#!/usr/bin/env python3
"""Import a UDisc league round export into RoundData.xlsx.

UDisc lets you download a per-round xlsx that has one sheet per pool/division.
This script:
  1. Reads each sheet in the UDisc file
  2. Maps the UDisc division name → a course code (GOLD=lmy, BLUE=lmb by default)
  3. Matches each player against the active2025 roster (handles accents,
     surname-only matches, common first-name shortenings)
  4. Appends one new round row per pool into the active2025 sheet
  5. Saves the workbook (a `.bak` backup is created next to the file)

Players that don't match are skipped (column score stays 0 = did not play).
Re-run hc24.py after to recompute handicaps.

Usage:
    python3 import_udisc.py udisc_export.xlsx \\
        --event LETS04 --year 26 [--dry-run]
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import unicodedata
from difflib import get_close_matches
from pathlib import Path

from openpyxl import load_workbook


# Map UDisc division name → course code in RoundData.xlsx.
# Edit if the league uses different division names.
DIVISION_TO_COURSE = {
    "GOLD": "lmy",   # Larrimac Yellow tees
    "BLUE": "lmb",   # Larrimac Blue tees
}

# Common first-name shortenings the master sheet uses.
FIRST_NAME_ALIASES = {
    "Christopher": "Chris", "Matthew": "Matt", "Jonathan": "Jon",
    "Michael": "Mike", "Robert": "Rob", "William": "Will",
    "Daniel": "Dan", "Nicholas": "Nick", "Andrew": "Andy",
    "Joshua": "Josh", "Anthony": "Tony", "Maximilian": "Max",
    "Maxime": "Max",
}


def strip_accents(s: str) -> str:
    """é → e, ñ → n, ç → c, etc. — for matching only, never for writing."""
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def to_lastname_first(udisc_name: str) -> str:
    """'Jacob Mainville' → 'Mainville_Jacob'. Multi-word last names join with _.

    'Pier-luc Gyre' → 'Gyre_Pier-luc' (hyphens preserved, case preserved).
    """
    parts = udisc_name.strip().split()
    if len(parts) < 2:
        return udisc_name.strip()
    return f"{'_'.join(parts[1:])}_{parts[0]}"


def match_player(udisc_name: str, roster: list[str]) -> tuple[str | None, str]:
    """Return (matched_roster_name, reason) or (None, why_not).

    Matching cascade (highest confidence first):
        1. Exact match after Last_First flip
        2. Same after stripping accents from both sides
        3. Case-insensitive
        4. Unique surname (one Last_* in roster)
        5. First-name shortening (Christopher → Chris, etc.)
        6. Fuzzy (difflib, ≥0.75 similarity)
    """
    candidate = to_lastname_first(udisc_name)

    # 1 — exact
    if candidate in roster:
        return candidate, "exact"

    # 2 — accent-stripped exact
    stripped = {strip_accents(n).lower(): n for n in roster}
    key = strip_accents(candidate).lower()
    if key in stripped:
        return stripped[key], "accent-normalized"

    # 3 — case-insensitive
    ci = {n.lower(): n for n in roster}
    if candidate.lower() in ci:
        return ci[candidate.lower()], "case-insensitive"

    # 4 — unique surname
    last = candidate.split("_")[0]
    last_stripped = strip_accents(last).lower()
    surname_matches = [
        n for n in roster
        if strip_accents(n).lower().startswith(last_stripped + "_")
    ]
    if len(surname_matches) == 1:
        return surname_matches[0], "unique surname"
    if len(surname_matches) > 1:
        return None, f"ambiguous surname → {surname_matches}"

    # 5 — first-name shortening
    parts = udisc_name.strip().split()
    if len(parts) >= 2:
        short = FIRST_NAME_ALIASES.get(parts[0])
        if short:
            alt = f"{'_'.join(parts[1:])}_{short}"
            if alt in roster:
                return alt, f"first-name shortening ({parts[0]}→{short})"

    # 6 — fuzzy
    close = get_close_matches(candidate, roster, n=1, cutoff=0.75)
    if close:
        return close[0], "fuzzy"

    return None, "no match"


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


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("udisc_file", type=Path,
                   help="UDisc league round xlsx export")
    p.add_argument("--master", type=Path, default=Path("RoundData.xlsx"),
                   help="Master workbook (default: ./RoundData.xlsx)")
    p.add_argument("--sheet", default="active2025",
                   help="Master sheet to append to (default: active2025)")
    p.add_argument("--event", required=True,
                   help='Event name to write into col B (e.g. "LETS04")')
    p.add_argument("--year", type=int, required=True,
                   help='2-digit year for col A (e.g. 26 for 2026)')
    p.add_argument("--division-map", action="append", default=[],
                   help='Override DIVISION_TO_COURSE: --division-map GOLD=lmy')
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would be written; do not save the workbook")
    args = p.parse_args(argv)

    div_map = dict(DIVISION_TO_COURSE)
    for entry in args.division_map:
        k, _, v = entry.partition("=")
        div_map[k.strip()] = v.strip()

    udisc = load_workbook(args.udisc_file, data_only=True)
    master = load_workbook(args.master, data_only=False)
    if args.sheet not in master.sheetnames:
        sys.exit(f"sheet {args.sheet!r} not in {args.master}")
    ms = master[args.sheet]
    roster = load_roster(ms)
    roster_names = [n for _, n in roster]
    name_to_col = {n: c for c, n in roster}

    print(f"Master roster: {len(roster_names)} players in {args.sheet!r}")
    print(f"Event: year={args.year}  name={args.event!r}")
    print()

    appended = []
    for sheet_name in udisc.sheetnames:
        ws = udisc[sheet_name]
        division, pool = read_udisc_pool(ws)
        course = div_map.get(division)
        if not course:
            print(f"  SKIP {sheet_name!r}: unknown division {division!r} "
                  f"(map with --division-map {division}=<code>)")
            continue

        print(f"══ {sheet_name}  ({division} → {course}, {len(pool)} players) ══")
        scores_by_col: dict[int, int] = {}
        unmatched = []
        for udisc_name, score in pool:
            roster_name, why = match_player(udisc_name, roster_names)
            if roster_name is None:
                unmatched.append((udisc_name, score, why))
                continue
            col = name_to_col[roster_name]
            scores_by_col[col] = score
            tag = "  " if why == "exact" else "  "
            print(f"  {tag}{udisc_name:<32} → {roster_name:<32} (score={score}, {why})")

        for udisc_name, score, why in unmatched:
            print(f"  ?? {udisc_name:<32}   skipped (score={score}, {why})")

        appended.append({
            "course": course,
            "scores": scores_by_col,
            "n_matched": len(scores_by_col),
            "n_skipped": len(unmatched),
        })
        print()

    if not appended:
        sys.exit("nothing to append")

    target_row = next_empty_row(ms)
    print(f"══ Writes ══")
    for i, entry in enumerate(appended):
        r = target_row + i
        print(f"  row {r}: year={args.year}  event={args.event!r}  course={entry['course']!r}"
              f"  ({entry['n_matched']} scores written, {entry['n_skipped']} skipped)")
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
