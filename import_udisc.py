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
import unicodedata
import urllib.request
from difflib import get_close_matches
from pathlib import Path

from openpyxl import load_workbook


# Map UDisc division name (xlsx mode) → course code in RoundData.xlsx.
# Edit if the league uses different division names.
DIVISION_TO_COURSE = {
    "GOLD": "lmy",   # Larrimac Yellow tees
    "BLUE": "lmb",   # Larrimac Blue tees
}

# (No flat lookup table — guess_course_from_layout() below does context-aware
# matching that handles both UDisc's compact phrasing ("Almonte Blues")
# and PDGA's verbose layout strings ("Larrimac Disc Golf Course - YELLOWS").)

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

    # 4 — unique surname, BUT only if the first name's first letter also
    #     agrees. Without that check, an unfamiliar player ("Amber Correia")
    #     would get auto-matched to a roster member ("Correia_Justin") just
    #     because they share a last name. First-name shortenings (Chris/
    #     Christopher, Dave/David, Max/Maxime) still share initial letters,
    #     so this filter doesn't reject legitimate matches.
    parts = udisc_name.strip().split()
    udisc_first_initial = parts[0][0].lower() if parts else ""
    last = candidate.split("_")[0]
    last_stripped = strip_accents(last).lower()
    surname_matches = [
        n for n in roster
        if strip_accents(n).lower().startswith(last_stripped + "_")
    ]
    if len(surname_matches) == 1:
        roster_first = surname_matches[0].split("_", 1)[1] if "_" in surname_matches[0] else ""
        if roster_first and udisc_first_initial == roster_first[0].lower():
            return surname_matches[0], "unique surname + first-initial"
        # Surname matches but first names disagree → probably a different person
        return None, (
            f"surname matches {surname_matches[0]!r} but first names "
            f"differ ({parts[0] if parts else '?'} vs {roster_first})"
        )
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

    layout_text   The human-readable layout name shown on the page (e.g.
                  "Blue Tees 18"). Used to guess a course code.
    players       List of (display_name, round_total_score) tuples.
    """
    headers = {
        # UDisc 403s when there's no User-Agent set
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
                      "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                      "Version/17.0 Safari/605.1.15",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        page = resp.read().decode("utf-8", errors="replace")

    # Title gives us the full event name; <h1> gives layout/round.
    m_title = re.search(r"<title[^>]*>([^<]+)</title>", page)
    m_h1 = re.search(r"<h1[^>]*>([^<]+)</h1>", page)
    layout_text = " | ".join(
        s.group(1).strip()
        for s in (m_h1, m_title)
        if s and "UDisc" not in s.group(1).split("|", 1)[0]
    )

    # Each player row has the pattern (after stripping tags):
    #   |position|<blank>|Player Name|relative_score|h1|h2|...|h18|rating|strokes|
    # Strokes is the last cell. Name is in a <p class="text-wrap text-start">.
    players = []
    for tr_match in re.finditer(r"<tr[^>]*>(.+?)</tr>", page, re.DOTALL):
        row_html = tr_match.group(1)
        name_match = re.search(
            r'<p class="text-wrap text-start">\s*(?:<!--[^>]*-->)?\s*([^<]+?)</p>',
            row_html,
        )
        if not name_match:
            continue
        name = html.unescape(name_match.group(1).strip())
        # All <td> cell text contents:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.DOTALL)
        # Strokes is the last numeric cell
        strokes = None
        for cell in reversed(cells):
            txt = re.sub(r"<[^>]+>", "", cell).strip()
            if txt.isdigit():
                strokes = int(txt)
                break
        if strokes is None:
            continue
        players.append((name, strokes))

    return layout_text, players


def guess_course_from_layout(text: str) -> str | None:
    """Map a layout/event string (UDisc or PDGA) to one of our course codes.

    Context-aware: looks for the COURSE name first, then a tee color modifier
    within the same text. Handles both compact UDisc names ("Almonte Blues")
    and verbose PDGA strings ("Larrimac Disc Golf Course - YELLOWS; 18 holes").
    """
    s = text.lower()

    def has(*tokens):
        return any(t in s for t in tokens)

    # Larrimac
    if has("larrimac", "lmac"):
        if has("yellow"):
            return "lmy"
        if has("blue"):
            return "lmb"
        return "lmb"
    # Sandy Row. PDGA uses "ORANGE Sandy Row" / "BLUE Sandy Row"; UDisc
    # sometimes drops the color ("Sandy Row Golf Club"). User convention in
    # active2025: sro = ORANGE, sr = BLUE (BLUE is the default when no
    # color modifier is present).
    if has("sandy row"):
        return "sro" if has("orange") else "sr"
    # Almonte
    if has("almonte"):
        if has("yellow"):
            return "aly"
        if has("blue"):
            return "alb"
        if has("red"):
            return "alr"
        return "alm"
    # Ferguson Forest (Kemptville). UDisc events: "Ferguson Forest Blues",
    # "Ferguson Forest Wonderbread", etc. User maps all of these to kvb/kvy/kvr
    # (the Kemptville tee codes), NOT the older `kpv` slot. Check this before
    # the general "kemptville" rule so Ferguson always lands on the right code.
    if has("ferguson"):
        if has("yellow"):
            return "kvy"
        if has("red"):
            return "kvr"
        return "kvb"
    # Kemptville (other layouts, if any)
    if has("kemptville"):
        if has("yellow"):
            return "kvy"
        if has("blue"):
            return "kvb"
        if has("red"):
            return "kvr"
        return "kvb"
    # Ettyville Phase MVP. UDisc uses "Ettyville MVP <tee>". Also Pdgy aliases.
    if has("ettyville mvp", "phase mvp", "pdgy", "mvp tee", "mvp"):
        if has("white"):
            return "epw"
        if has("yellow"):
            return "epy"
        if has("blue"):
            return "epb"
    # Ettyville Phase Axiom. UDisc uses "Ettyville Axiom [Dunes] <tee>".
    if has("axiom", "inva"):
        if has("white"):
            return "eiw"
        if has("yellow"):
            return "eiy"
        if has("blue"):
            return "eib"
    # Single-layout courses
    if has("the shire", "shire"):
        return "shr"
    if has("camp fortune"):
        return "cf"
    if has("franktown"):
        return "rhl"
    if has("centrepointe", "centerpointe"):
        return "ctp"
    # Mountain — UDisc lists this as "Philips Screw Driver" (yes, that
    # spelling); user catalogs it as Phillips_Screwdriver → mtn.
    if has("philips screw driver", "phillips screw driver", "phillips screwdriver",
           "screwdriver", "mountain"):
        return "mtn"
    if has("kanata"):
        return "kan"
    if has("upi"):
        return "upi"
    return None


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("source",
                   help="UDisc xlsx file path OR leaderboard URL")
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
