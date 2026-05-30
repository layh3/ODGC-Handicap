"""ODGC handicap algorithm — pure-compute kernel shared by the CLI and the
Cloudflare Worker.

No I/O. Caller's responsibility to read input (from .dat, xlsx, Google Sheet,
or any other source) and shape it into the (player, i_pl, tokens) tuple
that compute_handicaps expects.

Faithful 1:1 port of hc24.cpp / hcCalc.h / LeastSquares.h / stdev.h —
hc24.py used to be the only home of this code; it's been moved here so
that the worker can import the same algorithm without dragging in the
CLI's file-system helpers.

Arrays are 1-indexed to mirror the C++ source line-by-line.
"""

from __future__ import annotations

import math


# --- output formatting ----------------------------------------------------

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
    while leaving the rest of the field untouched.
    """
    if hc >= 0 or not k:
        return hc
    return -k * math.tanh(-hc / k)


# --- math helpers ---------------------------------------------------------

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


def _num_for_irck(ir: int) -> int:
    """Sliding scale from hcCalc.h: how many low differentials to average."""
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
    y = sorted(x[1:irmax + 1])
    total = sum(y[:num]) if num > 0 else 0.0
    result = (total * 0.96 / num) if num > 0 else 0.0
    return min(result, 36.0)


# --- course catalog -------------------------------------------------------

NUM_CRS = 30
# Indexed to match the C++ 0-indexed courseID[] exactly. The course-match
# loop starts at index 1, so the "jeu" entry at index 0 is never matched
# (dead slot). Critical lookups depend on these specific indices:
# crs_ref[7]==unq triggers the one-shot ref-score rule; the icnm[] array used
# for the odgccaCH catalog block encodes these positions directly.
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


# --- the algorithm --------------------------------------------------------

def compute_handicaps(player, i_pl, tokens, *, anchor_at_zero=True, verbose=True):
    """Run the full algorithm and return final state.

    anchor_at_zero=True   ODGC convention: when any HC goes negative, anchor
                          the lowest at 0 and shift all other HCs/differentials
                          up by the same amount (no '+' handicaps).
    anchor_at_zero=False  Standard golf convention: HCs are computed naturally
                          and may be negative. Display as '+X.X' downstream.
    verbose=True          Print unknown-course warning (only the first call in
                          a session needs to).
    """
    pos = 0

    def take():
        nonlocal pos
        t = tokens[pos]
        pos += 1
        return t

    # Line 2: "end_2020_hc" "HC" <seed HCs>
    take(); take()
    hc = [0.0] * (i_pl + 2)
    has_hc = [False] * (i_pl + 2)
    for j in range(1, i_pl + 1):
        hc[j] = float(take())
        if hc[j] > -0.9:
            has_hc[j] = True

    # Lines 3-9: 7 lines of seed differentials.
    rnd_count = [0] * (i_pl + 2)
    diff = [[0.0] * 600 for _ in range(i_pl + 2)]
    d_ry = [[0] * 600 for _ in range(i_pl + 2)]
    for k in range(1, 8):
        for j in range(1, i_pl + 1):
            dum = float(take())
            if dum < 90.0:
                rnd_count[j] += 1
                diff[j][k] = dum
                d_ry[j][k] = 20

    # Lines 10-13: membership flags
    ODGCmem_stat = [0] * (i_pl + 2)
    TOSSmem_stat = [0] * (i_pl + 2)
    EVmem_stat = [0] * (i_pl + 2)
    LLmem_stat = [0] * (i_pl + 2)
    for stat_array in (ODGCmem_stat, TOSSmem_stat, EVmem_stat, LLmem_stat):
        take(); take()
        for j in range(1, i_pl + 1):
            stat_array[j] = int(take())

    # Course reference state, seeded
    course_rnds = [0] * NUM_CRS
    icrs_ref = [[0.0] * NUM_CRS for _ in range(6)]
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

    # Pre-scan rounds: build course refs in chronological order
    n_rounds_cap = 600
    ry = [0] * n_rounds_cap
    event = [""] * n_rounds_cap
    course = [""] * n_rounds_cap
    score = [[0] * (i_pl + 2) for _ in range(n_rounds_cap)]
    rnd_crs_ref = [0.0] * n_rounds_cap

    unknown_courses: dict[str, int] = {}
    i_rc = 0
    while pos < len(tokens):
        if pos + 3 > len(tokens):
            break
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
        for j in range(1, i_pl + 1):
            if pos >= len(tokens):
                score[i_rc][j] = 0
            else:
                score[i_rc][j] = int(take())

        crs = course[i_rc]
        ev = event[i_rc]
        i_c = 0
        for j in range(1, NUM_CRS):
            if crs == COURSE_ID[j]:
                i_c = j
        if i_c == 0 and not (ev and ev[0] == "x"):
            unknown_courses[crs] = unknown_courses.get(crs, 0) + 1
        if ev and ev[0] == "x":
            i_c = 0
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
                crs_ref[i_c] = rnd_std
        rnd_crs_ref[i_rc] = crs_ref[i_c]

    if unknown_courses and verbose:
        import sys
        print("WARNING: unknown course codes — treated as par-54 reference "
              "(c_fac=1.0). The original C++ would NaN-cascade on these.",
              file=sys.stderr)
        for crs_code, n in sorted(unknown_courses.items()):
            print(f"  {crs_code!r}: {n} round(s)", file=sys.stderr)

    # --- main round loop ---
    hc0 = [0.0] * (i_pl + 2)
    in_rnd_count = [0] * (i_pl + 2)
    toss19_rnd_count = [0] * (i_pl + 2)

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
        # Pre-check: round needs ≥2 established players to compute scratch/stddev.
        established_in_round = sum(
            1 for j in range(1, i_pl + 1)
            if score[r][j] > 0 and has_hc[j]
        )
        if established_in_round < 2:
            continue

        # Year-boundary stale-HC reset
        if r > 1 and ry[r] > ry[r - 1]:
            for j in range(1, i_pl + 1):
                if rnd_count[j] > 2 and ry[r] - d_ry[j][rnd_count[j]] > 2:
                    rnd_count[j] = 3
                    for k in range(1, 4):
                        diff[j][k] = hc[j] / 0.96
                        d_ry[j][k] = ry[r]

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

        i_c = 0
        for j in range(1, NUM_CRS):
            if course[r] == COURSE_ID[j]:
                i_c = j
        c_fac = crs_ref[i_c] / 54.0 if i_c else 1.0
        oc_fac = prevcrs_ref[i_c] / 54.0 if i_c else c_fac
        if i_c and prevcrs_ref[i_c] == 0:
            oc_fac = c_fac

        for j in range(1, i_pl + 1):
            hc0[j] = hc[j]

        for j in range(1, i_pl + 1):
            sc = score[r][j]
            if sc > 0:
                rnd_count[j] += 1
                rnd_size += 1
                player_pt[rnd_size] = j
                rnd_scores[rnd_size] = sc
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
            continue

        rnd_scratch = rnd_diff / rnd_asize
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

        slp = least_squares_slope(rnd_sc_delta, rnd_hc, rnd_asize)
        toest = slp * 113
        slp = min(max(95.0, toest), 165.0)

        for j in range(1, rnd_size + 1):
            k = player_pt[j]
            diff[k][rnd_count[k]] = (rnd_scores[j] - rnd_scratch) * (113 / slp) / c_fac
            d_ry[k][rnd_count[k]] = ry[r]

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
                has_hc[k] = True

            # Sub-zero detection (ODGC mode only)
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
                q_subzero = hc[id_zfc]
                qzeroHCid = id_zfc

        # Sub-zero shift (ODGC mode only)
        if anchor_at_zero and i_zero_flag == 1:
            for j in range(1, i_pl + 1):
                if rnd_count[j] > 2:
                    hc[j] -= q_subzero * numcz / 10
                if j == qzeroHCid:
                    hc[j] = 0
                    if numcz < 10:
                        for l in range(rnd_count[j], rnd_count[j] - numcz, -1):
                            diff[j][l] = 0.0
                for l in range(1, rnd_count[j] + 1):
                    diff[j][l] -= diff_corr

    # Cap final HCs at 36
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
