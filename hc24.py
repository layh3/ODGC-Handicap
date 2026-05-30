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

import math
from pathlib import Path


def fmt_g(x: float) -> str:
    """Mirror C++ ofstream default float formatting (precision 6, %g semantics)."""
    return f"{x:g}"


def fmt_g_golf(x: float) -> str:
    """%g formatting but with '+' prefix for negative values (golf convention:
    '+1.5' means the player is 1.5 strokes better than scratch)."""
    if x < 0:
        return f"+{-x:g}"
    return f"{x:g}"


def fmt_2f_golf(x: float) -> str:
    """Fixed 2-decimal but with '+' prefix for negative values."""
    if x < 0:
        return f"+{-x:.2f}"
    return f"{x:.2f}"


def open_latin1(path, mode="w"):
    """Output bytes in Latin-1 to match the C++ ofstream byte stream (the source
    .dat file is ISO-8859-1, and C++ does no transcoding)."""
    return open(path, mode, encoding="latin-1", newline="\n")


def compress_plus_hc(hc: float, k: float) -> float:
    """Soft-compress '+' handicaps (negative HC values) with a tanh curve.

    Applied only to negative HCs (handicaps better than scratch). Positive
    HCs pass through unchanged — high-handicappers don't need taming.

    Formula:  hc' = -k * tanh(|hc| / k)

    Behavior:
      - hc near 0           barely changed (tanh(x) ≈ x for small x)
      - hc ~ -k             ~halfway to the soft cap
      - hc → -∞             asymptote at -k (never reached, no hard ceiling)

    Disc-golf rationale: scoring volatility makes the natural HC formula
    produce '+9'-style numbers that overstate the consistent skill gap.
    A tanh compression with k=5 lands top players in the +4 to +5 range
    while leaving the rest of the field untouched. Tune via --golf-cap.
    """
    if hc >= 0 or not k:
        return hc
    return -k * math.tanh(-hc / k)


def least_squares_slope(x, y, n):
    """Mirror LeastSquares.h: 1-indexed arrays of length n+1, returns slope only."""
    sx = sum(x[i] for i in range(1, n + 1))
    sy = sum(y[i] for i in range(1, n + 1))
    sxy = sum(x[i] * y[i] for i in range(1, n + 1))
    sxx = sum(x[i] * x[i] for i in range(1, n + 1))
    denom = n * sxx - sx * sx
    if denom == 0:
        return 0.0
    return (n * sxy - sx * sy) / denom


def stdev_sample(x, mean, size):
    """Mirror stdev.h: sample-stdev over x[1..size] given precomputed mean."""
    s = sum((x[i] - mean) ** 2 for i in range(1, size + 1))
    return math.sqrt(s / (size - 1))


# Sliding scale from hcCalc.h: number of low differentials to average.
def _num_for_irck(ir: int) -> int:
    if ir < 3: return 0
    if 3 <= ir <= 5: return 1
    if 6 <= ir <= 8: return 2
    if 9 <= ir <= 10: return 3
    if 11 <= ir <= 12: return 4
    if 13 <= ir <= 14: return 5
    if 15 <= ir <= 16: return 6
    if ir == 17: return 7
    if ir == 18: return 8
    if ir == 19: return 9
    return 10  # ir >= 20


def hcc(x, ir):
    """Mirror hcCalc.h: sort the (up to 20) recent diffs ascending, average the
    leading `num`, scale by 0.96, cap at 36."""
    num = _num_for_irck(ir)
    irmax = min(20, ir)
    y = sorted(x[1:irmax + 1])  # ascending
    total = sum(y[:num]) if num > 0 else 0.0
    result = (total * 0.96 / num) if num > 0 else 0.0
    return min(result, 36.0)


# --- input parsing ---------------------------------------------------------

