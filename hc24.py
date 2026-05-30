#!/usr/bin/env python3
"""hc24.py — Python port of the ODGC disc-golf handicap algorithm.

Faithful 1:1 port of hc24.cpp / hcCalc.h / LeastSquares.h / stdev.h.
Reads RoundData.dat in the cwd; writes nine output files that should match
the C++ output byte-for-byte:
    alphHC.txt, atosHC.txt, evHC.txt, kvHC.txt, ladiesHC.txt,
    odgcHC.txt, odgccaCH.txt, rankHC.txt, player_rounds.txt
The diagnostic firehoses (example.txt, debug.txt) are NOT reproduced.

Arrays are 1-indexed to mirror the C++ source line-by-line.
"""

from __future__ import annotations

from pathlib import Path

# Pure algorithm + constants live in hc_algorithm.py so the Cloudflare Worker
# can import them too. hc24.py is the CLI orchestrator (file I/O, parsing
# from .dat / .xlsx / Google Sheets, writing the 18 output files).
from hc_algorithm import (
    fmt_g, fmt_g_golf, fmt_2f_golf,
    compress_plus_hc,
    compute_handicaps,
    NUM_CRS, COURSE_ID, SEEDS,
)


def open_latin1(path, mode="w"):
    """Output bytes in Latin-1 to match the C++ ofstream byte stream (the source
    .dat file is ISO-8859-1, and C++ does no transcoding)."""
    return open(path, mode, encoding="latin-1", newline="\n")


def parse_input_dat(path: Path):
    """Parse RoundData.dat into (player[], i_pl, remainder_tokens)."""
    text = path.read_text(encoding="latin-1")
    lines = text.split("\n")

    # Line 1: PLAYER + names. Whitespace-split == iss >> word.
    line1_tokens = lines[0].split()
    if not line1_tokens or line1_tokens[0] != "PLAYER":
        raise ValueError(f"Expected PLAYER as first token, got {line1_tokens[:3]}")

    # player[0] = "PLAYER", player[1..i_pl] = real names.
    i_pl = len(line1_tokens) - 1
    player = [""] * (i_pl + 2)
    for idx, name in enumerate(line1_tokens):
        player[idx] = name

    # Stream the rest of the file as whitespace-separated tokens
    # (mirrors C++ `ifstream >> token` semantics which cross newlines).
    remainder = []
    for ln in lines[1:]:
        remainder.extend(ln.split())

    return player, i_pl, remainder


