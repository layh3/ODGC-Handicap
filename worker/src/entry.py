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
import re as _re

from workers import Response  # type: ignore[import-not-found]

from hc_algorithm import compute_handicaps, fmt_2f_golf
from hc_matching import match_player, to_lastname_first, guess_course_from_layout, COURSE_NAMES
from hc_parsing import (
    parse_udisc_leaderboard, parse_pdga_event, parse_udisc_league_schedule,
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

    apps_url = getattr(env, "APPS_SCRIPT_URL", None) or ""
    if not apps_url:
        return _json_resp(
            {"ok": False, "error": "server missing APPS_SCRIPT_URL"}, status=500
        )

    action = body.get("action") or "ingest"

    # Player lookup is public — anyone with the page can browse rankings.
    if action == "lookup":
        name = (body.get("name") or "").strip()
        sheet = body.get("sheet") or "active2025"
        if not name:
            return _json_resp({"ok": False, "error": "name required"}, status=400)
        try:
            dossier = await _run_lookup(apps_url, name, sheet)
            return _json_resp({"ok": True, "dossier": dossier})
        except LookupError as e:
            return _json_resp({"ok": False, "error": str(e)}, status=404)
        except Exception as e:
            return _json_resp({"ok": False, "error": str(e)}, status=500)

    # Net results for a specific past event (public, read-only).
    if action == "event_results":
        ev_name = (body.get("event") or "").strip()
        yr_filter = body.get("year")
        sheet = body.get("sheet") or "active2025"
        if not ev_name:
            return _json_resp({"ok": False, "error": "event required"}, status=400)
        try:
            yr_filter = int(yr_filter) if yr_filter is not None else None
        except (TypeError, ValueError):
            yr_filter = None
        try:
            _, res_odgc, _ = await _pull_and_compute(apps_url, sheet)
            ev_arr  = res_odgc["event"]
            crs_arr = res_odgc["course"]
            ry_arr  = res_odgc["ry"]
            i_rc    = res_odgc["i_rc"]
            # Collect all matching round indices (deduplicated by event+course+year).
            seen = set()
            results = []
            for r in range(1, i_rc + 1):
                if ev_arr[r] != ev_name:
                    continue
                if yr_filter is not None and ry_arr[r] != yr_filter:
                    continue
                key = (ev_arr[r], crs_arr[r], ry_arr[r])
                if key in seen:
                    continue
                seen.add(key)
                players = _build_net_results(res_odgc, r)
                results.append({
                    "event": ev_arr[r],
                    "course": crs_arr[r],
                    "year": ry_arr[r],
                    "players": players,
                })
            if not results:
                return _json_resp(
                    {"ok": False, "error": f"no rounds found for event {ev_name!r}"},
                    status=404,
                )
            return _json_resp({"ok": True, "results": results})
        except Exception as e:
            return _json_resp({"ok": False, "error": str(e)}, status=500)

    # All-time top scores per course (public, read-only).
    if action == "course_records":
        sheet = body.get("sheet") or "active2025"
        try:
            data = await gs.pull(apps_url, sheet)
            roster = gs.load_roster_from_data(data)
            col_to_name = {c: n for c, n in roster}

            course_entries: dict[str, list] = {}
            for row in data[13:]:
                if len(row) < 3:
                    continue
                yr, ev, crs = row[0], row[1], row[2]
                if yr in (None, "") or ev in (None, "") or crs in (None, ""):
                    break
                ev_str = str(ev).strip()
                if len(ev_str) < 3:
                    break
                crs_str = str(crs).strip()
                if ev_str.startswith("x") or crs_str == "unq":
                    continue
                try:
                    yr_int = int(yr)
                except (TypeError, ValueError):
                    continue
                for col, name in col_to_name.items():
                    if col - 1 >= len(row):
                        continue
                    v = row[col - 1]
                    if v in (None, "", 0, "0"):
                        continue
                    try:
                        sc = int(v)
                        if sc > 0:
                            if crs_str not in course_entries:
                                course_entries[crs_str] = []
                            course_entries[crs_str].append((sc, name, ev_str, yr_int))
                    except (TypeError, ValueError):
                        continue

            records = {}
            for crs, entries in course_entries.items():
                entries.sort(key=lambda e: e[0])
                top = entries[:10]
                if len(entries) > 10:
                    cut = top[-1][0]
                    for e in entries[10:]:
                        if e[0] == cut:
                            top.append(e)
                        else:
                            break
                records[crs] = {
                    "name": COURSE_NAMES.get(crs, crs),
                    "top": [
                        {"player": e[1], "gross": e[0], "event": e[2], "year": e[3]}
                        for e in top
                    ],
                }
            sorted_recs = dict(sorted(records.items(), key=lambda kv: kv[1]["name"]))
            return _json_resp({"ok": True, "records": sorted_recs})
        except Exception as e:
            return _json_resp({"ok": False, "error": str(e)}, status=500)

    # HC list for the doubles team generator (public, read-only).
    if action == "hc_list":
        sheet = body.get("sheet") or "active2025"
        try:
            _, res_odgc, res_golf = await _pull_and_compute(apps_url, sheet)
            from hc_algorithm import compress_plus_hc
            i_pl = res_odgc["i_pl"]
            players = []
            for j in range(1, i_pl + 1):
                if res_odgc["rnd_count"][j] <= 2:
                    continue
                hc = res_odgc["hc"][j]
                hc_g_raw = res_golf["hc"][j]
                hc_golf_disp = compress_plus_hc(hc_g_raw, 5.0)
                players.append({
                    "name": res_odgc["player"][j],
                    "hc": round(hc, 2),
                    "hc_golf": fmt_2f_golf(hc_golf_disp),
                    "rounds": res_odgc["rnd_count"][j],
                })
            players.sort(key=lambda p: p["hc"])
            return _json_resp({"ok": True, "players": players})
        except Exception as e:
            return _json_resp({"ok": False, "error": str(e)}, status=500)

    # Roster: just the player name list, for the lookup typeahead.
    if action == "roster":
        sheet = body.get("sheet") or "active2025"
        try:
            data = await gs.pull(apps_url, sheet)
            roster = gs.load_roster_from_data(data)
            names = sorted([n for _, n in roster])
            return _json_resp({"ok": True, "names": names})
        except Exception as e:
            return _json_resp({"ok": False, "error": str(e)}, status=500)

    # Ingest + admin actions are password-gated.
    shared = getattr(env, "SHARED_PASSWORD", None) or ""
    if not shared:
        return _json_resp(
            {"ok": False, "error": "server missing SHARED_PASSWORD secret"},
            status=500,
        )
    if body.get("password") != shared:
        return _json_resp({"ok": False, "error": "wrong password"}, status=401)

    sheet = body.get("sheet") or "active2025"

    # Admin: edit a player's club-membership flags.
    if action == "set_membership":
        name = (body.get("name") or "").strip()
        flags = body.get("flags") or {}
        if not name:
            return _json_resp({"ok": False, "error": "name required"}, status=400)
        try:
            result = await gs.set_membership(apps_url, name, flags, sheet)
            return _json_resp({"ok": True, "result": result})
        except Exception as e:
            return _json_resp({"ok": False, "error": str(e)}, status=500)

    # Admin: rename a player (fix a typo in their roster entry).
    if action == "rename_player":
        old_name = (body.get("old_name") or "").strip()
        new_name = (body.get("new_name") or "").strip()
        if not old_name or not new_name:
            return _json_resp(
                {"ok": False, "error": "old_name and new_name required"},
                status=400,
            )
        try:
            result = await gs.rename_player(apps_url, old_name, new_name, sheet)
            return _json_resp({"ok": True, "result": result})
        except Exception as e:
            return _json_resp({"ok": False, "error": str(e)}, status=500)

    # Admin: append a brand-new player to the roster.
    if action == "add_player_to_roster":
        name = (body.get("name") or "").strip()
        if not name:
            return _json_resp({"ok": False, "error": "name required"}, status=400)
        try:
            data = await gs.pull(apps_url, sheet)
            roster = gs.load_roster_from_data(data)
            if not roster:
                return _json_resp(
                    {"ok": False, "error": "couldn't locate the roster in the sheet"},
                    status=500,
                )
            existing = {n for _, n in roster}
            if name in existing:
                return _json_resp(
                    {"ok": False, "error": f"player {name!r} already on the roster"},
                    status=409,
                )
            after_col = max(c for c, _ in roster)
            new_col = await gs.add_player(apps_url, name, after_col, sheet)
            return _json_resp({"ok": True, "name": name, "col": new_col})
        except Exception as e:
            return _json_resp({"ok": False, "error": str(e)}, status=500)

    # Manual trigger for auto-ingest (for testing and ad-hoc runs).
    if action == "run_auto_ingest":
        log: list[str] = []
        try:
            result = await _auto_ingest_all(apps_url, log)
            return _json_resp({"ok": True, "log": log, "result": result})
        except Exception as e:
            log.append(f"ERROR: {e}")
            return _json_resp({"ok": False, "error": str(e), "log": log}, status=500)

    url = (body.get("url") or "").strip()
    event = (body.get("event") or "").strip()
    year = body.get("year")

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

    # ---- net results + recap ----
    # Pre-state HC compute (uses the PRE-append data so movers reflect delta).
    _par, _ipl, _tok = _data_to_tokens(data)
    res_before = compute_handicaps(_par, _ipl, _tok, anchor_at_zero=True, verbose=False)

    net_results = []
    recap_blocks = []
    for entry in to_write:
        round_idx = _find_round_idx(res_odgc, entry["event_name"], entry["course"], year)
        if round_idx is None:
            log.append(f"  WARNING: round index not found for {entry['event_name']}/{entry['course']}")
            continue
        players = _build_net_results(res_odgc, round_idx)
        if not players:
            log.append(f"  net results unavailable for {entry['event_name']}/{entry['course']}")
            continue
        net_results.append({
            "event": entry["event_name"],
            "course": entry["course"],
            "players": players,
        })
        log.append(f"net results — {entry['event_name']} @ {entry['course']}:")
        for p in players:
            if p["is_new"]:
                log.append(f"  NEW (no HC yet): {p['name']} {p['gross']}")
            else:
                log.append(f"  {p['rank']}. {p['name']}  net {p['net']}  ({p['gross']} − {p['hc']})")

        movers = _build_movers(res_before, res_odgc, entry["scores"])
        pbs = _find_pbs(data, entry["course"], entry["scores"], player_arr, i_pl)
        new_player_names = [p["name"] for p in players if p["is_new"]]
        recap_blocks.append(
            _build_recap_block(
                entry["event_name"], entry["course"],
                players, movers, pbs, new_player_names,
            )
        )

    if net_results:
        log.append("pushing Results tab…")
        results_rows = _build_results_tab_rows(net_results)
        await gs.replace_sheet(apps_url, "Results", results_rows, freeze_rows=2)
        log.append(f"  Results tab: {len(results_rows)} rows")

    recap = "\n\n".join(recap_blocks)

    return {
        "kind": kind,
        "pools_seen": len(pools),
        "new_players": len(pending_player_inserts),
        "rows_added": rows_added,
        "skipped": skipped_dups,
        "hc_pushed": True,
        "hc_rows": len(hc_rows),
        "subset_tabs": [s["tab_name"] for s in SUBSET_TABS],
        "net_results": net_results,
        "recap": recap,
    }


# --- shared pull + compute ------------------------------------------------

async def _pull_and_compute(apps_url, sheet):
    """Pull the sheet once and run both HC computes. Returns (data, res_odgc, res_golf)."""
    data = await gs.pull(apps_url, sheet)
    player_arr, i_pl, tokens = _data_to_tokens(data)
    res_odgc = compute_handicaps(player_arr, i_pl, tokens,
                                 anchor_at_zero=True, verbose=False)
    res_golf = compute_handicaps(player_arr, i_pl, tokens,
                                 anchor_at_zero=False, verbose=False)
    return data, res_odgc, res_golf


# --- player lookup --------------------------------------------------------

async def _run_lookup(apps_url, name, sheet):
    """Pull the sheet, compute both HCs, and build a per-player dossier.

    Raises LookupError if the name doesn't match any roster entry.
    """
    _, res_odgc, res_golf = await _pull_and_compute(apps_url, sheet)
    return _build_dossier(name, res_odgc, res_golf)


def _build_dossier(name, res_odgc, res_golf):
    from hc_algorithm import _num_for_irck, compress_plus_hc

    player = res_odgc["player"]
    i_pl = res_odgc["i_pl"]

    # Resolve name → 1-indexed player j. Try exact first, then case-insensitive.
    target = name.strip()
    j = None
    for k in range(1, i_pl + 1):
        if player[k] == target:
            j = k
            break
    if j is None:
        casefolded = target.casefold()
        for k in range(1, i_pl + 1):
            if player[k].casefold() == casefolded:
                j = k
                break
    if j is None:
        raise LookupError(f"no roster entry matches {name!r}")

    hc_base = res_odgc["hc"][j]
    hc_golf = res_golf["hc"][j]
    hc_golf_disp = compress_plus_hc(hc_golf, 5.0)
    rnd_count = res_odgc["rnd_count"][j]
    crs_ref = res_odgc["crs_ref"]
    score = res_odgc["score"]
    event = res_odgc["event"]
    course = res_odgc["course"]
    ry = res_odgc["ry"]
    diff = res_odgc["diff"][j]
    d_ry = res_odgc["d_ry"][j]
    played_at = res_odgc["played_at"][j]

    # Walk slots 1..rnd_count and resolve each to its round of origin.
    # played_at[k] = 0 means synthetic (seed or year-reset) — skip.
    played: list[dict] = []
    for k in range(1, rnd_count + 1):
        r = played_at[k]
        if r <= 0:
            continue
        sc = score[r][j] if r < len(score) else 0
        played.append({
            "round_index": r,
            "diff_slot": k,
            "year": ry[r],
            "event": event[r],
            "course": course[r],
            "score": int(sc) if sc else 0,
            "diff": round(diff[k], 3),
        })

    last20 = played[-20:]
    diffs_in_window = [(p["diff_slot"], p["diff"]) for p in last20
                       if p["diff"] is not None]
    n_for_avg = _num_for_irck(min(20, rnd_count))
    counted_slots: set[int] = set()
    if n_for_avg > 0:
        ranked = sorted(diffs_in_window, key=lambda x: x[1])
        counted_slots = {slot for slot, _ in ranked[:n_for_avg]}
    counted_sum = sum(d for slot, d in diffs_in_window if slot in counted_slots)

    for p in last20:
        p["counted"] = p["diff_slot"] in counted_slots

    # PB: best gross per course across ALL of the player's rounds.
    best_per_course: dict[str, int] = {}
    for p in played:
        if p["score"] > 0:
            crs = p["course"]
            if crs not in best_per_course or p["score"] < best_per_course[crs]:
                best_per_course[crs] = p["score"]
    for p in last20:
        p["pb"] = p["score"] > 0 and p["score"] == best_per_course.get(p["course"])

    # Per-course HC for every course the algorithm has a reference for.
    from hc_algorithm import COURSE_ID
    per_course = []
    for c in range(1, len(COURSE_ID)):
        if c >= len(crs_ref):
            continue
        ref = crs_ref[c]
        if ref <= 0:
            continue
        per_course.append({
            "code": COURSE_ID[c],
            "ref": round(ref, 2),
            "hc": round(hc_base * ref / 54.0, 2),
        })

    # Ranks: position in each club's ascending-by-HC ordering.
    def rank_in(filter_fn):
        qualified = [k for k in range(1, i_pl + 1)
                     if res_odgc["rnd_count"][k] > 2 and filter_fn(k)]
        qualified.sort(key=lambda k: res_odgc["hc"][k])
        for i, k in enumerate(qualified, 1):
            if k == j:
                return {"rank": i, "of": len(qualified)}
        return None

    is_member = res_odgc["rnd_count"][j] > 2
    ranks = {
        "overall": rank_in(lambda k: True) if is_member else None,
        "ODGC": rank_in(lambda k: res_odgc["ODGCmem_stat"][k] == 1)
                if is_member and res_odgc["ODGCmem_stat"][j] == 1 else None,
        "EV": rank_in(lambda k: res_odgc["EVmem_stat"][k] == 1
                      or res_odgc["ODGCmem_stat"][k] == 1
                      or res_odgc["TOSSmem_stat"][k] == 1)
              if is_member and (res_odgc["EVmem_stat"][j] == 1
                                or res_odgc["ODGCmem_stat"][j] == 1
                                or res_odgc["TOSSmem_stat"][j] == 1) else None,
        "Ladies": rank_in(lambda k: res_odgc["LLmem_stat"][k] == 1
                          and res_odgc["ODGCmem_stat"][k] == 1)
                  if is_member and res_odgc["LLmem_stat"][j] == 1
                  and res_odgc["ODGCmem_stat"][j] == 1 else None,
    }

    return {
        "name": player[j],
        "rnd_count": rnd_count,
        "hc": round(hc_base, 4),
        "hc_golf": round(hc_golf_disp, 4),
        "memberships": {
            "ODGC": res_odgc["ODGCmem_stat"][j] == 1,
            "TOSS": res_odgc["TOSSmem_stat"][j] == 1,
            "EV": res_odgc["EVmem_stat"][j] == 1,
            "Ladies": res_odgc["LLmem_stat"][j] == 1,
        },
        "last_20": last20,
        "counted_n": n_for_avg,
        "counted_sum": round(counted_sum, 3),
        "per_course_hc": per_course,
        "ranks": ranks,
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


def _build_net_results(res, round_idx):
    """Net leaderboard for one round: [{rank, name, gross, hc, net, is_new}, ...]

    Returns [] if the round was skipped by the <2-established-players gate.
    """
    player       = res["player"]
    i_pl         = res["i_pl"]
    score        = res["score"]
    rnd_count    = res["rnd_count"]
    played_at    = res["played_at"]
    hc_entering  = res["hc_entering"]
    est_entering = res["est_entering"]
    round_c_fac  = res["round_c_fac"]

    c_fac = round_c_fac[round_idx]

    entries = []
    for j in range(1, i_pl + 1):
        sc = score[round_idx][j]
        if sc <= 0:
            continue
        # Walk slots from the end — the slot for this round is near the top.
        slot = None
        for k in range(rnd_count[j], 0, -1):
            if played_at[j][k] == round_idx:
                slot = k
                break
        if slot is None:
            # Round was skipped (< 2 established players)
            return []
        gross = int(sc)
        hc_in = hc_entering[j][slot]
        est   = est_entering[j][slot]
        if est:
            net = gross - hc_in * c_fac
            entries.append({
                "name": player[j], "gross": gross,
                "hc": round(hc_in, 1), "net": round(net, 1), "is_new": False,
            })
        else:
            entries.append({
                "name": player[j], "gross": gross,
                "hc": None, "net": None, "is_new": True,
            })

    established = sorted([e for e in entries if not e["is_new"]], key=lambda e: e["net"])
    new_players  = [e for e in entries if e["is_new"]]

    prev_net = None
    display_rank = 1
    for i, e in enumerate(established):
        if prev_net is not None and e["net"] == prev_net:
            e["rank"] = established[i - 1]["rank"]
        else:
            e["rank"] = display_rank
        prev_net = e["net"]
        display_rank += 1
    for e in new_players:
        e["rank"] = None

    return established + new_players


def _find_round_idx(res, event_name, course_code, year):
    """Return the most recent round index matching event/course/year, or None."""
    ev  = res["event"]
    crs = res["course"]
    ry  = res["ry"]
    i_rc = res["i_rc"]
    for r in range(i_rc, 0, -1):
        if ev[r] == event_name and crs[r] == course_code and ry[r] == year:
            return r
    return None


def _build_movers(res_before, res_after, scores_by_col):
    """HC movers for the ingested pool — players whose HC changed by ≥0.05."""
    before_hc = {
        res_before["player"][j]: res_before["hc"][j]
        for j in range(1, res_before["i_pl"] + 1)
        if res_before["rnd_count"][j] > 2
    }
    after_hc = {
        res_after["player"][j]: res_after["hc"][j]
        for j in range(1, res_after["i_pl"] + 1)
        if res_after["rnd_count"][j] > 2
    }
    movers = []
    for col in scores_by_col:
        j = col - 3
        if j < 1 or j > res_after["i_pl"]:
            continue
        name = res_after["player"][j]
        if name not in before_hc or name not in after_hc:
            continue
        delta = after_hc[name] - before_hc[name]
        if abs(delta) >= 0.05:
            movers.append({
                "name": name,
                "before": round(before_hc[name], 2),
                "after": round(after_hc[name], 2),
                "delta": round(delta, 2),
            })
    movers.sort(key=lambda m: -abs(m["delta"]))
    return movers[:5]


def _find_pbs(data, pool_course, scores_by_col, player_arr, i_pl):
    """Personal bests: players whose new gross beats their previous best at this course."""
    pbs = []
    for col, new_gross in scores_by_col.items():
        j = col - 3
        if j < 1 or j > i_pl:
            continue
        prev_scores = []
        for row in data[13:]:
            if len(row) < 3:
                continue
            crs = str(row[2]).strip() if row[2] is not None else ""
            if crs != pool_course:
                continue
            if len(row) <= col - 1:
                continue
            v = row[col - 1]
            if v in (None, "", 0, "0"):
                continue
            try:
                sc = int(v)
                if sc > 0:
                    prev_scores.append(sc)
            except (TypeError, ValueError):
                continue
        if not prev_scores:
            continue
        prev_best = min(prev_scores)
        if new_gross < prev_best:
            pbs.append({"name": player_arr[j], "new": new_gross, "prev": prev_best})
    return pbs


def _build_recap_block(event_name, course_code, net_players, movers, pbs, new_player_names):
    """One plain-text recap block for a single pool."""
    n = len(net_players)
    lines = [f"\U0001f94f {event_name} @ {course_code} — {n} player{'s' if n != 1 else ''}"]

    podium = [p for p in net_players if not p["is_new"]][:3]
    if podium:
        pts = " · ".join(f"{p['rank']}. {p['name']} {p['net']:.1f}" for p in podium)
        lines.append(f"\U0001f3c6 Net: {pts}")

    if movers:
        def _mstr(m):
            arrow = "▼" if m["delta"] < 0 else "▲"
            return f"{m['name']} {m['before']:.2f}→{m['after']:.2f} ({arrow}{abs(m['delta']):.2f})"
        lines.append(f"\U0001f4c8 HC movers: {' · '.join(_mstr(m) for m in movers)}")

    if pbs:
        pb_parts = [f"{p['name']} {p['new']} at {course_code} (prev {p['prev']})" for p in pbs]
        lines.append(f"\U0001f525 PBs: {', '.join(pb_parts)}")

    if new_player_names:
        lines.append(f"\U0001f44b First tracked round: {', '.join(new_player_names)}")

    lines.append("Full standings: https://odgc-hc-page.pages.dev/players")
    return "\n".join(lines)


def _build_results_tab_rows(net_results_list):
    stamp = _dt.datetime.now().isoformat(timespec="minutes")
    rows = [
        [f"Latest results — generated {stamp}"],
        [],
    ]
    for pool in net_results_list:
        rows.append([f"{pool['event']} @ {pool['course']}"])
        rows.append(["Rank", "Player", "Gross", "HC", "Net"])
        for p in pool["players"]:
            rank_str = str(p["rank"]) if p["rank"] is not None else "—"
            hc_str   = f"{p['hc']:.1f}" if p["hc"] is not None else "NEW"
            net_str  = f"{p['net']:.1f}" if p["net"] is not None else "—"
            rows.append([rank_str, p["name"], p["gross"], hc_str, net_str])
        rows.append([])
    return rows


def _derive_event_name(title: str, prefix: str, existing_events: list) -> str:
    """Derive an ingest event name from a UDisc event title.

    "LETS Larrimac Evening Tags Series - LETS #6" + "LETS" → "LETS06"
    "Monday Night Tags @Almonte - ..." (no #N) → count-based "Alm01", "Alm02" …
    """
    m = _re.search(r"#\s*(\d+)", title)
    if m:
        return f"{prefix}{int(m.group(1)):02d}"
    n = sum(1 for ev in existing_events if str(ev).startswith(prefix))
    return f"{prefix}{n + 1:02d}"


_AUTOINGEST_TAB = "AutoIngest"
_LOG_TAB = "Log"
_AUTOINGEST_TEMPLATE = [
    ["schedule_url", "event_prefix", "year", "enabled"],
    [
        "https://udisc.com/leagues/lets-larrimac-evening-tags-series-UCtqMO/schedule",
        "LETS", 26, 1,
    ],
    [
        "https://udisc.com/leagues/monday-night-tags-almonte-3un343/schedule",
        "Alm", 26, 1,
    ],
]


async def _auto_ingest_all(apps_url: str, log: list) -> dict:
    """Fetch each configured league schedule and ingest any new events."""
    sheet = "active2025"

    # Pull (or bootstrap) the AutoIngest config tab.
    try:
        ai_data = await gs.pull(apps_url, _AUTOINGEST_TAB)
        if not ai_data:
            raise ValueError("empty")
    except Exception:
        log.append("AutoIngest tab missing — creating template")
        await gs.replace_sheet(
            apps_url, _AUTOINGEST_TAB, _AUTOINGEST_TEMPLATE, freeze_rows=1
        )
        return {"ok": False, "bootstrapped": True,
                "error": "AutoIngest tab created — re-run to ingest"}

    configs = []
    for row in ai_data[1:]:
        if len(row) < 4:
            continue
        sched_url = str(row[0]).strip()
        prefix    = str(row[1]).strip()
        enabled   = str(row[3]).strip()
        if enabled not in ("1", "true", "True"):
            continue
        try:
            year = int(row[2])
        except (TypeError, ValueError):
            continue
        if sched_url and prefix:
            configs.append({"url": sched_url, "prefix": prefix, "year": year})

    if not configs:
        log.append("no enabled rows in AutoIngest tab")
        return {"ok": True, "ingested_rows": 0}

    log.append(f"AutoIngest: {len(configs)} league(s)")
    today = _dt.datetime.now().strftime("%Y-%m-%d")

    data = await gs.pull(apps_url, sheet)
    existing_events = [
        str(r[1]).strip() for r in data[13:] if len(r) > 1 and r[1] not in (None, "")
    ]

    log_rows = []
    stamp = _dt.datetime.now().isoformat(timespec="seconds")
    total_rows_added = 0

    for cfg in configs:
        prefix = cfg["prefix"]
        yr = cfg["year"]
        yr_str = f"20{yr:02d}" if yr < 100 else str(yr)
        try:
            sched_page = await fetch_text(cfg["url"], user_agent=UDISC_USER_AGENT)
            all_events = parse_udisc_league_schedule(sched_page)
            # Most recent past event only — keeps subrequest budget low with multiple leagues.
            year_events = [
                e for e in all_events
                if e["date"].startswith(yr_str) and e["date"] <= today
            ][:1]
            log.append(
                f"{prefix}: {len(year_events)} past event(s) in {yr_str}"
                + (f" (latest {year_events[0]['date']})" if year_events else "")
            )
        except Exception as e:
            log.append(f"ERROR fetching schedule for {prefix}: {e}")
            log_rows.append([stamp, prefix, 0, f"schedule_error: {e}", "auto"])
            continue

        for ev in year_events:
            ev_name = _derive_event_name(ev["title"], prefix, existing_events)
            # Always advance the counter so subsequent events get unique names.
            existing_events.append(ev_name)
            inner_log: list[str] = []
            try:
                result = await _run_ingest(
                    apps_url, ev["url"], ev_name, yr, sheet, inner_log
                )
                log.extend(f"  {l}" for l in inner_log)
                rows = result.get("rows_added", 0)
                total_rows_added += rows
                if rows > 0:
                    log.append(f"  ingested {ev_name}: {rows} row(s)")
                    log_rows.append([stamp, ev_name, rows, "ok", "auto"])
                    data = await gs.pull(apps_url, sheet)
                    existing_events = [
                        str(r[1]).strip() for r in data[13:]
                        if len(r) > 1 and r[1] not in (None, "")
                    ]
                else:
                    log.append(f"  {ev_name}: already ingested or no data")
            except Exception as e:
                log.append(f"  ERROR ingesting {ev_name}: {e}")
                log_rows.append([stamp, ev_name, 0, f"ingest_error: {e}", "auto"])

    if log_rows:
        try:
            await gs.pull(apps_url, _LOG_TAB)
        except Exception:
            log.append("creating Log tab")
            await gs.replace_sheet(
                apps_url, _LOG_TAB,
                [["timestamp", "event", "rows_added", "status", "source"]],
                freeze_rows=1,
            )
        try:
            await gs.append_rows(apps_url, log_rows, _LOG_TAB)
            log.append(f"wrote {len(log_rows)} row(s) to Log tab")
        except Exception as e:
            log.append(f"WARNING: Log tab write failed: {e}")

    return {"ok": True, "ingested_rows": total_rows_added}


async def on_scheduled(event, env, ctx):
    """Cloudflare cron — runs daily at 06:00 UTC."""
    apps_url = getattr(env, "APPS_SCRIPT_URL", None) or ""
    if not apps_url:
        return
    log: list[str] = []
    try:
        await _auto_ingest_all(apps_url, log)
    except Exception:
        pass


def _json_resp(obj, status=200):
    h = {"content-type": "application/json"}
    h.update(CORS_HEADERS)
    return Response(_json.dumps(obj, indent=2), status=status, headers=h)