# Course code list and seed reference-score history (from initialize_variables.h).
NUM_CRS = 30
# Indexed to match the C++ 0-indexed courseID[] exactly. The course-match loop
# starts at index 1, so the "jeu" entry at index 0 is never matched (dead slot).
# Critical lookups depend on these specific indices: crs_ref[7]==unq triggers the
# one-shot ref-score rule; the icnm[] array used for the odgccaCH catalog block
# encodes these positions directly.
COURSE_ID = [
    "jeu",  # 0 — dead slot (never matched)
    "epw",  # 1
    "epb",  # 2
    "epy",  # 3
    "eiw",  # 4
    "eib",  # 5
    "eiy",  # 6
    "unq",  # 7 — special-case: one-shot layout
    "lmb",  # 8
    "lmy",  # 9
    "alm0", # 10
    "kan",  # 11
    "kpv",  # 12
    "mtn",  # 13
    "cur",  # 14
    "shr",  # 15
    "upi",  # 16
    "kvb",  # 17
    "ffw",  # 18
    "rhl",  # 19
    "alm",  # 20
    "kvr",  # 21
    "alb",  # 22
    "aly",  # 23
    "cf",   # 24
    "kvy",  # 25
    "alr",  # 26
    "ctp",  # 27
    "sr",   # 28 — Sandy Row
    "sro",  # 29 — Sandy Row (alt layout)
]

# Seed top-5 reference scores per course (most recent at highest index).
SEEDS = {
    1: [59.0],
    2: [63.4, 61.2, 57.9, 59.0, 62.2],
    3: [65.2, 64.4, 61.8, 64.0, 65.2],
    4: [56.6],
    5: [56.4, 52.8, 52.8, 54.2, 56.2],
    6: [55.8, 70.2, 69.6, 56.2, 56.6],
    8: [53.0, 56.8],
    9: [57.6, 60.6],
    10: [52.4, 52.2, 52.6, 53.6, 56.6],
    11: [49.6, 45.8, 51.8, 46.0, 51.6],
    13: [57.6, 55.0, 56.6, 55.8, 54.8],
    15: [51.6, 50.0, 51.8, 52.8, 52.0],
}


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


