#!/usr/bin/env python3
"""Import a PDGA tournament's results into RoundData.xlsx.

Fetches a PDGA event page, scrapes results for every division and round,
matches players against the active2025 roster, and appends one new round
row per (division × round) into the active sheet. New players get added
to the roster automatically (same behavior as import_udisc.py).

Each (division, round) becomes one row because their per-round scratch
is computed against their own field — combining divisions of widely-
different skill into one row would distort the scratch calc.

Event names in the output rows follow the pattern:
    {prefix}_R{round}_{division}      (e.g. "LarrimacOpen_R1_MPO")

Course code is auto-detected from each round's layout text. If the
detection misses, pass --course-override DIV/R<n>=code (repeatable).

Usage:
    python3 import_pdga.py 101991 --event LarrimacOpen --year 25
    python3 import_pdga.py https://www.pdga.com/tour/event/103069 \\
        --event SandyThrow --year 26 \\
        --division MPO --division MA1 \\
        --course-override MA1/R2=sro
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

# Reuse the matching + roster machinery from the UDisc importer.
from import_udisc import (
    add_new_player,
    find_duplicate_row,
    guess_course_from_layout,
    load_roster,
    match_player,
    next_empty_row,
    to_lastname_first,
)


PDGA_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)


def fetch_pdga(event_id_or_url: str):
    """Fetch a PDGA event page and parse it into structured pools.

    Returns ``(event_name, pools)`` where each pool is a dict:
        {
          'division': 'MPO',
          'round':    1,
          'layout_text': 'Larrimac Disc Golf Course - YELLOWS; ...',
          'players': [(display_name, pdga_num, round_score), ...],
        }
    """
    src = str(event_id_or_url)
    if not src.startswith(("http://", "https://")):
        # Bare numeric event id
        url = f"https://www.pdga.com/tour/event/{src}"
    else:
        url = src

    req = urllib.request.Request(url, headers={"User-Agent": PDGA_USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        page = resp.read().decode("utf-8", errors="replace")

    # Event name from the page title
    m = re.search(r'<h1 class="title"[^>]*>([^<]+)</h1>', page)
    event_name = html.unescape(m.group(1).strip()) if m else "PDGA event"

    # Layout-details divs hold each round's course/layout text.
    #   id="layout-details-{event_id}-{DIVISION}-round-{N}"
    layouts: dict[tuple[str, int], str] = {}
    for m in re.finditer(
        r'<div id="layout-details-\d+-([A-Z0-9]+)-round-(\d+)"[^>]*>(.*?)</div>',
        page, re.DOTALL,
    ):
        div_code = m.group(1)
        rnd = int(m.group(2))
        body = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(3))).strip()
        layouts[(div_code, rnd)] = html.unescape(body)

    # Division codes appear in document order; each division gets one
    # `<table class="results" id="tournament-stats-N">` in the same order.
    div_codes = re.findall(r'<h3 class="division" id="([A-Z0-9]+)"', page)
    tables = list(
        re.finditer(
            r'<table class="results[^"]*" id="tournament-stats-\d+".*?</table>',
            page, re.DOTALL,
        )
    )

    pools: list[dict] = []
    for div_code, table_match in zip(div_codes, tables):
        table_html = table_match.group(0)

        # Round columns from the table header: <th class="round" ...>Rd<N></th>
        thead_match = re.search(r"<thead.*?</thead>", table_html, re.DOTALL)
        if not thead_match:
            continue
        round_nums = [
            int(n) for n in re.findall(
                r'<th[^>]*class="[^"]*\bround\b[^"]*"[^>]*>Rd(\d+)</th>',
                thead_match.group(0),
            )
        ]
        if not round_nums:
            continue

        # Per-round player lists, populated as we walk the tbody.
        per_round: dict[int, list[tuple[str, str, int]]] = {r: [] for r in round_nums}

        tbody_match = re.search(r"<tbody.*?</tbody>", table_html, re.DOTALL)
        if not tbody_match:
            continue

        for row_match in re.finditer(
            r"<tr[^>]*>(.+?)</tr>", tbody_match.group(0), re.DOTALL
        ):
            row_html = row_match.group(1)

            # Name from <td class="player">: may be wrapped in an <a>.
            name_m = re.search(
                r'<td class="player"[^>]*>\s*(?:<a[^>]*>)?([^<]+)',
                row_html,
            )
            if not name_m:
                continue
            name = html.unescape(name_m.group(1).strip())

            pdga_m = re.search(
                r'<td class="pdga-number"[^>]*>([^<]*)</td>', row_html
            )
            pdga_num = html.unescape(pdga_m.group(1).strip()) if pdga_m else ""

            # Round scores: <td class="round"><a class="score">SCORE</a></td>
            # Appear in Rd1, Rd2, ... order. If a player DNF'd a round, the
            # <a class="score"> may be absent; we skip rounds we can't read.
            score_cells = re.findall(
                r'<td[^>]*class="[^"]*\bround\b[^"]*"[^>]*>.*?<a[^>]*class="[^"]*\bscore\b[^"]*"[^>]*>([^<]+)</a>',
                row_html, re.DOTALL,
            )
            for r_num, score_text in zip(round_nums, score_cells):
                try:
                    per_round[r_num].append((name, pdga_num, int(score_text.strip())))
                except ValueError:
                    continue

        for r_num in round_nums:
            pools.append({
                "division": div_code,
                "round": r_num,
                "layout_text": layouts.get((div_code, r_num), ""),
                "players": per_round[r_num],
            })

    return event_name, pools


def _run_gsheet_path(args, pools):
    """Apps-Script-backed alternative to the xlsx workflow in main().

    Same matching/dedup logic, just reads/writes the Google Sheet via the
    primitives in gsheets.py. One `pull` at the start, one `add_player` per
    new roster column (often zero), one `append_rows` for all surviving
    round rows.
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
    print(f"Master roster: {len(roster_names)} players in {args.sheet!r}\n")

    pending_player_inserts: list[tuple[int, str]] = []
    appended: list[dict] = []
    for pool in pools:
        if "divisions" in pool:
            label = f"R{pool['round']} {'/'.join(pool['divisions'])}"
        else:
            label = f"{pool['division']} R{pool['round']}"
        print(f"══ {label}  →  {pool['course']!r}  "
              f"({len(pool['players'])} players, {pool['course_why']}) ══")
        scores_by_col: dict[int, int] = {}
        added_count = 0
        for pdga_name, _pdga_num, score in pool["players"]:
            roster_name, why = match_player(pdga_name, roster_names)
            if roster_name is None:
                if args.no_add_players:
                    print(f"  ?? {pdga_name:<32}   skipped (score={score}, {why})")
                    continue
                roster_name = to_lastname_first(pdga_name)
                last_col = max(c for c, _ in roster)
                new_col = last_col + 1
                pending_player_inserts.append((last_col, roster_name))
                roster.append((new_col, roster_name))
                roster_names.append(roster_name)
                name_to_col[roster_name] = new_col
                added_count += 1
                col = new_col
                why = "ADDED to roster"
            else:
                col = name_to_col[roster_name]
            scores_by_col[col] = score
            mark = "++" if why == "ADDED to roster" else "  "
            print(f"  {mark}{pdga_name:<32} → {roster_name:<32} (score={score}, {why})")

        if "divisions" in pool:
            event_name = f"{args.event}_R{pool['round']}"
        else:
            event_name = f"{args.event}_R{pool['round']}_{pool['division']}"
        appended.append({
            "course": pool["course"],
            "event_name": event_name,
            "scores": scores_by_col,
            "n_added": added_count,
        })
        print()

    if not appended:
        sys.exit("nothing to append")

    print("══ Dedup check ══")
    to_write: list[dict] = []
    for entry in appended:
        dup = gsheets.find_duplicate_row_in_data(data, args.year, entry["scores"])
        if dup is None:
            to_write.append(entry)
            continue
        r_dup, n, total, ev_dup, crs_dup = dup
        if args.force:
            print(f"  WARN  {entry['event_name']:30s} matches row {r_dup} "
                  f"({n}/{total}; {ev_dup!r}, {crs_dup!r}) — writing anyway because --force")
            to_write.append(entry)
        else:
            print(f"  SKIP  {entry['event_name']:30s} duplicate of row {r_dup} "
                  f"(event {ev_dup!r}, course {crs_dup!r}, {n}/{total} scores match)")
    print()

    if not to_write and not pending_player_inserts:
        print("nothing to write (all candidate pools flagged as duplicates).")
        return

    print("══ Planned writes ══")
    for after_col, name in pending_player_inserts:
        print(f"  add_player {name!r:30s} at col {after_col + 1}")
    for entry in to_write:
        n_total = len(entry["scores"])
        n_matched = n_total - entry["n_added"]
        print(f"  append row  event={entry['event_name']!r:30s}  course={entry['course']!r}  "
              f"({n_matched} matched, {entry['n_added']} new)")

    if args.dry_run:
        print("\n(dry run — Sheet NOT modified)")
        return

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
            row[1] = entry["event_name"]
            row[2] = entry["course"]
            for col, score in entry["scores"].items():
                row[col - 1] = score
            rows.append(row)
        print(f"\n══ Appending {len(rows)} round row(s) ══")
        result = gsheets.append_rows(url, rows, args.sheet)
        print(f"  written at rows {result['first_row']}-{result['last_row']}")

    print(f"\nNow re-run:  python3 hc24.py --gsheet --sheet {args.sheet}")


