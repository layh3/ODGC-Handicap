"""HTML parsers for UDisc leaderboard and PDGA event pages.

Pure functions over an already-fetched HTML string — fetching is the
caller's job (urllib in the CLI, js.fetch in the Cloudflare Worker).
"""

from __future__ import annotations

import html
import re


UDISC_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.0 Safari/605.1.15"
)
PDGA_USER_AGENT = UDISC_USER_AGENT


def parse_udisc_leaderboard(page: str) -> tuple[str, list[tuple[str, int]]]:
    """Extract (layout_text, [(player_name, round_total_score), ...]) from
    a UDisc leaderboard page's HTML.

    UDisc 403s on requests without a desktop User-Agent — set one upstream
    when fetching (see UDISC_USER_AGENT)."""
    m_title = re.search(r"<title[^>]*>([^<]+)</title>", page)
    m_h1 = re.search(r"<h1[^>]*>([^<]+)</h1>", page)
    layout_text = " | ".join(
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

    return layout_text, players


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
