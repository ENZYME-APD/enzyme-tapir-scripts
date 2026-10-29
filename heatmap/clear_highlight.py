#!/usr/bin/env python3
"""
Clear all Tapir highlights in Archicad and switch 3D wireframe off.

Usage:
  python3 clear_highlight.py
  python3 clear_highlight.py --port 19724

Standalone: needs only the Python standard library.
"""
import argparse
import json
import urllib.request


def call(port, body):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def find_port():
    for port in range(19723, 19744):
        try:
            if call(port, {"command": "API.IsAlive"}).get("succeeded"):
                return port
        except Exception:
            continue
    raise SystemExit("No running Archicad found on ports 19723-19743.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int)
    port = ap.parse_args().port or find_port()

    res = call(port, {
        "command": "API.ExecuteAddOnCommand",
        "parameters": {
            "addOnCommandId": {"commandNamespace": "TapirCommand",
                               "commandName": "HighlightElements"},
            "addOnCommandParameters": {"elements": [], "highlightedColors": [],
                                       "wireframe3D": False},
        },
    })
    if not res.get("succeeded"):
        raise SystemExit(f"Failed: {res.get('error')}")
    print("Highlight cleared.")


if __name__ == "__main__":
    main()