def main(argv=None):
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("source", help="PDGA event ID (e.g. 101991) or full URL")
    p.add_argument("--event", required=True,
                   help="Event-name prefix; per-row events become {prefix}_R{n}_{division}")
    p.add_argument("--year", type=int, required=True,
                   help="2-digit year for col A (e.g. 26 for 2026)")
    p.add_argument("--division", action="append", default=[],
                   help="Limit to these divisions, e.g. --division MPO --division MA1")
    p.add_argument("--course-override", action="append", default=[], metavar="DIV/Rn=code",
                   help="Force course for a specific (division, round): "
                        "e.g. --course-override MA1/R2=sro")
    p.add_argument("--master", type=Path, default=Path("RoundData.xlsx"))
    p.add_argument("--gsheet", nargs="?", const="auto", default=None, metavar="URL",
                   help="Write to the Google Sheet via the Apps Script backend "
                        "instead of the local xlsx. With no value, uses "
                        "./gsheets_url.txt.")
    p.add_argument("--sheet", default="active2025")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-add-players", action="store_true",
                   help="Skip unmatched players instead of adding them to the roster")
    p.add_argument("--no-merge-same-course", action="store_true",
                   help="Disable merging divisions playing the same (round, course) "
                        "into one row. Off by default — merging keeps single-player "
                        "divisions from being skipped by the round-size guard.")
    p.add_argument("--force", action="store_true",
                   help="Write rows even if they look like duplicates of existing ones")
    args = p.parse_args(argv)

    # Parse --course-override entries.
    course_overrides: dict[tuple[str, int], str] = {}
    for entry in args.course_override:
        key, _, code = entry.partition("=")
        m = re.match(r"([A-Z0-9]+)/R?(\d+)", key.strip())
        if not m or not code.strip():
            sys.exit(
                f"invalid --course-override {entry!r}; "
                "expected DIV/R<n>=code, e.g. MPO/R1=lmb"
            )
        course_overrides[(m.group(1), int(m.group(2)))] = code.strip()

    # Fetch the event.
    event_name, pools = fetch_pdga(args.source)
    print(f"Event:  {event_name}")
    print(f"Source: {args.source}")
    print(f"Pools:  {len(pools)} (division × round)")
    print()

    # Optional division filter.
    if args.division:
        wanted = {d.upper() for d in args.division}
        before = len(pools)
        pools = [p for p in pools if p["division"] in wanted]
        print(f"Filtered to divisions {sorted(wanted)}: {before} → {len(pools)} pools")
        print()

    # Resolve a course code for each pool.
    for pool in pools:
        key = (pool["division"], pool["round"])
        if key in course_overrides:
            pool["course"] = course_overrides[key]
            pool["course_why"] = "via --course-override"
        else:
            code = guess_course_from_layout(pool["layout_text"])
            if not code:
                sys.exit(
                    f"\nno course detected for {pool['division']} R{pool['round']}\n"
                    f"  layout: {pool['layout_text']!r}\n"
                    f"  pass --course-override {pool['division']}/R{pool['round']}=CODE"
                )
            pool["course"] = code
            pool["course_why"] = f"auto-detected from {pool['layout_text'][:50]!r}"

    # Group pools by (round, course) so divisions on the same layout share
    # one row. Single-player pools then merge with other divisions on the
    # same course, avoiding the round-size guard in hc24.py that would
    # otherwise skip them entirely.
    if not args.no_merge_same_course:
        merged: dict[tuple[int, str], dict] = {}
        for pool in pools:
            key = (pool["round"], pool["course"])
            if key not in merged:
                merged[key] = {
                    "round": pool["round"],
                    "course": pool["course"],
                    "course_why": pool["course_why"],
                    "divisions": [],
                    "players": [],
                }
            merged[key]["divisions"].append(pool["division"])
            merged[key]["players"].extend(pool["players"])
        pools = list(merged.values())
        # Sort by round then course for readable output order.
        pools.sort(key=lambda p: (p["round"], p["course"]))
        print(f"Merged same-course divisions: {len(pools)} pool(s) after merge\n")

    if args.gsheet is not None:
        return _run_gsheet_path(args, pools)

    # Open the master workbook.
    master = load_workbook(args.master, data_only=False)
    if args.sheet not in master.sheetnames:
        sys.exit(f"sheet {args.sheet!r} not in {args.master}")
    ms = master[args.sheet]
    roster = load_roster(ms)
    roster_names = [n for _, n in roster]
    name_to_col = {n: c for c, n in roster}
    print(f"Master roster: {len(roster_names)} players in {args.sheet!r}\n")

    # Match + (optionally) auto-add, accumulate writes.
    appended: list[dict] = []
    for pool in pools:
        if "divisions" in pool:
            label = f"R{pool['round']} {'/'.join(pool['divisions'])}"
        else:
            label = f"{pool['division']} R{pool['round']}"
        print(f"══ {label}  →  {pool['course']!r}  "
              f"({len(pool['players'])} players, {pool['course_why']}) ══")
        scores_by_col: dict[int, int] = {}
        added_count = 0
        for pdga_name, _pdga_num, score in pool["players"]:
            roster_name, why = match_player(pdga_name, roster_names)
            if roster_name is None:
                if args.no_add_players:
                    print(f"  ?? {pdga_name:<32}   skipped (score={score}, {why})")
                    continue
                roster_name = to_lastname_first(pdga_name)
                last_col = max(c for c, _ in roster)
                if not args.dry_run:
                    new_col = add_new_player(ms, roster_name, last_col)
                else:
                    new_col = last_col + 1
                roster.append((new_col, roster_name))
                roster_names.append(roster_name)
                name_to_col[roster_name] = new_col
                added_count += 1
                col = new_col
                why = "ADDED to roster"
            else:
                col = name_to_col[roster_name]
            scores_by_col[col] = score
            mark = "++" if why == "ADDED to roster" else "  "
            print(f"  {mark}{pdga_name:<32} → {roster_name:<32} (score={score}, {why})")

        # Event name: merged pools just use {prefix}_R{round}; multiple rows
        # with the same event name but different courses are fine (mirrors
        # how LETS04 shows up twice in active2025 for lmy and lmb pools).
        # Un-merged pools include the division so each row is unique.
        if "divisions" in pool:
            event_name = f"{args.event}_R{pool['round']}"
        else:
            event_name = f"{args.event}_R{pool['round']}_{pool['division']}"
        appended.append({
            "course": pool["course"],
            "event_name": event_name,
            "scores": scores_by_col,
            "n_added": added_count,
        })
        print()

    if not appended:
        sys.exit("nothing to append")

    # Dedup check: skip any candidate pool that looks like a re-import of an
    # existing row. Matches purely on (year, per-player-score overlap), so it
    # catches duplicates even when event names or course codes diverge.
    print("══ Dedup check ══")
    to_write: list[dict] = []
    for entry in appended:
        dup = find_duplicate_row(ms, args.year, entry["scores"])
        if dup is not None:
            r_dup, n, total, ev_dup, crs_dup = dup
            if args.force:
                print(f"  WARN  {entry['event_name']:30s} matches row {r_dup} "
                      f"({n}/{total} scores; event {ev_dup!r}, course {crs_dup!r}) "
                      f"— writing anyway because --force")
                to_write.append(entry)
            else:
                print(f"  SKIP  {entry['event_name']:30s} duplicate of row {r_dup} "
                      f"(event {ev_dup!r}, course {crs_dup!r}, {n}/{total} scores match)")
        else:
            to_write.append(entry)
    print()

    if not to_write:
        print("nothing to write (all candidate pools flagged as duplicates).")
        if not args.dry_run:
            return
        # fall through so dry-run still finishes cleanly
        to_write = []

    # Write the new round rows.
    target_row = next_empty_row(ms)
    print("══ Writes ══")
    for i, entry in enumerate(to_write):
        r = target_row + i
        n_total = len(entry["scores"])
        n_matched = n_total - entry["n_added"]
        print(f"  row {r}: year={args.year}  event={entry['event_name']!r:30s}  "
              f"course={entry['course']!r}  "
              f"({n_matched} matched, {entry['n_added']} new added)")
        if args.dry_run:
            continue
        ms.cell(row=r, column=1, value=args.year)
        ms.cell(row=r, column=2, value=entry["event_name"])
        ms.cell(row=r, column=3, value=entry["course"])
        for col_idx, _name in roster:
            ms.cell(row=r, column=col_idx, value=entry["scores"].get(col_idx, 0))

    if args.dry_run:
        print("\n(dry run — workbook NOT modified)")
        return

    bak = args.master.with_suffix(args.master.suffix + ".bak")
    if not bak.exists():
        shutil.copy(args.master, bak)
        print(f"\nbackup → {bak}")

    master.save(args.master)
    print(f"saved   → {args.master}")
    print(f"\nNow re-run:  python3 hc24.py --xlsx {args.master} --sheet {args.sheet}")


if __name__ == "__main__":
    main()
