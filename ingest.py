#!/usr/bin/env python3
"""One-command flow: ingest a round/tournament from a URL, then recompute HCs.

Auto-detects whether the source is a PDGA event or a UDisc league round and
delegates to the matching importer. Then runs hc24.py to refresh the HC
output files. Default backend is the Google Sheet via Apps Script (set up
with apps_script.gs and gsheets_url.txt). Pass --xlsx PATH to operate on a
local workbook instead.

Auto-detection rules:
    bare numeric ("101991")                → PDGA event by ID
    pdga.com/tour/event/...                → PDGA event
    udisc.com/events/.../leaderboard...    → UDisc league round
    a path ending in .xlsx                 → UDisc xlsx export

Usage:
    python3 ingest.py "https://udisc.com/events/.../leaderboard?round=1" \\
        --event TOSS05 --year 26
    python3 ingest.py 101991 --event LarrimacOpen --year 26
    python3 ingest.py imports/lets_2026.xlsx --event LETS06 --year 26 \\
        --xlsx RoundData.xlsx

Extra flags after the required ones pass through to the underlying
importer (--no-add-players, --force, --course-override, --division, …)
or to hc24.py (--odgc-only, --golf-cap K).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def detect_source_kind(src: str) -> str:
    """Returns 'pdga' or 'udisc' for the source string."""
    s = src.strip()
    if s.isdigit():
        return "pdga"
    if "pdga.com" in s:
        return "pdga"
    if "udisc.com" in s:
        return "udisc"
    if s.lower().endswith((".xlsx", ".xlsm", ".xltx")):
        return "udisc"
    raise SystemExit(
        f"can't tell what kind of source this is: {s!r}\n"
        f"expected a PDGA URL/event-id, a UDisc URL, or a UDisc xlsx path."
    )


def main(argv=None):
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("source",
                   help="PDGA event ID/URL, UDisc URL, or UDisc xlsx file path")
    p.add_argument("--event", required=True,
                   help='Event name to write into col B (e.g. "TOSS05")')
    p.add_argument("--year", type=int, required=True,
                   help='2-digit year for col A (e.g. 26 for 2026)')
    p.add_argument("--sheet", default="active2025",
                   help="Worksheet name (default: active2025)")
    backend = p.add_mutually_exclusive_group()
    backend.add_argument("--xlsx", type=Path, default=None,
                         help="Use a local xlsx workbook instead of the Google Sheet")
    backend.add_argument("--gsheet", nargs="?", const="auto", default=None,
                         metavar="URL",
                         help="Override the gsheet URL (default: ./gsheets_url.txt)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would be written; don't modify anything or recompute HCs")
    p.add_argument("--kind", choices=("auto", "pdga", "udisc"), default="auto",
                   help="Force source type instead of auto-detecting")
    p.add_argument("--skip-recompute", action="store_true",
                   help="Just ingest; don't run hc24 afterwards")
    # Common importer pass-throughs (forwarded to import_udisc / import_pdga):
    p.add_argument("--force", action="store_true",
                   help="(importer) write rows even if they look like duplicates")
    p.add_argument("--no-add-players", action="store_true",
                   help="(importer) skip unmatched players instead of adding them")
    p.add_argument("--course", default=None,
                   help="(udisc URL) override auto-detected course code")
    p.add_argument("--course-override", action="append", default=[],
                   metavar="DIV/Rn=code",
                   help="(pdga) force course for a (division, round); repeatable")
    p.add_argument("--division", action="append", default=[],
                   help="(pdga) limit to specific division(s); repeatable")
    p.add_argument("--no-merge-same-course", action="store_true",
                   help="(pdga) one row per (division × round) instead of merging")
    # hc24 pass-throughs:
    p.add_argument("--odgc-only", action="store_true",
                   help="(hc24) skip the golf-style output set")
    p.add_argument("--golf-cap", type=float, default=None, metavar="K",
                   help="(hc24) tanh soft cap for '+' handicaps (default 5.0)")
    p.add_argument("--push-tab", default="HC", metavar="TAB",
                   help="Sheet tab to overwrite with the rankings table "
                        "(gsheet backend only; default: HC)")
    p.add_argument("--no-push", action="store_true",
                   help="Skip pushing the rankings table back to the Sheet")
    args = p.parse_args(argv)

    # Source detection.
    kind = args.kind if args.kind != "auto" else detect_source_kind(args.source)

    # Default backend: --gsheet (auto). Either --xlsx or explicit --gsheet
    # URL overrides.
    use_xlsx = args.xlsx is not None
    gsheet_arg = None
    if not use_xlsx:
        gsheet_arg = args.gsheet if args.gsheet is not None else "auto"

    # --- step 1: ingest --------------------------------------------------
    importer_argv = [
        args.source,
        "--event", args.event,
        "--year", str(args.year),
        "--sheet", args.sheet,
    ]
    if use_xlsx:
        importer_argv += ["--master", str(args.xlsx)]
    else:
        importer_argv += ["--gsheet", gsheet_arg]
    if args.dry_run:
        importer_argv += ["--dry-run"]
    if args.force:
        importer_argv += ["--force"]
    if args.no_add_players:
        importer_argv += ["--no-add-players"]
    if kind == "udisc" and args.course:
        importer_argv += ["--course", args.course]
    if kind == "pdga":
        for ov in args.course_override:
            importer_argv += ["--course-override", ov]
        for div in args.division:
            importer_argv += ["--division", div]
        if args.no_merge_same_course:
            importer_argv += ["--no-merge-same-course"]

    print(f"┌── ingest ({kind}) ──")
    print(f"│  source:  {args.source}")
    print(f"│  event:   {args.event}    year: {args.year}")
    print(f"│  target:  {'xlsx ' + str(args.xlsx) if use_xlsx else 'gsheet'}")
    print(f"└──")
    print()

    if kind == "pdga":
        import import_pdga
        import_pdga.main(importer_argv)
    else:
        import import_udisc
        import_udisc.main(importer_argv)

    if args.dry_run:
        print("\n(dry run — skipping HC recompute)")
        return
    if args.skip_recompute:
        return

    # --- step 2: recompute HCs ------------------------------------------
    hc_argv = ["--sheet", args.sheet]
    if use_xlsx:
        hc_argv += ["--xlsx", str(args.xlsx)]
    else:
        hc_argv += ["--gsheet", gsheet_arg]
    if args.odgc_only:
        hc_argv += ["--odgc-only"]
    if args.golf_cap is not None:
        hc_argv += ["--golf-cap", str(args.golf_cap)]
    # When backend is gsheet, also push the rankings table back to the
    # Sheet unless the user asked us not to.
    if not use_xlsx and not args.no_push:
        hc_argv += ["--push-sheet", args.push_tab]

    print()
    print("┌── recompute HCs ──")
    print(f"│  source:  {'xlsx ' + str(args.xlsx) if use_xlsx else 'gsheet'}")
    print(f"│  outputs land in:  {Path.cwd()}")
    print("└──")
    print()

    import hc24
    hc24.main(hc_argv)


if __name__ == "__main__":
    main()
