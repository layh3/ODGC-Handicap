"""ODGC Handicap — Cloudflare Worker entry point.

Receives a POST from the frontend with a UDisc/PDGA URL (or PDGA event id)
plus event name and year, runs the full ingest flow against the Google
Sheet, and returns a JSON status. The same matching/dedup/algorithm code
the CLI uses is imported from hc_algorithm / hc_matching / hc_parsing.

Endpoints:
    GET  /            short help text
    POST /            run an ingest
        {
          "url": "https://udisc.com/events/.../leaderboard?round=1",
          "event": "TOSS05",
          "year": 26,
          "password": "<shared secret>"   (required)
        }
"""

import datetime as _dt
import json as _json

from workers import Response  # type: ignore[import-not-found]

from hc_algorithm import compute_handicaps, fmt_2f_golf
from hc_matching import match_player, to_lastname_first, guess_course_from_layout
from hc_parsing import (
    parse_udisc_leaderboard, parse_pdga_event,
    UDISC_USER_AGENT, PDGA_USER_AGENT,
)
import gsheets_worker as gs
from worker_io import fetch_text


HELP = (
    "ODGC HC Worker — alive.\n\n"
    "POST JSON: {url, event, year, password}\n"
)

# CORS — the frontend lives at a different origin (CF Pages) so the browser
# enforces a preflight + ACAO check. We allow any origin since the password
# gate is the real auth.
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
}


async def on_fetch(request, env):
    if request.method == "OPTIONS":
        return Response("", headers=CORS_HEADERS)
    if request.method == "GET":
        h = {"content-type": "text/plain"}
        h.update(CORS_HEADERS)
        return Response(HELP, headers=h)
    if request.method != "POST":
        return Response("method not allowed", status=405, headers=CORS_HEADERS)

    try:
        body = _json.loads(await request.text() or "{}")
    except Exception as e:
        return _json_resp({"ok": False, "error": f"bad json: {e}"}, status=400)

    # Password gate. env.SHARED_PASSWORD is set via `wrangler secret put`.
    shared = getattr(env, "SHARED_PASSWORD", None) or ""
    if not shared:
        return _json_resp(
            {"ok": False, "error": "server missing SHARED_PASSWORD secret"},
            status=500,
        )
    if body.get("password") != shared:
        return _json_resp({"ok": False, "error": "wrong password"}, status=401)

    apps_url = getattr(env, "APPS_SCRIPT_URL", None) or ""
    if not apps_url:
        return _json_resp(
            {"ok": False, "error": "server missing APPS_SCRIPT_URL"}, status=500
        )

    url = (body.get("url") or "").strip()
    event = (body.get("event") or "").strip()
    year = body.get("year")
    sheet = body.get("sheet") or "active2025"

    if not url:
        return _json_resp({"ok": False, "error": "url required"}, status=400)
    if not event:
        return _json_resp({"ok": False, "error": "event required"}, status=400)
    try:
        year = int(year)
    except (TypeError, ValueError):
        return _json_resp({"ok": False, "error": "year must be a 2-digit int"},
                          status=400)

    log: list[str] = []
    try:
        result = await _run_ingest(apps_url, url, event, year, sheet, log)
        return _json_resp({"ok": True, "log": log, "result": result})
    except Exception as e:
        log.append(f"ERROR: {e}")
        return _json_resp({"ok": False, "error": str(e), "log": log},
                          status=500)


# --- the ingest flow ------------------------------------------------------

