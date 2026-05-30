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

    Apps Script web apps redirect POSTs through script.googleusercontent.com;
    js.fetch follows redirects and (in CF Workers) preserves the POST body,
    so auto-follow is what we want. We just add a short retry for transient
    errors.
    """
    payload = _json.dumps(body)
    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            init = to_js(
                {
                    "method": "POST",
                    "headers": {"Content-Type": "application/json"},
                    "body": payload,
                },
                dict_converter=Object.fromEntries,
            )
            resp = await _js_fetch(url, init)
            text = await resp.text()
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
