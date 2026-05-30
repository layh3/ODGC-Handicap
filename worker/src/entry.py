from workers import Response
import json


async def on_fetch(request, env):
    if request.method == "GET":
        return Response(
            "ODGC HC Worker — alive. POST {action: 'ping', upstream_url: '<apps-script-url>'} "
            "to verify connectivity to Apps Script.",
            headers={"content-type": "text/plain"},
        )
    if request.method != "POST":
        return Response("method not allowed", status=405)

    try:
        body_text = await request.text()
        body = json.loads(body_text) if body_text else {}
    except Exception as e:
        return Response(json.dumps({"ok": False, "error": f"bad json: {e}"}),
                        status=400, headers={"content-type": "application/json"})

    action = body.get("action", "ping")
    upstream = body.get("upstream_url")
    if not upstream:
        return Response(
            json.dumps({"ok": False, "error": "upstream_url required"}),
            status=400, headers={"content-type": "application/json"})

    # Workers Python uses the JS fetch API via the `js` module
    from js import fetch, Object
    from pyodide.ffi import to_js

    init = to_js({
        "method": "POST",
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"action": action}),
    }, dict_converter=Object.fromEntries)

    resp = await fetch(upstream, init)
    text = await resp.text()
    try:
        parsed = json.loads(text)
    except Exception:
        parsed = {"raw": text[:200]}

    return Response(
        json.dumps({
            "ok": True,
            "worker_says": "i can reach apps script",
            "apps_script_returned": parsed,
        }, indent=2),
        headers={"content-type": "application/json"},
    )