async def _run_ingest(apps_url, url, event, year, sheet, log):
    kind = _detect_kind(url)
    log.append(f"detected {kind} source")

    pools = await _fetch_pools(kind, url, event, log)
    log.append(f"parsed {len(pools)} pool(s)")

    log.append("pulling sheet…")
    data = await gs.pull(apps_url, sheet)
    roster = gs.load_roster_from_data(data)
    roster_names = [n for _, n in roster]
    name_to_col = {n: c for c, n in roster}
    log.append(f"  roster: {len(roster_names)} players")

    pending_player_inserts: list[tuple[int, str]] = []
    appended: list[dict] = []
    for pool in pools:
        scores_by_col: dict[int, int] = {}
        added: list[tuple] = []
        for player_in, score in pool["players"]:
            roster_name, _why = match_player(player_in, roster_names)
            if roster_name is None:
                roster_name = to_lastname_first(player_in)
                last_col = max(c for c, _ in roster)
                new_col = last_col + 1
                pending_player_inserts.append((last_col, roster_name))
                roster.append((new_col, roster_name))
                roster_names.append(roster_name)
                name_to_col[roster_name] = new_col
                added.append((player_in, roster_name, score))
                col = new_col
            else:
                col = name_to_col[roster_name]
            scores_by_col[col] = score
        appended.append({
            "course": pool["course"],
            "event_name": pool["event_name"],
            "scores": scores_by_col,
            "n_total": len(scores_by_col),
            "n_added": len(added),
        })

    to_write: list[dict] = []
    skipped_dups: list[dict] = []
    for entry in appended:
        dup = gs.find_duplicate_row_in_data(data, year, entry["scores"])
        if dup is None:
            to_write.append(entry)
            continue
        r_dup, n, total, ev_dup, crs_dup = dup
        skipped_dups.append({
            "candidate_event": entry["event_name"],
            "candidate_course": entry["course"],
            "matched_row": r_dup,
            "matched_event": ev_dup,
            "matched_course": crs_dup,
            "score_matches": n,
            "candidate_size": total,
        })
        log.append(
            f"SKIP dup: {entry['event_name']!r}/{entry['course']!r} "
            f"matches row {r_dup} ({ev_dup!r}/{crs_dup!r}, "
            f"{n}/{total} scores)"
        )

    if not to_write and not pending_player_inserts:
        log.append("nothing new to write")
        return {"new_players": 0, "rows_added": 0, "skipped": skipped_dups,
                "hc_pushed": False}

    if pending_player_inserts:
        log.append(f"adding {len(pending_player_inserts)} new player(s)…")
        for after_col, name in pending_player_inserts:
            await gs.add_player(apps_url, name, after_col, sheet)
            log.append(f"  + {name}")

    rows_added = 0
    if to_write:
        max_col = max(c for c, _ in roster)
        rows = []
        for entry in to_write:
            row = [0] * max_col
            row[0] = year
            row[1] = entry["event_name"]
            row[2] = entry["course"]
            for col, score in entry["scores"].items():
                row[col - 1] = score
            rows.append(row)
        log.append(f"appending {len(rows)} round row(s)…")
        ar = await gs.append_rows(apps_url, rows, sheet)
        rows_added = ar.get("rows_appended", 0)
        log.append(f"  rows {ar.get('first_row')}–{ar.get('last_row')}")

    # ---- recompute HCs against the freshly-updated sheet ----
    log.append("pulling updated sheet for recompute…")
    data2 = await gs.pull(apps_url, sheet)
    player_arr, i_pl, tokens = _data_to_tokens(data2)
    log.append(f"  {i_pl} players, {len(tokens)} tokens")

    log.append("computing ODGC handicaps…")
    res_odgc = compute_handicaps(player_arr, i_pl, tokens,
                                 anchor_at_zero=True, verbose=False)
    log.append("computing golf handicaps…")
    res_golf = compute_handicaps(player_arr, i_pl, tokens,
                                 anchor_at_zero=False, verbose=False)

    log.append("pushing HC tab…")
    hc_rows = _build_hc_rows(res_odgc, res_golf)
    await gs.replace_sheet(apps_url, "HC", hc_rows, freeze_rows=4)
    log.append(f"  HC tab: {len(hc_rows)} rows")

    for spec in SUBSET_TABS:
        log.append(f"pushing {spec['tab_name']} tab…")
        sub_rows = _build_subset_rows(res_odgc, spec)
        await gs.replace_sheet(apps_url, spec["tab_name"], sub_rows, freeze_rows=4)
        log.append(f"  {spec['tab_name']} tab: {len(sub_rows)} rows")

    return {
        "kind": kind,
        "pools_seen": len(pools),
        "new_players": len(pending_player_inserts),
        "rows_added": rows_added,
        "skipped": skipped_dups,
        "hc_pushed": True,
        "hc_rows": len(hc_rows),
        "subset_tabs": [s["tab_name"] for s in SUBSET_TABS],
    }


