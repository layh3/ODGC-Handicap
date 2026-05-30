"""Worker-side Apps Script client.

Mirrors the public surface of the CLI's gsheets.py — pull, append_rows,
add_player, replace_sheet — but uses the worker_io.post_json helper
(js.fetch) so it runs in the Cloudflare Workers Python runtime.

The Apps Script URL comes from the env binding APPS_SCRIPT_URL so the
worker doesn't hard-code it.
"""

from __future__ import annotations

from worker_io import post_json


async def ping(url: str) -> dict:
    return await _call(url, {"action": "ping"})


async def pull(url: str, sheet: str = "active2025") -> list[list]:
    result = await _call(url, {"action": "pull", "sheet": sheet})
    return result["data"]


async def append_rows(url: str, rows: list[list],
                      sheet: str = "active2025") -> dict:
    if not rows:
        return {"ok": True, "rows_appended": 0}
    return await _call(url, {
        "action": "append_rows",
        "sheet": sheet,
        "rows": rows,
    })


async def add_player(url: str, name: str, after_col: int,
                     sheet: str = "active2025") -> int:
    result = await _call(url, {
        "action": "add_player",
        "sheet": sheet,
        "name": name,
        "after_col": after_col,
    })
    return result["col"]


async def replace_sheet(url: str, target_sheet: str, rows: list[list],
                        *, freeze_rows: int = 0, freeze_cols: int = 0) -> dict:
    return await _call(url, {
        "action": "replace_sheet",
        "target_sheet": target_sheet,
        "rows": rows,
        "freeze_rows": freeze_rows,
        "freeze_cols": freeze_cols,
    })


async def set_membership(url: str, name: str, flags: dict,
                         sheet: str = "active2025") -> dict:
    """Set a player's club-membership flags (rows 10-13). `flags` may include
    any subset of {ODGC, TOSS, EV, Ladies} — only provided keys are written."""
    return await _call(url, {
        "action": "set_membership",
        "sheet": sheet,
        "name": name,
        "flags": flags,
    })


async def rename_player(url: str, old_name: str, new_name: str,
                        sheet: str = "active2025") -> dict:
    return await _call(url, {
        "action": "rename_player",
        "sheet": sheet,
        "old_name": old_name,
        "new_name": new_name,
    })


async def _call(url: str, body: dict) -> dict:
    result = await post_json(url, body)
    if not result.get("ok"):
        raise RuntimeError(
            f"Apps Script {body.get('action')!r} returned error: "
            f"{result.get('error')}"
        )
    return result


# --- pulled-data helpers (mirror gsheets.py for CLI parity) ---------------

HELPER_LABELS = {"count", "total", "sum", "tally", "n", "#"}


def load_roster_from_data(data: list[list]) -> list[tuple[int, str]]:
    """Return [(1-indexed col, player_name), ...] from row 1 cols D onward."""
    if not data:
        return []
    row1 = data[0]
    roster: list[tuple[int, str]] = []
    for c in range(4, len(row1) + 1):
        v = row1[c - 1]
        if v in (None, ""):
            break
        s = str(v).strip()
        if s.lower() in HELPER_LABELS:
            break
        roster.append((c, s))
    return roster


def find_duplicate_row_in_data(
    data: list[list], year: int, candidate_scores: dict,
    *, min_matches: int = 3,
) -> tuple | None:
    """Same shape as the CLI helper. ≥``min_matches`` exact (col, score)
    pairs in any same-year existing row → flagged as a duplicate."""
    if not candidate_scores:
        return None
    best: tuple | None = None
    for row_idx in range(13, len(data)):
        row = data[row_idx]
        if not row:
            continue
        first = row[0] if len(row) > 0 else None
        if first in (None, ""):
            break
        try:
            if int(first) != year:
                continue
        except (TypeError, ValueError):
            continue
        n_matches = 0
        for col, score in candidate_scores.items():
            if col > len(row):
                continue
            v = row[col - 1]
            if v in (None, "", 0, "0"):
                continue
            try:
                if int(v) == score:
                    n_matches += 1
            except (TypeError, ValueError):
                continue
        if n_matches >= min_matches and (best is None or n_matches > best[1]):
            event = row[1] if len(row) > 1 else None
            course = row[2] if len(row) > 2 else None
            best = (row_idx + 1, n_matches, len(candidate_scores),
                    event, course)
    return best
