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


def open_latin1(path, mode="w"):
    """Output bytes in Latin-1 to match the C++ ofstream byte stream (the source
    .dat file is ISO-8859-1, and C++ does no transcoding)."""
    return open(path, mode, encoding="latin-1", newline="\n")


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
NUM_CRS = 28
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


def parse_input(path: Path):
    """Return a parsed-input bundle from RoundData.dat."""
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


def main():
    here = Path.cwd()
    player, i_pl, tokens = parse_input(here / "RoundData.dat")

    pos = 0
    def take():
        nonlocal pos
        t = tokens[pos]
        pos += 1
        return t

    # Line 2: "end_2020_hc" "HC" <seed HCs>
    take(); take()  # discard label tokens
    hc = [0.0] * (i_pl + 2)
    for j in range(1, i_pl + 1):
        hc[j] = float(take())

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

                if hc[j] > -0.9:
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

            # Sub-zero detection: if this player just went negative, schedule a
            # global shift so the lowest HC anchors at 0 (no "+ handicap" in
            # the current system).
            if rnd_count[k] > 2 and hc[k] < 0.0:
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

        # Sub-zero shift: anchor lowest HC at 0, shift all others up by the same amount.
        if i_zero_flag == 1:
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

    # --- output files --------------------------------------------------------

    with open_latin1(here / "player_rounds.txt", "w") as f:
        for j in range(1, i_pl + 1):
            f.write(f"{player[j]} HC =  {fmt_g(hc[j])}  rounds played = {rnd_count[j] - in_rnd_count[j]}\n")

    # rankHC.txt — sorted ascending by HC; same bubble-sort as C++
    rank_hc = list(range(0, i_pl + 2))  # rank_hc[1..i_pl] starts as identity
    for ij in range(1, i_pl):
        for j in range(1, i_pl - ij + 1):
            if hc[rank_hc[j]] > hc[rank_hc[j + 1]]:
                rank_hc[j], rank_hc[j + 1] = rank_hc[j + 1], rank_hc[j]

    with open_latin1(here / "rankHC.txt", "w") as f:
        f.write("\n\n")
        i_rank = 0
        for j in range(1, i_pl + 1):
            idx = rank_hc[j]
            if rnd_count[idx] > 2:
                i_rank += 1
                f.write(f" rank =  {i_rank}  {player[idx]} HC =  {fmt_g(hc[idx])}  rounds played = {rnd_count[idx] - in_rnd_count[idx]}\n")

    # alphHC.txt — natural file order is already alphabetical.
    # `mem_stat` array in the C++ is declared but never populated, so the
    # "current member?" field is always "NO". Reproduce.
    with open_latin1(here / "alphHC.txt", "w") as f:
        for j in range(1, i_pl + 1):
            if rnd_count[j] > 2:
                f.write(
                    f"{player[j]} HC =  {fmt_g(hc[j])}  "
                    f"rounds played = {rnd_count[j] - in_rnd_count[j]}  "
                    f"current member? - NO 2019TOSSrnds = {toss19_rnd_count[j]}\n"
                )

    # kvHC.txt — Kemptville (Ferguson + Mountain), all qualified players
    with open_latin1(here / "kvHC.txt", "w") as f:
        f.write("\nKemptville_courses_HC_list    base54HC Ferguson   Mountain  \n")
        for j in range(1, i_pl + 1):
            if rnd_count[j] > 2:
                f.write(
                    f"{player[j]}   "
                    f"{hc[j]:.2f}   "
                    f"{hc[j] * crs_ref[12] / 54.0:.2f}   "
                    f"{hc[j] * crs_ref[13] / 54.0:.2f}   "
                    f"{hc[j] * crs_ref[1] / 54.0:.2f}\n"
                )

    # odgcHC.txt — ODGC members, multi-course scaled
    with open_latin1(here / "odgcHC.txt", "w") as f:
        f.write(
            "\nODGC_courses_HC_list    base54HC LmacBlue  LmacYellow Almonte_blue   "
            "Kanata   Mountain  KvYel KvBlue KvRed Shire Franktown Camp_Fortune\n"
        )
        for j in range(1, i_pl + 1):
            if rnd_count[j] > 2 and ODGCmem_stat[j] == 1:
                f.write(
                    f"{player[j]}   {hc[j]:.2f}   "
                    f"{hc[j]*crs_ref[8]/54.0:.2f}   "
                    f"{hc[j]*crs_ref[9]/54.0:.2f}   "
                    f"{hc[j]*crs_ref[22]/54.0:.2f}   "
                    f"{hc[j]*crs_ref[11]/54.0:.2f}   "
                    f"{hc[j]*crs_ref[13]/54.0:.2f}   "
                    f"{hc[j]*crs_ref[25]/54.0:.2f}   "
                    f"{hc[j]*crs_ref[17]/54.0:.2f}   "
                    f"{hc[j]*crs_ref[21]/54.0:.2f}   "
                    f"{hc[j]*crs_ref[15]/54.0:.2f}   "
                    f"{hc[j]*crs_ref[18]/54.0:.2f}   "
                    f"{hc[j]*crs_ref[24]/54.0:.2f}\n"
                )

    # odgccaCH.txt — ODGC.ca stripped-down list + course difficulty table
    with open_latin1(here / "odgccaCH.txt", "w") as f:
        f.write("\n  name    base54HC \n")
        for j in range(1, i_pl + 1):
            if rnd_count[j] > 2 and ODGCmem_stat[j] == 1:
                f.write(f"{player[j]}   {hc[j]:.2f}\n")
        f.write("\n\n")
        # Course catalog — C++ stream state is still fixed/setprecision(2) here
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

    # atosHC.txt — TOSS list (ODGC + Atos-list members)
    with open_latin1(here / "atosHC.txt", "w") as f:
        f.write(
            "ODGC_courses_HC_list    base54HC LmacBlue  LmacYellow Almonte_Blue  "
            "Almonte_Yellow  Kanata   Mountain  KvYel KvBlue KvRed Shire Franktown "
            "Camp_Fortune\n"
        )
        for j in range(1, i_pl + 1):
            if rnd_count[j] > 2 and (TOSSmem_stat[j] == 1 or ODGCmem_stat[j] == 1):
                f.write(
                    f"{player[j]}   {hc[j]:.2f}   "
                    f"{hc[j]*crs_ref[8]/54.0:.2f}   "
                    f"{hc[j]*crs_ref[9]/54.0:.2f}   "
                    f"{hc[j]*crs_ref[22]/54.0:.2f}   "
                    f"{hc[j]*crs_ref[23]/54.0:.2f}   "
                    f"{hc[j]*crs_ref[11]/54.0:.2f}   "
                    f"{hc[j]*crs_ref[13]/54.0:.2f}   "
                    f"{hc[j]*crs_ref[25]/54.0:.2f}   "
                    f"{hc[j]*crs_ref[17]/54.0:.2f}   "
                    f"{hc[j]*crs_ref[21]/54.0:.2f}   "
                    f"{hc[j]*crs_ref[15]/54.0:.2f}   "
                    f"{hc[j]*crs_ref[18]/54.0:.2f}   "
                    f"{hc[j]*crs_ref[24]/54.0:.2f}\n"
                )

    # evHC.txt — Ettyville (MVP + Axiom)
    with open_latin1(here / "evHC.txt", "w") as f:
        f.write("EV_courses_HC_list   MVP_WHI  MVP_BLU  MVP_YEL   AxiomWHI  AxiomBLU  AxiomYEL \n")
        for j in range(1, i_pl + 1):
            if rnd_count[j] > 2 and (EVmem_stat[j] == 1 or ODGCmem_stat[j] == 1):
                f.write(
                    f"{player[j]}   "
                    f"{hc[j]*crs_ref[1]/54.0:.2f}   "
                    f"{hc[j]*(crs_ref[3]-3.21)/54.0:.2f}   "
                    f"{hc[j]*crs_ref[3]/54.0:.2f}   "
                    f"{hc[j]*crs_ref[4]/54.0:.2f}   "
                    f"{hc[j]*(crs_ref[6]-2.05)/54.0:.2f}   "
                    f"{hc[j]*crs_ref[6]/54.0:.2f}\n"
                )

    # ladiesHC.txt — Ladies League & ODGC members
    with open_latin1(here / "ladiesHC.txt", "w") as f:
        f.write("\nLL_courses_HC_list   base54HC  Kanata \n")
        for j in range(1, i_pl + 1):
            if rnd_count[j] > 2 and LLmem_stat[j] == 1 and ODGCmem_stat[j] == 1:
                f.write(
                    f"{player[j]}   {hc[j]:.2f}   "
                    f"{hc[j]*crs_ref[11]/54.0:.2f}\n"
                )


if __name__ == "__main__":
    main()