# --- helpers --------------------------------------------------------------

def _detect_kind(source: str) -> str:
    s = source.strip()
    if s.isdigit() or "pdga.com" in s:
        return "pdga"
    if "udisc.com" in s:
        return "udisc"
    raise ValueError(f"can't tell what kind of URL this is: {source!r}")


async def _fetch_pools(kind, url, event, log):
    """Returns a list of {course, event_name, players: [(name, score), ...]}.

    UDisc: one pool. PDGA: one pool per (round, course) after same-course
    merging across divisions.
    """
    if kind == "udisc":
        log.append("GET UDisc page…")
        page = await fetch_text(url, user_agent=UDISC_USER_AGENT)
        raw_pools = parse_udisc_leaderboard(page)
        if any(p.get("unmatched") for p in raw_pools):
            unmatched = [p for p in raw_pools if p.get("unmatched")][0]
            raise ValueError(
                "UDisc stream payload didn't assign these players to a "
                f"layout: {[n for n,_ in unmatched['players']]!r}"
            )
        pools = []
        for p in raw_pools:
            course = guess_course_from_layout(p["layout_text"])
            if not course:
                raise ValueError(
                    f"can't infer course from UDisc layout {p['layout_text']!r}"
                )
            ev = event
            if len(raw_pools) > 1:
                ev = f"{event}_{course}"
            pools.append({
                "course": course,
                "event_name": ev,
                "players": p["players"],
            })
        if len(pools) > 1:
            log.append(f"  split by tee → {len(pools)} pools: "
                       f"{', '.join(p['course'] for p in pools)}")
        return pools

    # PDGA
    src = url
    if src.isdigit():
        src = f"https://www.pdga.com/tour/event/{src}"
    log.append("GET PDGA page…")
    page = await fetch_text(src, user_agent=PDGA_USER_AGENT)
    event_name_from_pdga, pdga_pools = parse_pdga_event(page)
    log.append(f"  event: {event_name_from_pdga!r}  pools (raw): {len(pdga_pools)}")

    # Merge same-(round, course) pools.
    merged: dict[tuple[int, str], dict] = {}
    for p in pdga_pools:
        course = guess_course_from_layout(p["layout_text"])
        if not course:
            raise ValueError(
                f"can't infer course for {p['division']} R{p['round']} "
                f"from layout {p['layout_text']!r}"
            )
        key = (p["round"], course)
        if key not in merged:
            merged[key] = {
                "course": course,
                "round": p["round"],
                "divisions": [],
                "players": [],
            }
        merged[key]["divisions"].append(p["division"])
        for name, _pdga, sc in p["players"]:
            merged[key]["players"].append((name, sc))
    pools = sorted(merged.values(), key=lambda p: (p["round"], p["course"]))
    for p in pools:
        p["event_name"] = f"{event}_R{p['round']}"
    return pools


