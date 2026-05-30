"""I/O shims for the Cloudflare Workers Python runtime.

The standard library's urllib doesn't work in the Workers Python runtime;
outbound HTTP has to go through the JavaScript fetch API exposed via the
`js` interop module.

This module wraps that with the same shape the CLI uses (a fetcher that
returns text plus a JSON POST helper), so the higher-level matching/dedup
code can remain platform-agnostic.
"""

from __future__ import annotations

import json as _json

from js import fetch as _js_fetch, Object  # type: ignore[import-not-found]
from pyodide.ffi import to_js  # type: ignore[import-not-found]


async def fetch_text(url: str, *, user_agent: str | None = None) -> str:
    """GET ``url``; return the response body as a decoded string.

    ``user_agent`` lets callers pass a desktop UA — PDGA and UDisc both
    403 anonymous fetches.
    """
    headers = {"User-Agent": user_agent} if user_agent else {}
    init = to_js(
        {"method": "GET", "headers": headers},
        dict_converter=Object.fromEntries,
    )
    resp = await _js_fetch(url, init)
    if not resp.ok:
        raise RuntimeError(f"GET {url} returned HTTP {resp.status}")
    return await resp.text()


async def post_json(url: str, body: dict, *, max_retries: int = 2) -> dict:
    """POST a JSON body to ``url``; return the parsed JSON response.

    Apps Script web apps respond to /exec with a 302 → script.googleusercontent.com.
    js.fetch's default ``redirect: 'follow'`` downgrades POST→GET on 302
    (legacy fetch-spec behavior), which lands the request on doGet and
    returns the help text instead of running doPost. We handle the
    redirect manually so the method/body are preserved.
    """
    payload = _json.dumps(body)
    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            text = await _post_following_redirects(url, payload)
            try:
                return _json.loads(text)
            except Exception:
                raise RuntimeError(
                    f"POST {url} returned non-JSON: {text[:200]!r}"
                )
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                continue
            raise
    raise RuntimeError(f"unreachable: {last_err}")


async def _post_following_redirects(url: str, payload: str,
                                    *, hop_cap: int = 5) -> str:
    cur = url
    for _ in range(hop_cap):
        init = to_js(
            {
                "method": "POST",
                "headers": {"Content-Type": "application/json"},
                "body": payload,
                "redirect": "manual",
            },
            dict_converter=Object.fromEntries,
        )
        resp = await _js_fetch(cur, init)
        status = int(resp.status)
        if status in (301, 302, 303, 307, 308):
            loc = resp.headers.get("location") if resp.headers else None
            if not loc:
                break
            cur = loc
            continue
        return await resp.text()
    raise RuntimeError(f"too many redirects from {url}")