def parse_input_xlsx(path: Path, sheet: str):
    """Parse an active*-style worksheet into the same shape as parse_input_dat.

    Sheet layout (rows 1-indexed, cols 1-indexed):
        col A,B,C: row labels / round metadata
        col D+:    one column per player

        row  1: player names (cols D..)
        row  2: seed HCs (-1 if no seed)
        rows 3-9: 7 lines of seed differentials (100 if no seed)
        row 10: ODGCmember 0/1
        row 11: Atos_List 0/1
        row 12: EVmember 0/1
        row 13: LadiesLeague 0/1
        row 14+: year (A), event (B), course (C), scores (D..) — 0 = did not play
    """
    try:
        from openpyxl import load_workbook
    except ImportError as e:
        raise ImportError("openpyxl required for --xlsx; install with `pip install openpyxl`") from e

    wb = load_workbook(path, data_only=True)
    if sheet not in wb.sheetnames:
        raise ValueError(f"Sheet {sheet!r} not found. Available: {wb.sheetnames}")
    ws = wb[sheet]

    # Player columns: row 1, col D (=4) onward, stopping at the first None or
    # at a known helper column ("count", "total", etc. — sums added to the
    # right of the real roster by the spreadsheet maintainer).
    HELPER_LABELS = {"count", "total", "sum", "tally", "n", "#"}
    row1 = list(ws.iter_rows(min_row=1, max_row=1, values_only=True))[0]
    names = []
    for v in row1[3:]:
        if v is None:
            break
        s = str(v).strip()
        if s.lower() in HELPER_LABELS:
            break
        names.append(s)
    i_pl = len(names)
    if i_pl == 0:
        raise ValueError(f"No player names found in row 1 of sheet {sheet!r}")
    player = [""] * (i_pl + 2)
    player[0] = "PLAYER"
    for idx, name in enumerate(names, 1):
        player[idx] = name

    def cells_row(row_num):
        """Return values from col D to col D+i_pl-1 of the given row."""
        return [ws.cell(row=row_num, column=4 + j).value for j in range(i_pl)]

    def as_num(v, default):
        return v if v is not None else default

    tokens: list[str] = []

    # Row 2: seed HCs
    tokens += ["end_2020_hc", "HC"]
    for v in cells_row(2):
        tokens.append(_fmt_num(as_num(v, -1)))

    # Rows 3-9: 7 lines of seed differentials, no labels
    for r in range(3, 10):
        for v in cells_row(r):
            tokens.append(_fmt_num(as_num(v, 100)))

    # Rows 10-13: membership flags (each has labels in col B,C)
    label_pairs = [
        ("ODGCmember", "status"),
        ("Atos_List", "status"),
        ("EVmember", "status"),
        ("LadiesLeague", "status"),
    ]
    for r, (lab1, lab2) in zip(range(10, 14), label_pairs):
        tokens += [lab1, lab2]
        for v in cells_row(r):
            tokens.append(str(int(as_num(v, 0))))

    # Rows 14+: rounds. Mirror the .dat parser's stop rule (event len < 3).
    for r in range(14, ws.max_row + 1):
        yr = ws.cell(row=r, column=1).value
        ev = ws.cell(row=r, column=2).value
        cr = ws.cell(row=r, column=3).value
        if yr is None or ev is None or cr is None:
            break
        ev_str = str(ev).strip()
        if len(ev_str) < 3:
            break
        tokens.append(str(int(yr)))
        tokens.append(ev_str)
        tokens.append(str(cr).strip())
        for v in cells_row(r):
            tokens.append(str(int(as_num(v, 0))))

    return player, i_pl, tokens


def parse_input_gsheet(url: str, sheet: str = "active2025"):
    """Same shape as parse_input_xlsx but reads from a Google Sheet via the
    Apps Script backend (see gsheets.py and apps_script.gs)."""
    from gsheets import pull

    data = pull(url, sheet)
    if not data:
        raise ValueError(f"Sheet {sheet!r} is empty")

    HELPER_LABELS = {"count", "total", "sum", "tally", "n", "#"}
    row1 = data[0]
    names: list[str] = []
    for v in row1[3:]:
        if v in (None, ""):
            break
        s = str(v).strip()
        if s.lower() in HELPER_LABELS:
            break
        names.append(s)
    i_pl = len(names)
    if i_pl == 0:
        raise ValueError(f"No player names found in row 1 of sheet {sheet!r}")
    player = [""] * (i_pl + 2)
    player[0] = "PLAYER"
    for idx, name in enumerate(names, 1):
        player[idx] = name

    def cell_or_none(row_idx: int, col_idx: int):
        if row_idx >= len(data):
            return None
        r = data[row_idx]
        if col_idx >= len(r):
            return None
        v = r[col_idx]
        return None if v == "" else v

    def cells_row(row_num: int):
        # 1-indexed row_num → 0-indexed data; cols D..D+i_pl-1
        return [cell_or_none(row_num - 1, 3 + j) for j in range(i_pl)]

    def as_num(v, default):
        return v if v is not None else default

    tokens: list[str] = ["end_2020_hc", "HC"]
    for v in cells_row(2):
        tokens.append(_fmt_num(as_num(v, -1)))

    for r in range(3, 10):
        for v in cells_row(r):
            tokens.append(_fmt_num(as_num(v, 100)))

    label_pairs = [
        ("ODGCmember", "status"),
        ("Atos_List", "status"),
        ("EVmember", "status"),
        ("LadiesLeague", "status"),
    ]
    for r, (lab1, lab2) in zip(range(10, 14), label_pairs):
        tokens += [lab1, lab2]
        for v in cells_row(r):
            tokens.append(str(int(as_num(v, 0))))

    for r in range(14, len(data) + 1):
        yr = cell_or_none(r - 1, 0)
        ev = cell_or_none(r - 1, 1)
        cr = cell_or_none(r - 1, 2)
        if yr is None or ev is None or cr is None:
            break
        ev_str = str(ev).strip()
        if len(ev_str) < 3:
            break
        tokens.append(str(int(yr)))
        tokens.append(ev_str)
        tokens.append(str(cr).strip())
        for v in cells_row(r):
            tokens.append(str(int(as_num(v, 0))))

    return player, i_pl, tokens


