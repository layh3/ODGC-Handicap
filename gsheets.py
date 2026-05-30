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
