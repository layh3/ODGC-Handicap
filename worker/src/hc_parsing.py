"""HTML parsers for UDisc leaderboard and PDGA event pages.

Pure functions over an already-fetched HTML string — fetching is the
caller's job (urllib in the CLI, js.fetch in the Cloudflare Worker).
"""

from __future__ import annotations

import html
import json
import re
import unicodedata


UDISC_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.0 Safari/605.1.15"
)
PDGA_USER_AGENT = UDISC_USER_AGENT


def parse_udisc_leaderboard(page: str) -> list[dict]:
    """Parse a UDisc leaderboard page into one or more pools.

    Returns ``[{'layout_text': str, 'players': [(name, score), ...]}, ...]``.

    Most events are single-layout → one pool. League nights like LETS that
    let players pick Blue vs Yellow tees on the same round produce one pool
    per layout. The React Router stream payload embedded in the page maps
    each registrant to a ``courseLayoutId``; we decode that and partition
    the HTML-table players by it.

    UDisc 403s on requests without a desktop User-Agent — set one upstream
    when fetching (see UDISC_USER_AGENT).
    """
    m_title = re.search(r"<title[^>]*>([^<]+)</title>", page)
    m_h1 = re.search(r"<h1[^>]*>([^<]+)</h1>", page)
    base_layout_text = " | ".join(
        s.group(1).strip()
        for s in (m_h1, m_title)
        if s and "UDisc" not in s.group(1).split("|", 1)[0]
    )

    # Each player row has the pattern (after stripping tags):
    #   |position|<blank>|Player Name|relative_score|h1|h2|...|h18|rating|strokes|
    # Strokes is the last numeric cell. Name is in a <p class="text-wrap
    # text-start">.
    players: list[tuple[str, int]] = []
    for tr_match in re.finditer(r"<tr[^>]*>(.+?)</tr>", page, re.DOTALL):
        row_html = tr_match.group(1)
        name_match = re.search(
            r'<p class="text-wrap text-start">\s*(?:<!--[^>]*-->)?\s*([^<]+?)</p>',
            row_html,
        )
        if not name_match:
            continue
        name = html.unescape(name_match.group(1).strip())
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.DOTALL)
        strokes = None
        for cell in reversed(cells):
            txt = re.sub(r"<[^>]+>", "", cell).strip()
            if txt.isdigit():
                strokes = int(txt)
                break
        if strokes is None:
            continue
        players.append((name, strokes))

    name_to_layout = _extract_udisc_layouts(page)
    distinct_layouts = {lab for lab in name_to_layout.values() if lab}
    if len(distinct_layouts) <= 1:
        # Single layout (or stream unparseable) → preserve old behavior.
        return [{"layout_text": base_layout_text, "players": players}]

    # Multi-layout: partition by per-player tee assignment.
    groups: dict[str, list[tuple[str, int]]] = {}
    unmatched: list[tuple[str, int]] = []
    for name, score in players:
        label = name_to_layout.get(_norm_name(name))
        if label:
            groups.setdefault(label, []).append((name, score))
        else:
            unmatched.append((name, score))

    pools: list[dict] = []
    for label, group_players in groups.items():
        pool_layout = f"{base_layout_text} | {label}" if base_layout_text else label
        pools.append({"layout_text": pool_layout, "players": group_players})
    if unmatched:
        # Surface the gap loudly — better to fail than misattribute.
        pools.append({
            "layout_text": base_layout_text,
            "players": unmatched,
            "unmatched": True,
        })
    return pools


def _norm_name(name: str) -> str:
    """Casefold + strip diacritics so HTML-table and stream-payload spellings
    of the same player match (e.g., 'François' vs 'Francois')."""
    nfkd = unicodedata.normalize("NFKD", name)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).casefold().strip()