def _data_to_tokens(data):
    """Turn the 2D pulled sheet into the (player, i_pl, tokens) tuple
    compute_handicaps expects. Mirrors hc24.parse_input_gsheet inline."""
    HELPER_LABELS = {"count", "total", "sum", "tally", "n", "#"}
    if not data:
        raise ValueError("sheet is empty")
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
        raise ValueError("no player names in row 1")
    player_arr = [""] * (i_pl + 2)
    player_arr[0] = "PLAYER"
    for idx, name in enumerate(names, 1):
        player_arr[idx] = name

    def cell(row_idx, col_idx):
        if row_idx >= len(data):
            return None
        r = data[row_idx]
        if col_idx >= len(r):
            return None
        v = r[col_idx]
        return None if v == "" else v

    def cells_row(row_num):
        return [cell(row_num - 1, 3 + j) for j in range(i_pl)]

    def as_num(v, default):
        return v if v is not None else default

    def fmt_num(v):
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        return str(v)

    tokens: list[str] = ["end_2020_hc", "HC"]
    for v in cells_row(2):
        tokens.append(fmt_num(as_num(v, -1)))
    for r in range(3, 10):
        for v in cells_row(r):
            tokens.append(fmt_num(as_num(v, 100)))
    for r, (lab1, lab2) in zip(
        range(10, 14),
        [("ODGCmember", "status"), ("Atos_List", "status"),
         ("EVmember", "status"), ("LadiesLeague", "status")],
    ):
        tokens += [lab1, lab2]
        for v in cells_row(r):
            tokens.append(str(int(as_num(v, 0))))
    for r in range(14, len(data) + 1):
        yr = cell(r - 1, 0)
        ev = cell(r - 1, 1)
        cr = cell(r - 1, 2)
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

    return player_arr, i_pl, tokens


def _build_hc_rows(res_odgc, res_golf, golf_cap_k=5.0):
    """Mirror of gsheets.build_hc_summary_rows but works directly on the
    compute_handicaps result dicts (the worker doesn't write txt files)."""
    from hc_algorithm import compress_plus_hc

    player = res_odgc["player"]
    i_pl = res_odgc["i_pl"]
    hc_odgc = res_odgc["hc"]
    hc_golf_raw = res_golf["hc"]
    rnd_count = res_odgc["rnd_count"]
    ODGCmem_stat = res_odgc["ODGCmem_stat"]

    hc_golf_disp = [compress_plus_hc(h, golf_cap_k) for h in hc_golf_raw]

    qualified = [j for j in range(1, i_pl + 1) if rnd_count[j] > 2]
    odgc_sorted = sorted(qualified, key=lambda j: hc_odgc[j])
    golf_sorted = sorted(qualified, key=lambda j: hc_golf_disp[j])
    golf_rank_by_idx = {j: i + 1 for i, j in enumerate(golf_sorted)}

    odgc_member_rank: dict[int, int] = {}
    member_counter = 0
    for j in odgc_sorted:
        if ODGCmem_stat[j] == 1:
            member_counter += 1
            odgc_member_rank[j] = member_counter

    stamp = _dt.datetime.now().isoformat(timespec="minutes")
    rows: list[list] = [
        ["ODGC Handicaps"],
        [f"Generated {stamp} from active2025 (via worker)"],
        [],
        ["Rank", "ODGC Rank", "Player", "HC", "HC (Golf)",
         "Golf Rank", "Rounds"],
    ]
    for rank, j in enumerate(odgc_sorted, 1):
        odgc_r = odgc_member_rank.get(j, "")
        rows.append([
            rank, odgc_r, player[j],
            f"{hc_odgc[j]:.2f}",
            fmt_2f_golf(hc_golf_disp[j]),
            golf_rank_by_idx[j],
            rnd_count[j],
        ])
    return rows