def compute_handicaps(player, i_pl, tokens, *, anchor_at_zero=True, verbose=True):
    """Run the full algorithm and return final state.

    anchor_at_zero=True   ODGC convention: when any HC goes negative, anchor
                          the lowest at 0 and shift all other HCs/differentials
                          up by the same amount (no '+' handicaps).
    anchor_at_zero=False  Standard golf convention: HCs are computed naturally
                          and may be negative. Display as '+X.X' downstream.
    verbose=True          Print unknown-course warning to stderr (only the
                          first call in a session needs to.)
    """
    pos = 0
    def take():
        nonlocal pos
        t = tokens[pos]
        pos += 1
        return t

    # Line 2: "end_2020_hc" "HC" <seed HCs>
    take(); take()  # discard label tokens
    hc = [0.0] * (i_pl + 2)
    # Track "this player has an established HC entering each round" separately
    # from the HC value itself. In ODGC mode the C++ used `hc[j] > -0.9` as a
    # proxy (since real HCs are always ≥0). In golf mode HCs can legitimately
    # be below -0.9, so we need an explicit flag.
    has_hc = [False] * (i_pl + 2)
    for j in range(1, i_pl + 1):
        hc[j] = float(take())
        if hc[j] > -0.9:  # any seed value other than the -1 sentinel
            has_hc[j] = True

    # Lines 3-9: 7 lines of seed differentials (no labels; just values).
    # Values < 90 are real; 90/99.9/100 are sentinels.
    rnd_count = [0] * (i_pl + 2)
    diff = [[0.0] * 600 for _ in range(i_pl + 2)]
    d_ry = [[0] * 600 for _ in range(i_pl + 2)]
    for k in range(1, 8):
        for j in range(1, i_pl + 1):
            dum = float(take())
            if dum < 90.0:
                rnd_count[j] += 1
                diff[j][k] = dum
                d_ry[j][k] = 20  # seed year — 2020

    # Lines 10-13: membership flags
    ODGCmem_stat = [0] * (i_pl + 2)
    TOSSmem_stat = [0] * (i_pl + 2)
    EVmem_stat = [0] * (i_pl + 2)
    LLmem_stat = [0] * (i_pl + 2)
    for stat_array in (ODGCmem_stat, TOSSmem_stat, EVmem_stat, LLmem_stat):
        take(); take()  # label tokens (e.g. "ODGCmember" "status")
        for j in range(1, i_pl + 1):
            stat_array[j] = int(take())

    # --- course reference state, seeded ---
    course_rnds = [0] * NUM_CRS
    icrs_ref = [[0.0] * NUM_CRS for _ in range(6)]  # icrs_ref[1..5][course]
    for c, vals in SEEDS.items():
        course_rnds[c] = len(vals)
        for i, v in enumerate(vals, 1):
            icrs_ref[i][c] = v
    crs_ref = [0.0] * 35
    prevcrs_ref = [0.0] * 35
    for j in range(1, NUM_CRS):
        if course_rnds[j] > 0:
            s = sum(icrs_ref[i][j] for i in range(1, course_rnds[j] + 1))
            crs_ref[j] = s / course_rnds[j]

    # --- pre-scan rounds: build course refs in chronological order ---
    # (C++ does this inline with reading; we tokenize then iterate.)
    # We allocate after we know how many rounds; cap at 500 to match C++ n_rounds.
    n_rounds_cap = 600
    ry = [0] * n_rounds_cap
    event = [""] * n_rounds_cap
    course = [""] * n_rounds_cap
    score = [[0] * (i_pl + 2) for _ in range(n_rounds_cap)]
    rnd_crs_ref = [0.0] * n_rounds_cap

    unknown_courses: dict[str, int] = {}
    i_rc = 0
    while pos < len(tokens):
        # Need at least 3 tokens to start a round header.
        if pos + 3 > len(tokens):
            break
        # Peek event without committing.
        candidate_ev = tokens[pos + 1]
        if len(candidate_ev) < 3:
            break
        try:
            year_val = int(tokens[pos])
        except ValueError:
            break
        i_rc += 1
        ry[i_rc] = year_val
        pos += 1
        event[i_rc] = take()
        course[i_rc] = take()
        # Read i_pl scores (file always has all of them; guard anyway).
        for j in range(1, i_pl + 1):
            if pos >= len(tokens):
                score[i_rc][j] = 0
            else:
                score[i_rc][j] = int(take())

        # Course ref update (same as C++ during read).
        crs = course[i_rc]
        ev = event[i_rc]
        i_c = 0
        for j in range(1, NUM_CRS):
            if crs == COURSE_ID[j]:
                i_c = j
        if i_c == 0 and not (ev and ev[0] == "x"):
            # The C++ tolerates this silently and lets crs_ref[0]=0 corrupt
            # downstream c_fac → divide-by-zero → NaN/inf cascade. Track it so
            # we can warn the operator.
            unknown_courses[crs] = unknown_courses.get(crs, 0) + 1
        if ev and ev[0] == "x":
            i_c = 0  # B-tier excluded from course reference
        course_rnds[i_c] += 1
        irnd_sorted = sorted(s for s in (score[i_rc][j] for j in range(1, i_pl + 1)) if s > 0)
        if i_c > 0 and len(irnd_sorted) >= 5:
            rnd_std = sum(irnd_sorted[:5]) / 5.0
            if course_rnds[i_c] > 5:
                for i in range(1, 5):
                    icrs_ref[i][i_c] = icrs_ref[i + 1][i_c]
                icrs_ref[5][i_c] = rnd_std
                cr_t = 5
            else:
                icrs_ref[course_rnds[i_c]][i_c] = rnd_std
                cr_t = course_rnds[i_c]
            cr_s = sum(icrs_ref[i][i_c] for i in range(1, cr_t + 1))
            prevcrs_ref[i_c] = crs_ref[i_c]
            crs_ref[i_c] = cr_s / cr_t
            if i_c == 7:
                # 'unq' layout uses just this one round's ref score.
                crs_ref[i_c] = rnd_std
        rnd_crs_ref[i_rc] = crs_ref[i_c]

    if unknown_courses and verbose:
        import sys
        print("WARNING: unknown course codes — treated as par-54 reference "
              "(c_fac=1.0). The original C++ would NaN-cascade on these.",
              file=sys.stderr)
        for crs_code, n in sorted(unknown_courses.items()):
            print(f"  {crs_code!r}: {n} round(s)", file=sys.stderr)

    # --- main round loop -----------------------------------------------------
    hc0 = [0.0] * (i_pl + 2)
    in_rnd_count = [0] * (i_pl + 2)
    toss19_rnd_count = [0] * (i_pl + 2)  # legacy — always 0 in current data
    # Reset rnd_count to seed-only state and re-derive per round, mirroring C++.
    # (C++ retains seed counts and keeps adding; so do we.)
    # We already accumulated seed counts above; main loop continues from there.

    rnd_size_cap = 95
    rnd_scores = [0.0] * rnd_size_cap
    rnd_hc = [0.0] * rnd_size_cap
    rnd_ascores = [0.0] * rnd_size_cap
    rnd_adj_sc = [0.0] * rnd_size_cap
    rnd_adj_gen = [0.0] * rnd_size_cap
    rnd_sc_delta = [0.0] * rnd_size_cap
    player_pt = [0] * rnd_size_cap

    ss_id = [0] * 12
    ss_diff_corr = [0.0] * 12
    ss_numc = [0] * 12

    for r in range(1, i_rc + 1):
        # Pre-check: a round needs ≥2 players with an established HC for the
        # round-scratch / stddev / slope calc to be meaningful. PDGA-style
        # division splits (e.g. a single-player FA1 or FA40) can leave only
        # one ODGC member in a pool. Skip these rounds entirely so they
        # don't affect anyone's HC. (The .dat never had this; only matters
        # for xlsx-imported tournament data.)
        established_in_round = sum(
            1 for j in range(1, i_pl + 1)
            if score[r][j] > 0 and has_hc[j]
        )
        if established_in_round < 2:
            continue

        # Year-boundary stale-HC reset: if last round was >2 years ago, reset to
        # 3 seed diffs at current HC.
        if r > 1 and ry[r] > ry[r - 1]:
            for j in range(1, i_pl + 1):
                if rnd_count[j] > 2 and ry[r] - d_ry[j][rnd_count[j]] > 2:
                    rnd_count[j] = 3
                    for k in range(1, 4):
                        diff[j][k] = hc[j] / 0.96
                        d_ry[j][k] = ry[r]

        # Per-round state
        rnd_size = 0
        rnd_asize = 0
        rnd_sum = 0
        rnd_diff = 0.0
        rnd_rej = 0
        q_subzero = 0.0
        qzeroHCid = 0
        diff_corr = 0.0
        i_zero_flag = 0
        i_zfc = 0
        id_zfc = 0
        numcz = 1

        # Course factor
        i_c = 0
        for j in range(1, NUM_CRS):
            if course[r] == COURSE_ID[j]:
                i_c = j
        c_fac = crs_ref[i_c] / 54.0 if i_c else 1.0
        oc_fac = prevcrs_ref[i_c] / 54.0 if i_c else c_fac
        if i_c and prevcrs_ref[i_c] == 0:
            oc_fac = c_fac

        # Snapshot HCs at start of round (used as hc0 inside)
        for j in range(1, i_pl + 1):
            hc0[j] = hc[j]

        # Build round pools
        for j in range(1, i_pl + 1):
            sc = score[r][j]
            if sc > 0:
                rnd_count[j] += 1
                rnd_size += 1
                player_pt[rnd_size] = j
                rnd_scores[rnd_size] = sc
                # rnd_adj_gen used only for sort/display in C++; keep for parity
                rnd_adj_gen[rnd_size] = sc - hc0[j] * c_fac
                if rnd_count[j] <= 3:
                    rnd_adj_gen[rnd_size] = sc

                if has_hc[j]:
                    rnd_asize += 1
                    rnd_ascores[rnd_asize] = sc
                    rnd_adj_sc[rnd_asize] = sc - hc0[j] * c_fac
                    rnd_hc[rnd_asize] = hc0[j] * c_fac
                    rnd_diff += rnd_adj_sc[rnd_asize]
                    rnd_sum += sc

        if rnd_asize == 0:
            continue  # safety: no established players in round

        rnd_scratch = rnd_diff / rnd_asize  # unfiltered

        # Outlier filter: drop adjusted scores > mean + 1.4σ
        rnd_std = stdev_sample(rnd_adj_sc, rnd_scratch, rnd_asize)
        rnd_upperFilter = rnd_scratch + 1.40 * rnd_std
        for j in range(1, rnd_asize + 1):
            if rnd_adj_sc[j] > rnd_upperFilter:
                rnd_rej += 1
                rnd_diff -= rnd_adj_sc[j]

        denom = rnd_asize - rnd_rej
        if denom > 0:
            rnd_scratch = rnd_diff / denom

        for j in range(1, rnd_asize + 1):
            rnd_sc_delta[j] = rnd_ascores[j] - rnd_scratch

        # Slope = least-squares regression of (score - scratch) vs HC, * 113, clamped.
        slp = least_squares_slope(rnd_sc_delta, rnd_hc, rnd_asize)
        toest = slp * 113
        slp = min(max(95.0, toest), 165.0)

        # Differentials + per-player HC update
        for j in range(1, rnd_size + 1):
            k = player_pt[j]
            diff[k][rnd_count[k]] = (rnd_scores[j] - rnd_scratch) * (113 / slp) / c_fac
            d_ry[k][rnd_count[k]] = ry[r]

            # Pack last-20 diffs into dfk[1..]
            i_in = 1
            if rnd_count[k] > 20:
                i_in = rnd_count[k] - 19
            dfk = [0.0] * 21
            for i in range(i_in, rnd_count[k] + 1):
                dfk[i - i_in + 1] = diff[k][i]

            irck = rnd_count[k]
            if irck > 20:
                irck = 20
            if rnd_count[k] > 2:
                hc[k] = hcc(dfk, irck)
                has_hc[k] = True  # established (will be true going forward)

            # Sub-zero detection: schedule a global shift so the lowest HC
            # anchors at 0 (ODGC convention — no '+' handicaps). Skipped
            # entirely in golf mode: the player's HC simply stays negative.
            if anchor_at_zero and rnd_count[k] > 2 and hc[k] < 0.0:
                q_subzero = hc[k]
                qzeroHCid = k
                i_zero_flag = 1
                i_zfc += 1
                ss_id[i_zfc] = k
                numc = _num_for_irck(irck)
                diff_corr0 = q_subzero * numc / 0.96 / 10
                ss_diff_corr[i_zfc] = diff_corr0
                ss_numc[i_zfc] = numc
                if diff_corr0 < diff_corr:
                    diff_corr = diff_corr0
                    id_zfc = k
                    numcz = numc
                # If this isn't the new lowest, id_zfc/numcz keep their prior values.
                q_subzero = hc[id_zfc]
                qzeroHCid = id_zfc

        # Sub-zero shift: ODGC convention — anchor lowest HC at 0, shift others up.
        # Skipped entirely in golf mode (anchor_at_zero=False) so HCs can stay negative.
        if anchor_at_zero and i_zero_flag == 1:
            for j in range(1, i_pl + 1):
                if rnd_count[j] > 2:
                    hc[j] -= q_subzero * numcz / 10
                if j == qzeroHCid:
                    hc[j] = 0
                    if numcz < 10:
                        # Zero out the player's `numcz` most-recent diffs so the
                        # HC stays anchored at 0.
                        for l in range(rnd_count[j], rnd_count[j] - numcz, -1):
                            diff[j][l] = 0.0
                # Shift all this player's diffs by diff_corr (negative → upshift).
                for l in range(1, rnd_count[j] + 1):
                    diff[j][l] -= diff_corr

    # Cap final HCs at 36 (only for players with established HC)
    for j in range(1, i_pl + 1):
        if rnd_count[j] > 2 and hc[j] > 36.0:
            hc[j] = 36.0

    return {
        "player": player,
        "i_pl": i_pl,
        "hc": hc,
        "rnd_count": rnd_count,
        "in_rnd_count": in_rnd_count,
        "toss19_rnd_count": toss19_rnd_count,
        "ODGCmem_stat": ODGCmem_stat,
        "TOSSmem_stat": TOSSmem_stat,
        "EVmem_stat": EVmem_stat,
        "LLmem_stat": LLmem_stat,
        "crs_ref": crs_ref,
    }


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


if __name__ == "__main__":
    main()