def _extract_udisc_layouts(page: str) -> dict[str, str]:
    """Return ``{normalized_player_name: layout_label}`` extracted from the
    React Router stream payload embedded in a UDisc leaderboard page.

    Returns ``{}`` if the payload is missing or can't be decoded — callers
    treat that as "single layout, use the page-level title".

    The payload is a devalue-style flat array: ``[v0, v1, v2, ...]`` where
    objects encode ``{"_K": V}`` meaning ``{flat[K]: deref(V)}`` and integer
    values reference other indices. Player ("registrant") objects expose
    ``name`` (string) and ``courseLayoutId`` (UUID string); layout objects
    expose ``_id`` (UUID string) and ``name`` (label like 'Yellow Tees').
    """
    try:
        m = re.search(
            r"streamController\.enqueue\((\".+?\")\)",
            page, re.DOTALL,
        )
        if not m:
            return {}
        # The captured group is itself a JSON string literal whose payload
        # is another JSON document. Two json.loads peel both layers.
        inner = json.loads(m.group(1))
        flat = json.loads(inner)
        if not isinstance(flat, list):
            return {}
    except (json.JSONDecodeError, ValueError):
        return {}

    def resolve_key(k: str) -> str | None:
        if not k.startswith("_"):
            return k
        try:
            idx = int(k[1:])
        except ValueError:
            return None
        if 0 <= idx < len(flat) and isinstance(flat[idx], str):
            return flat[idx]
        return None

    def resolve_val(v):
        if isinstance(v, int) and 0 <= v < len(flat):
            return flat[v]
        return v

    # Pass 1: layout objects. A layout has _id pointing to a UUID-ish string
    # AND a `name` field resolving to a string label (e.g., 'Yellow Tees').
    # We also require `courseId` or `layoutId` to avoid matching unrelated
    # objects that happen to have those two fields.
    layout_label_by_uuid: dict[str, str] = {}
    for obj in flat:
        if not isinstance(obj, dict):
            continue
        named: dict[str, object] = {}
        for k, v in obj.items():
            key = resolve_key(k)
            if key is not None:
                named[key] = v
        if "_id" not in named or "name" not in named:
            continue
        if "courseId" not in named and "layoutId" not in named:
            continue
        uuid = resolve_val(named["_id"])
        label = resolve_val(named["name"])
        if isinstance(uuid, str) and isinstance(label, str):
            layout_label_by_uuid[uuid] = label

    # Pass 2: registrant objects. Each has `name` (player display name) and
    # `courseLayoutId` (UUID matching a layout's _id).
    name_to_layout: dict[str, str] = {}
    for obj in flat:
        if not isinstance(obj, dict):
            continue
        named = {}
        for k, v in obj.items():
            key = resolve_key(k)
            if key is not None:
                named[key] = v
        if "name" not in named or "courseLayoutId" not in named:
            continue
        player_name = resolve_val(named["name"])
        layout_uuid = resolve_val(named["courseLayoutId"])
        if not isinstance(player_name, str) or not isinstance(layout_uuid, str):
            continue
        label = layout_label_by_uuid.get(layout_uuid)
        if label:
            name_to_layout[_norm_name(player_name)] = label
    return name_to_layout


def parse_pdga_event(page: str) -> tuple[str, list[dict]]:
    """Parse a PDGA event page's HTML.

    Returns ``(event_name, pools)`` where each pool is::

        {
          'division': 'MPO',
          'round':    1,
          'layout_text': 'Larrimac Disc Golf Course - YELLOWS; 18 holes; ...',
          'players': [(display_name, pdga_num, round_score), ...],
        }

    PDGA 403s without a desktop User-Agent; set one upstream when fetching
    (see PDGA_USER_AGENT).
    """
    m = re.search(r'<h1 class="title"[^>]*>([^<]+)</h1>', page)
    event_name = html.unescape(m.group(1).strip()) if m else "PDGA event"

    # Layout-details divs hold each round's course/layout text.
    #   id="layout-details-{event_id}-{DIVISION}-round-{N}"
    layouts: dict[tuple[str, int], str] = {}
    for m in re.finditer(
        r'<div id="layout-details-\d+-([A-Z0-9]+)-round-(\d+)"[^>]*>(.*?)</div>',
        page, re.DOTALL,
    ):
        div_code = m.group(1)
        rnd = int(m.group(2))
        body = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(3))).strip()
        layouts[(div_code, rnd)] = html.unescape(body)

    # Division codes appear in document order; each division gets one
    # `<table class="results" id="tournament-stats-N">` in the same order.
    div_codes = re.findall(r'<h3 class="division" id="([A-Z0-9]+)"', page)
    tables = list(
        re.finditer(
            r'<table class="results[^"]*" id="tournament-stats-\d+".*?</table>',
            page, re.DOTALL,
        )
    )

    pools: list[dict] = []
    for div_code, table_match in zip(div_codes, tables):
        table_html = table_match.group(0)
        thead_match = re.search(r"<thead.*?</thead>", table_html, re.DOTALL)
        if not thead_match:
            continue
        round_nums = [
            int(n) for n in re.findall(
                r'<th[^>]*class="[^"]*\bround\b[^"]*"[^>]*>Rd(\d+)</th>',
                thead_match.group(0),
            )
        ]
        if not round_nums:
            continue

        per_round: dict[int, list[tuple[str, str, int]]] = {r: [] for r in round_nums}
        tbody_match = re.search(r"<tbody.*?</tbody>", table_html, re.DOTALL)
        if not tbody_match:
            continue

        for row_match in re.finditer(
            r"<tr[^>]*>(.+?)</tr>", tbody_match.group(0), re.DOTALL
        ):
            row_html = row_match.group(1)
            name_m = re.search(
                r'<td class="player"[^>]*>\s*(?:<a[^>]*>)?([^<]+)',
                row_html,
            )
            if not name_m:
                continue
            name = html.unescape(name_m.group(1).strip())

            pdga_m = re.search(
                r'<td class="pdga-number"[^>]*>([^<]*)</td>', row_html
            )
            pdga_num = html.unescape(pdga_m.group(1).strip()) if pdga_m else ""

            score_cells = re.findall(
                r'<td[^>]*class="[^"]*\bround\b[^"]*"[^>]*>.*?<a[^>]*class="[^"]*\bscore\b[^"]*"[^>]*>([^<]+)</a>',
                row_html, re.DOTALL,
            )
            for r_num, score_text in zip(round_nums, score_cells):
                try:
                    per_round[r_num].append((name, pdga_num, int(score_text.strip())))
                except ValueError:
                    continue

        for r_num in round_nums:
            pools.append({
                "division": div_code,
                "round": r_num,
                "layout_text": layouts.get((div_code, r_num), ""),
                "players": per_round[r_num],
            })

    return event_name, pools