# Club-focused HC tabs. Each tab filters the qualified field down to the
# relevant membership and shows base HC plus per-course HCs scaled by
# crs_ref[c] / 54. Course indices match COURSE_ID in hc_algorithm.py.
SUBSET_TABS = [
    {
        "tab_name": "HC - ODGC",
        "title": "ODGC Members",
        "filter_key": "ODGCmem_stat",
        "filter_extra_or": [],
        "courses": [
            ("Larrimac Blue", 8),
            ("Larrimac Yellow", 9),
            ("Almonte Blue", 22),
            ("Kanata", 11),
            ("Mountain", 13),
            ("Ferguson Yellow", 25),
            ("Ferguson Blue", 17),
            ("Ferguson Red", 21),
            ("Shire", 15),
            ("Franktown", 18),
            ("Camp Fortune", 24),
        ],
    },
    {
        "tab_name": "HC - KV",
        "title": "Kemptville / Ferguson Forest",
        "filter_key": None,  # all qualified
        "filter_extra_or": [],
        "courses": [
            ("Ferguson Blue", 17),
            ("Ferguson Yellow", 25),
            ("Ferguson Red", 21),
            ("Mountain", 13),
        ],
    },
    {
        "tab_name": "HC - EV",
        "title": "Ettyville (MVP + Axiom)",
        "filter_key": "EVmem_stat",
        "filter_extra_or": ["ODGCmem_stat", "TOSSmem_stat"],
        # EV uses the historical (crs_ref[3]-3.21) / (crs_ref[6]-2.05) offsets
        # to back out the white-tee differentials from the longer blue tee
        # reference scores — mirrors hc24.py evHC output.
        "courses": [
            ("MVP White", 1, 0.0),
            ("MVP Blue", 3, -3.21),
            ("MVP Yellow", 3, 0.0),
            ("Axiom White", 4, 0.0),
            ("Axiom Blue", 6, -2.05),
            ("Axiom Yellow", 6, 0.0),
        ],
        "include_base_hc": False,
    },
    {
        "tab_name": "HC - Ladies",
        "title": "Ladies League (ODGC members)",
        "filter_key": "LLmem_stat",
        "filter_extra_and": "ODGCmem_stat",
        "filter_extra_or": [],
        "courses": [
            ("Kanata", 11),
        ],
    },
]


def _build_subset_rows(res, spec):
    """Build a club-focused ranking tab from a compute_handicaps result."""
    player = res["player"]
    i_pl = res["i_pl"]
    hc = res["hc"]
    rnd_count = res["rnd_count"]
    crs_ref = res["crs_ref"]
    include_base = spec.get("include_base_hc", True)

    def member(j):
        if spec["filter_key"] is None and not spec["filter_extra_or"]:
            return True
        flags = []
        if spec["filter_key"]:
            flags.append(res[spec["filter_key"]][j] == 1)
        for k in spec["filter_extra_or"]:
            flags.append(res[k][j] == 1)
        ok = any(flags)
        if "filter_extra_and" in spec:
            ok = ok and res[spec["filter_extra_and"]][j] == 1
        return ok

    qualified = [j for j in range(1, i_pl + 1)
                 if rnd_count[j] > 2 and member(j)]
    qualified.sort(key=lambda j: hc[j])

    stamp = _dt.datetime.now().isoformat(timespec="minutes")
    rows: list[list] = [
        [spec["title"]],
        [f"Generated {stamp} from active2025 (via worker)"],
        [],
    ]
    header = ["Rank", "Player"]
    if include_base:
        header.append("HC (base)")
    for course in spec["courses"]:
        header.append(course[0])
    header.append("Rounds")
    rows.append(header)

    for rank, j in enumerate(qualified, 1):
        row = [rank, player[j]]
        if include_base:
            row.append(f"{hc[j]:.2f}")
        for course in spec["courses"]:
            crs_idx = course[1]
            offset = course[2] if len(course) > 2 else 0.0
            ref = crs_ref[crs_idx] + offset
            row.append(f"{hc[j] * ref / 54.0:.2f}")
        row.append(rnd_count[j])
        rows.append(row)
    return rows


def _json_resp(obj, status=200):
    h = {"content-type": "application/json"}
    h.update(CORS_HEADERS)
    return Response(_json.dumps(obj, indent=2), status=status, headers=h)