def _fmt_num(v):
    """Stringify a numeric cell value the way the .dat file does (e.g. -1 not -1.0)."""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def export_tokens_as_dat(player, i_pl, tokens, out_path: Path):
    """Write the (player, tokens) parse back out as a .dat-formatted file.

    Used as a round-trip verification fixture: the same xlsx data, exported
    and run through the C++ pipeline, must produce identical output to the
    Python --xlsx run."""
    parts = ["\t" * 2 + "PLAYER\t" + "\t".join(player[1:i_pl + 1])]

    pos = 0
    def take_n(n):
        nonlocal pos
        out = tokens[pos:pos + n]
        pos += n
        return out

    # Row 2: 2 labels + i_pl values
    parts.append("\t" + "\t".join(take_n(2)) + "\t" + "\t".join(take_n(i_pl)))
    # Rows 3-9: 7 lines of i_pl values
    for _ in range(7):
        parts.append("\t\t\t" + "\t".join(take_n(i_pl)))
    # Rows 10-13: 2 labels + i_pl values
    for _ in range(4):
        parts.append("\t" + "\t".join(take_n(2)) + "\t" + "\t".join(take_n(i_pl)))
    # Round rows: 3 metadata + i_pl scores each, until tokens run out
    while pos + 3 + i_pl <= len(tokens):
        meta = take_n(3)
        scores = take_n(i_pl)
        parts.append("\t".join(meta) + "\t" + "\t".join(scores) + "\t")

    out_path.write_text("\n".join(parts) + "\n", encoding="latin-1")




