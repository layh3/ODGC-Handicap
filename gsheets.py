"""Google Sheets client for the ODGC handicap tools.

Backs the --gsheet mode of hc24.py, import_udisc.py and import_pdga.py.

The actual sheet access goes through the Apps Script web app deployed from
apps_script.gs. The script's URL lives in `gsheets_url.txt` next to hc24.py
and is treated as a write capability (anyone with the URL can write to the
sheet — keep the file gitignored).

Four primitives, mirroring the actions in apps_script.gs:

    ping(url)
    pull(url, sheet="active2025")               → list[list]
    append_rows(url, rows, sheet="active2025")
    add_player(url, name, after_col, sheet="active2025")
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_URL_FILE = "gsheets_url.txt"
DEFAULT_SHEET = "active2025"
HTTP_TIMEOUT = 30
MAX_RETRIES = 2
RETRY_BACKOFF = 1.5


def load_url(path: str | Path = DEFAULT_URL_FILE) -> str:
    """Read the Apps Script deployment URL.

    Looks in (1) the path given, (2) the cwd, (3) the directory of this
    module. So `python3 hc24.py --gsheet` works whether you run from the
    repo root or from a subdirectory like `out/`.
    """
    p = Path(path)
    candidates = [p, Path.cwd() / p.name, Path(__file__).parent / p.name]
    for cand in candidates:
        if cand.exists():
            url = cand.read_text().strip()
            if not url.startswith(("http://", "https://")):
                raise ValueError(f"{cand} doesn't look like a URL: {url!r}")
            return url
    locs = ", ".join(str(c) for c in candidates)
    raise FileNotFoundError(
        f"gsheets_url.txt not found. Looked in: {locs}. Create it with the "
        f"Apps Script web-app URL (see apps_script.gs)."
    )


def _post(url: str, body: dict) -> dict:
    """POST JSON to the Apps Script URL and parse the JSON response.

    Apps Script web apps redirect POSTs through script.googleusercontent.com.
    urllib follows the redirect correctly (re-POSTing the body); curl's -L
    silently downgrades to GET, which is why a curl test will look broken.
    """
    data = json.dumps(body).encode("utf-8")
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            try:
                result = json.loads(raw)
            except json.JSONDecodeError:
                raise RuntimeError(
                    f"Apps Script returned non-JSON. Check that the deployment "
                    f"is 'Who has access: Anyone'.\nFirst 200 chars: {raw[:200]!r}"
                )
            if not result.get("ok"):
                raise RuntimeError(
                    f"Apps Script returned error for {body.get('action')!r}: "
                    f"{result.get('error')}"
                )
            return result
        except (urllib.error.URLError, TimeoutError, RuntimeError) as e:
            last_err = e
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF ** attempt)
                continue
            raise
    raise RuntimeError(f"unreachable: {last_err}")


def ping(url: str) -> dict:
    """Health check. Returns spreadsheet name + sheet dimensions."""
    return _post(url, {"action": "ping"})


def pull(url: str, sheet: str = DEFAULT_SHEET) -> list[list]:
    """Fetch the entire named tab as a 2D list (row-major, 0-indexed)."""
    result = _post(url, {"action": "pull", "sheet": sheet})
    return result["data"]


def append_rows(url: str, rows: list[list], sheet: str = DEFAULT_SHEET) -> dict:
    """Append N rows at the next free row in `sheet`. All rows must have
    identical length. Returns `{ok, rows_appended, first_row, last_row}`."""
    if not rows:
        return {"ok": True, "rows_appended": 0}
    return _post(url, {"action": "append_rows", "sheet": sheet, "rows": rows})


def add_player(url: str, name: str, after_col: int,
               sheet: str = DEFAULT_SHEET) -> int:
    """Insert a new player column right of `after_col`. Fills row 1 with the
    name, row 2 with -1 (seed HC sentinel), rows 3-9 with 100 (seed-diff
    sentinels) and rows 10-13 with 0 (membership flags). Returns the new
    column index (1-indexed)."""
    result = _post(url, {
        "action": "add_player",
        "sheet": sheet,
        "name": name,
        "after_col": after_col,
    })
    return result["col"]


def replace_sheet(url: str, target_sheet: str, rows: list[list],
                  *, freeze_rows: int = 0, freeze_cols: int = 0) -> dict:
    """Drop and recreate `target_sheet` (a different tab from the data tab
    used by other actions), then fill it with `rows`. Used to publish the
    current handicap rankings into a dedicated tab.

    ``freeze_rows`` / ``freeze_cols`` lock those many leading rows/columns
    in place so they stay visible when the user scrolls.
    """
    return _post(url, {
        "action": "replace_sheet",
        "target_sheet": target_sheet,
        "rows": rows,
        "freeze_rows": freeze_rows,
        "freeze_cols": freeze_cols,
    })


# --- output → tab serialization -------------------------------------------

import datetime as _dt
import re as _re


def _parse_rank_file(text: str) -> list[tuple[int, str, str, int]]:
    """Pull (rank, name, hc, rounds) tuples out of a rankHC.txt-style file.

    The HC field is kept as a string because golf-mode uses '+' prefixes
    that we want to preserve when writing to the Sheet.
    """
    pat = _re.compile(
        r" rank =\s+(\d+)\s+(\S+) HC =\s+(\S+)\s+rounds played = (\d+)"
    )
    out = []
    for line in text.splitlines():
        m = pat.match(line)
        if m:
            out.append((int(m.group(1)), m.group(2), m.group(3), int(m.group(4))))
    return out


def _parse_odgc_member_names(text: str) -> set[str]:
    """Pull the set of player names out of odgcHC.txt. Each data row starts
    with the player name; lines containing 'courses_HC_list' (the header)
    and blank lines are ignored."""
    members = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or "courses_HC_list" in line:
            continue
        tok = line.split(None, 1)[0]
        # Player names look like Last_First; skip stray header tokens that
        # might appear if the file format changes.
        if "_" in tok or tok[:1].isalpha():
            members.add(tok)
    return members


def build_hc_summary_rows(out_dir) -> list[list]:
    """Read rankHC.txt + rankHC_golf.txt + odgcHC.txt from `out_dir` and
    build a 2D rankings table suitable for replace_sheet().

    Layout:
        row 1: title
        row 2: "Generated <iso timestamp>"
        row 3: blank
        row 4: header
        rows 5+: one player per row

    Columns: Rank | ODGC Rank | Player | HC | HC (Golf) | Golf Rank | Rounds
        Rank        rank across all qualified players, sorted by ODGC HC
        ODGC Rank   rank within ODGC members only (blank for non-members)
        Golf Rank   rank across all qualified players, sorted by Golf HC
    """
    from pathlib import Path
    odgc_path = Path(out_dir) / "rankHC.txt"
    golf_path = Path(out_dir) / "rankHC_golf.txt"
    odgc_members_path = Path(out_dir) / "odgcHC.txt"
    for p in (odgc_path, golf_path, odgc_members_path):
        if not p.exists():
            raise FileNotFoundError(f"missing required output file: {p}")

    odgc = _parse_rank_file(odgc_path.read_text(encoding="latin-1"))
    golf = _parse_rank_file(golf_path.read_text(encoding="latin-1"))
    golf_by_name = {name: (rank, hc) for rank, name, hc, _r in golf}
    members = _parse_odgc_member_names(odgc_members_path.read_text(encoding="latin-1"))

    # Walk the (already-sorted) overall ranking; bump the ODGC-only rank
    # counter every time we hit an ODGC member.
    member_rank_by_name: dict[str, int] = {}
    member_counter = 0
    for _rank, name, _hc, _rounds in odgc:
        if name in members:
            member_counter += 1
            member_rank_by_name[name] = member_counter

    stamp = _dt.datetime.now().isoformat(timespec="minutes")
    rows: list[list] = [
        ["ODGC Handicaps"],
        [f"Generated {stamp} from active2025"],
        [],
        ["Rank", "ODGC Rank", "Player", "HC", "HC (Golf)", "Golf Rank", "Rounds"],
    ]
    for rank, name, hc, rounds in odgc:
        g_rank, g_hc = golf_by_name.get(name, ("", ""))
        odgc_rank = member_rank_by_name.get(name, "")
        rows.append([rank, odgc_rank, name,
                     _fmt_hc_2dp(hc), _fmt_hc_2dp(g_hc),
                     g_rank, rounds])
    return rows


def _fmt_hc_2dp(s: str) -> str:
    """Round a stringified HC ('1.23456' or '+4.74481') to 2 decimal places
    while preserving the golf '+' prefix. Used only for the HC sheet view —
    .txt outputs keep full precision."""
    if s in ("", None):
        return ""
    plus = s.startswith("+")
    body = s[1:] if plus else s
    try:
        v = float(body)
    except ValueError:
        return s
    return f"+{v:.2f}" if plus else f"{v:.2f}"


def push_hc_summary(url: str, out_dir, target_sheet: str = "HC") -> dict:
    """Convenience: build the rankings table from rankHC.txt /
    rankHC_golf.txt / odgcHC.txt in `out_dir` and push it to
    `target_sheet`. The top 4 rows (title, timestamp, blank, header) are
    frozen so they stay visible while scrolling."""
    rows = build_hc_summary_rows(out_dir)
    return replace_sheet(url, target_sheet, rows, freeze_rows=4)


# --- helpers used by the import scripts when they operate on cached data ---

def cell_at(data: list[list], row: int, col: int):
    """1-indexed cell read against the pulled 2D array. Returns None for
    out-of-range or empty cells; empty string from Apps Script is normalized
    to None to mirror openpyxl semantics."""
    if row < 1 or row > len(data):
        return None
    r = data[row - 1]
    if col < 1 or col > len(r):
        return None
    v = r[col - 1]
    if v == "":
        return None
    return v


def load_roster_from_data(data: list[list]) -> list[tuple[int, str]]:
    """Equivalent to import_udisc.load_roster() but on a pulled 2D array.

    Returns [(1-indexed col, player_name), ...] from row 1, cols D onward,
    stopping at the first empty cell or known helper label.
    """
    HELPERS = {"count", "total", "sum", "tally", "n", "#"}
    if not data:
        return []
    row1 = data[0]
    roster = []
    for c in range(4, len(row1) + 1):  # col D = 4 (1-indexed)
        v = row1[c - 1]
        if v in (None, ""):
            break
        s = str(v).strip()
        if s.lower() in HELPERS:
            break
        roster.append((c, s))
    return roster


def find_duplicate_row_in_data(
    data: list[list], year: int, candidate_scores: dict,
    *, min_matches: int = 3,
) -> tuple | None:
    """Equivalent to import_udisc.find_duplicate_row() but on a pulled array."""
    if not candidate_scores:
        return None
    best: tuple | None = None
    for row_idx in range(13, len(data)):    # round rows start at row 14
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
            best = (row_idx + 1, n_matches, len(candidate_scores), event, course)
    return best


# --- minimal CLI for smoke testing ---

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Smoke-test the Apps Script backend")
    p.add_argument("action", choices=["ping", "pull"])
    p.add_argument("--sheet", default=DEFAULT_SHEET)
    p.add_argument("--url-file", default=DEFAULT_URL_FILE)
    args = p.parse_args()
    url = load_url(args.url_file)
    if args.action == "ping":
        print(json.dumps(ping(url), indent=2))
    elif args.action == "pull":
        data = pull(url, args.sheet)
        print(f"pulled {len(data)} rows x {max(len(r) for r in data)} cols")
        print(f"first row (head):  {data[0][:6]}")
        print(f"row 14 (head):     {data[13][:6]}")
        print(f"last row (head):   {data[-1][:6]}")