def write_outputs(result, here, *, suffix="", golf_style=False, golf_cap_k=5.0):
    """Write the nine HC files into `here`.

    suffix       Appended to each filename before '.txt' (e.g. '_golf' →
                 'rankHC_golf.txt'). Empty for the default ODGC outputs.
    golf_style   If True, negative HCs render with '+' prefix (golf convention:
                 '+1.5' means the player is 1.5 strokes better than scratch).
                 If False, numbers print as-is (matches C++ reference output).
    golf_cap_k   Tanh soft-cap for '+' handicaps. Applied only when
                 golf_style=True. Set to 0 to disable compression and show
                 raw natural HCs. Default 5.0 → '+' handicaps asymptote at +5.
    """
    player = result["player"]
    i_pl = result["i_pl"]
    rnd_count = result["rnd_count"]
    in_rnd_count = result["in_rnd_count"]
    toss19_rnd_count = result["toss19_rnd_count"]
    ODGCmem_stat = result["ODGCmem_stat"]
    TOSSmem_stat = result["TOSSmem_stat"]
    EVmem_stat = result["EVmem_stat"]
    LLmem_stat = result["LLmem_stat"]
    crs_ref = result["crs_ref"]

    # Compress '+' handicaps for display when in golf mode. The natural HC
    # array is left intact in `result` so it stays available to callers.
    raw_hc = result["hc"]
    if golf_style and golf_cap_k:
        hc = [compress_plus_hc(h, golf_cap_k) for h in raw_hc]
    else:
        hc = raw_hc

    f_g = fmt_g_golf if golf_style else fmt_g
    f_2 = fmt_2f_golf if golf_style else (lambda x: f"{x:.2f}")

    # Alphabetical iteration order by player name. The .dat input was
    # manually maintained in name-sorted order treating apostrophes as
    # invisible (so L'Esperance sits between Lebrun and Lessard, not at
    # the top of the L's); the sort key matches that convention so the
    # regression byte-equality holds on the existing input.
    def _alpha_key(name: str) -> str:
        # Drop apostrophes (so L'Esperance sorts as "Lesperance") and
        # case-fold so the capitalized letter that follows an apostrophe
        # doesn't sort before lowercase neighbors.
        return name.replace("'", "").replace("’", "").casefold()

    alpha_order = sorted(range(1, i_pl + 1), key=lambda j: _alpha_key(player[j]))

    def out(name):
        return here / f"{name}{suffix}.txt"

    with open_latin1(out("player_rounds"), "w") as f:
        for j in alpha_order:
            f.write(f"{player[j]} HC =  {f_g(hc[j])}  rounds played = {rnd_count[j] - in_rnd_count[j]}\n")

    # rankHC — sorted ascending by HC; same bubble-sort as C++
    rank_hc = list(range(0, i_pl + 2))
    for ij in range(1, i_pl):
        for j in range(1, i_pl - ij + 1):
            if hc[rank_hc[j]] > hc[rank_hc[j + 1]]:
                rank_hc[j], rank_hc[j + 1] = rank_hc[j + 1], rank_hc[j]

    with open_latin1(out("rankHC"), "w") as f:
        f.write("\n\n")
        i_rank = 0
        for j in range(1, i_pl + 1):
            idx = rank_hc[j]
            if rnd_count[idx] > 2:
                i_rank += 1
                f.write(f" rank =  {i_rank}  {player[idx]} HC =  {f_g(hc[idx])}  rounds played = {rnd_count[idx] - in_rnd_count[idx]}\n")

    # alphHC — players in alphabetical order. The C++ `mem_stat` array is
    # declared but never populated, so this field always prints "NO". Reproduce.
    with open_latin1(out("alphHC"), "w") as f:
        for j in alpha_order:
            if rnd_count[j] > 2:
                f.write(
                    f"{player[j]} HC =  {f_g(hc[j])}  "
                    f"rounds played = {rnd_count[j] - in_rnd_count[j]}  "
                    f"current member? - NO 2019TOSSrnds = {toss19_rnd_count[j]}\n"
                )

    # kvHC — Kemptville (Ferguson + Mountain), all qualified players
    with open_latin1(out("kvHC"), "w") as f:
        f.write("\nKemptville_courses_HC_list    base54HC Ferguson   Mountain  \n")
        for j in alpha_order:
            if rnd_count[j] > 2:
                f.write(
                    f"{player[j]}   "
                    f"{f_2(hc[j])}   "
                    f"{f_2(hc[j] * crs_ref[12] / 54.0)}   "
                    f"{f_2(hc[j] * crs_ref[13] / 54.0)}   "
                    f"{f_2(hc[j] * crs_ref[1] / 54.0)}\n"
                )

    # odgcHC — ODGC members, multi-course scaled
    with open_latin1(out("odgcHC"), "w") as f:
        f.write(
            "\nODGC_courses_HC_list    base54HC LmacBlue  LmacYellow Almonte_blue   "
            "Kanata   Mountain  KvYel KvBlue KvRed Shire Franktown Camp_Fortune\n"
        )
        for j in alpha_order:
            if rnd_count[j] > 2 and ODGCmem_stat[j] == 1:
                f.write(
                    f"{player[j]}   {f_2(hc[j])}   "
                    f"{f_2(hc[j]*crs_ref[8]/54.0)}   "
                    f"{f_2(hc[j]*crs_ref[9]/54.0)}   "
                    f"{f_2(hc[j]*crs_ref[22]/54.0)}   "
                    f"{f_2(hc[j]*crs_ref[11]/54.0)}   "
                    f"{f_2(hc[j]*crs_ref[13]/54.0)}   "
                    f"{f_2(hc[j]*crs_ref[25]/54.0)}   "
                    f"{f_2(hc[j]*crs_ref[17]/54.0)}   "
                    f"{f_2(hc[j]*crs_ref[21]/54.0)}   "
                    f"{f_2(hc[j]*crs_ref[15]/54.0)}   "
                    f"{f_2(hc[j]*crs_ref[18]/54.0)}   "
                    f"{f_2(hc[j]*crs_ref[24]/54.0)}\n"
                )

    # odgccaCH — ODGC.ca stripped-down list + course difficulty table
    with open_latin1(out("odgccaCH"), "w") as f:
        f.write("\n  name    base54HC \n")
        for j in alpha_order:
            if rnd_count[j] > 2 and ODGCmem_stat[j] == 1:
                f.write(f"{player[j]}   {f_2(hc[j])}\n")
        f.write("\n\n")
        # Course catalog — these are reference scores, never negative, so :.2f is fine.
        cnm = [
            "", "The_Shire", "Kanata", "Larrimac", "Larrimac", "Larrimac",
            "Almonte", "Almonte", "Almonte", "Ettyville_MVP", "Ettyville_MVP",
            "Ettyville_MVP", "Ettyville_Axiom", "Ettyville_Axiom",
            "Ettyville_Axiom", "Kemptville", "Kemptville", "Kemptville",
            "Camp_Fortune", "Franktown", "Phillips_Screwdriver", "UPI",
            "Centrepointe",
        ]
        icnm = [0, 15, 11, 5, 8, 9, 26, 22, 23, 1, 2, 3, 4, 5, 6, 21, 17, 25, 24, 18, 13, 16, 27]
        nnm = 22
        for j in range(1, nnm + 1):
            ref = crs_ref[icnm[j]]
            f.write(f"{cnm[j]}   {ref:.2f}   {ref / 54.0:.2f}\n")

    # atosHC — TOSS list (ODGC + Atos-list members). Includes Sandy_Row tail column.
    with open_latin1(out("atosHC"), "w") as f:
        f.write(
            "ODGC_courses_HC_list    base54HC LmacBlue  LmacYellow Almonte_Blue  "
            "Almonte_Yellow  Kanata   Mountain  KvYel KvBlue KvRed Shire Franktown "
            "Camp_Fortune Sandy_Row\n"
        )
        for j in alpha_order:
            if rnd_count[j] > 2 and (TOSSmem_stat[j] == 1 or ODGCmem_stat[j] == 1):
                f.write(
                    f"{player[j]}   {f_2(hc[j])}   "
                    f"{f_2(hc[j]*crs_ref[8]/54.0)}   "
                    f"{f_2(hc[j]*crs_ref[9]/54.0)}   "
                    f"{f_2(hc[j]*crs_ref[22]/54.0)}   "
                    f"{f_2(hc[j]*crs_ref[23]/54.0)}   "
                    f"{f_2(hc[j]*crs_ref[11]/54.0)}   "
                    f"{f_2(hc[j]*crs_ref[13]/54.0)}   "
                    f"{f_2(hc[j]*crs_ref[25]/54.0)}   "
                    f"{f_2(hc[j]*crs_ref[17]/54.0)}   "
                    f"{f_2(hc[j]*crs_ref[21]/54.0)}   "
                    f"{f_2(hc[j]*crs_ref[15]/54.0)}   "
                    f"{f_2(hc[j]*crs_ref[18]/54.0)}   "
                    f"{f_2(hc[j]*crs_ref[24]/54.0)}   "
                    f"{f_2(hc[j]*crs_ref[28]/54.0)}\n"
                )

    # evHC — Ettyville (MVP + Axiom). TOSS members also included.
    with open_latin1(out("evHC"), "w") as f:
        f.write("EV_courses_HC_list   MVP_WHI  MVP_BLU  MVP_YEL   AxiomWHI  AxiomBLU  AxiomYEL \n")
        for j in alpha_order:
            if rnd_count[j] > 2 and (EVmem_stat[j] == 1 or ODGCmem_stat[j] == 1 or TOSSmem_stat[j] == 1):
                f.write(
                    f"{player[j]}   "
                    f"{f_2(hc[j]*crs_ref[1]/54.0)}   "
                    f"{f_2(hc[j]*(crs_ref[3]-3.21)/54.0)}   "
                    f"{f_2(hc[j]*crs_ref[3]/54.0)}   "
                    f"{f_2(hc[j]*crs_ref[4]/54.0)}   "
                    f"{f_2(hc[j]*(crs_ref[6]-2.05)/54.0)}   "
                    f"{f_2(hc[j]*crs_ref[6]/54.0)}\n"
                )

    # ladiesHC — Ladies League & ODGC members
    with open_latin1(out("ladiesHC"), "w") as f:
        f.write("\nLL_courses_HC_list   base54HC  Kanata \n")
        for j in alpha_order:
            if rnd_count[j] > 2 and LLmem_stat[j] == 1 and ODGCmem_stat[j] == 1:
                f.write(
                    f"{player[j]}   {f_2(hc[j])}   "
                    f"{f_2(hc[j]*crs_ref[11]/54.0)}\n"
                )


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="ODGC handicap calculator (Python port of hc24.cpp).")
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--dat", type=Path, default=None,
                     help="Path to RoundData.dat input (default: ./RoundData.dat)")
    src.add_argument("--xlsx", type=Path, default=None,
                     help="Path to RoundData.xlsx — read scores from a worksheet")
    src.add_argument("--gsheet", nargs="?", const="auto", default=None, metavar="URL",
                     help="Read scores from the Google Sheet via the Apps Script "
                          "backend. With no value, uses the URL in ./gsheets_url.txt.")
    parser.add_argument("--sheet", default="active2025",
                        help="Worksheet name when using --xlsx or --gsheet (default: active2025)")
    parser.add_argument("--export-dat", type=Path, default=None,
                        help="Also write the parsed input back out as a .dat file "
                             "(useful for round-trip verification against the C++ tool)")
    parser.add_argument("--odgc-only", action="store_true",
                        help="Skip the golf-style output set (default: write both)")
    parser.add_argument("--golf-cap", type=float, default=5.0, metavar="K",
                        help="Soft cap '+' handicaps with tanh, asymptote at +K "
                             "(default: 5.0; pass 0 to disable compression)")
    parser.add_argument("--push-sheet", nargs="?", const="HC", default=None,
                        metavar="TAB",
                        help="After writing output files, also push the rankings "
                             "table back into a tab in the Google Sheet (default "
                             "tab name: HC). Requires gsheets_url.txt next to hc24.py.")
    args = parser.parse_args(argv)

    here = Path.cwd()
    if args.gsheet is not None:
        url = args.gsheet
        if url == "auto":
            from gsheets import load_url
            url = load_url()
        player, i_pl, tokens = parse_input_gsheet(url, args.sheet)
    elif args.xlsx is not None:
        player, i_pl, tokens = parse_input_xlsx(args.xlsx, args.sheet)
    else:
        dat_path = args.dat if args.dat is not None else (here / "RoundData.dat")
        player, i_pl, tokens = parse_input_dat(dat_path)

    if args.export_dat is not None:
        export_tokens_as_dat(player, i_pl, tokens, args.export_dat)

    # ODGC convention — current behavior, lowest HC anchored at 0.
    result = compute_handicaps(player, i_pl, tokens, anchor_at_zero=True, verbose=True)
    write_outputs(result, here)

    if not args.odgc_only:
        # Standard golf convention — HCs can be negative, shown as '+X.X'.
        # Re-runs the algorithm because the sub-zero shifting is not reversible.
        # The tanh soft-cap (default k=5) tames disc-golf's score volatility
        # so top players land in the +4 to +5 range rather than +8 to +9.
        result_golf = compute_handicaps(player, i_pl, tokens, anchor_at_zero=False, verbose=False)
        write_outputs(result_golf, here, suffix="_golf", golf_style=True,
                      golf_cap_k=args.golf_cap)

    if args.push_sheet is not None:
        if args.odgc_only:
            print(
                "WARNING: --push-sheet skipped — need both rankHC.txt and "
                "rankHC_golf.txt and --odgc-only suppresses the golf set.",
                file=__import__("sys").stderr,
            )
        else:
            from gsheets import load_url, push_hc_summary
            url = load_url()
            print(f"\nPushing rankings to {args.push_sheet!r} tab in Google Sheet…")
            result = push_hc_summary(url, here, target_sheet=args.push_sheet)
            print(f"  wrote {result['rows']} rows to tab {result['target_sheet']!r}")


if __name__ == "__main__":
    main()
