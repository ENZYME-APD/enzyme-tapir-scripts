#!/usr/bin/env python3
"""
Column size heatmap for Archicad via Tapir.

Colours every column by its cross-section size (max of width/depth) and
highlights it in Archicad. Deterministic: same model -> same colours.
  - columns sorted by GUID
  - sizes rounded to 1 mm before binning
  - fixed colour ramp, fixed bin count
  - range is either fixed (--min/--max) or taken from the data

Usage:
  python column_heatmap.py                 # auto range, 11 bins
  python column_heatmap.py --min 0.4 --max 0.65 --bins 11
  python column_heatmap.py --clear         # remove highlight
  python column_heatmap.py --csv out.csv   # also write a size table

Needs only the Python standard library. Archicad must be running with Tapir.
"""
import argparse
import csv
import json
import urllib.request

# Fixed ramp, small -> large (blue -> yellow -> red). RGBA, 0-255.
RAMP = [
    (43, 131, 186), (171, 221, 164), (255, 255, 191),
    (253, 174, 97), (215, 25, 28),
]
GREY = [200, 200, 200, 60]


def call(port, command, params, tapir=True):
    """POST one command to Archicad's JSON API."""
    if tapir:
        body = {
            "command": "API.ExecuteAddOnCommand",
            "parameters": {
                "addOnCommandId": {"commandNamespace": "TapirCommand", "commandName": command},
                "addOnCommandParameters": params,
            },
        }
    else:
        body = {"command": f"API.{command}", "parameters": params}
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        res = json.load(r)
    if not res.get("succeeded", False):
        raise RuntimeError(f"{command} failed: {res.get('error')}")
    result = res["result"]
    return result.get("addOnCommandResponse", result) if tapir else result


def find_port():
    for port in range(19723, 19744):
        try:
            call(port, "IsAlive", {}, tapir=False)
            return port
        except Exception:
            continue
    raise SystemExit("No running Archicad found on ports 19723-19743.")


def lerp_ramp(t):
    """t in [0,1] -> RGBA from the fixed ramp."""
    t = min(max(t, 0.0), 1.0)
    pos = t * (len(RAMP) - 1)
    i = min(int(pos), len(RAMP) - 2)
    f = pos - i
    a, b = RAMP[i], RAMP[i + 1]
    return [round(a[k] + (b[k] - a[k]) * f) for k in range(3)] + [255]


def clear_highlight(port):
    """Remove all highlights and switch 3D wireframe off."""
    call(port, "HighlightElements",
         {"elements": [], "highlightedColors": [], "wireframe3D": False})


def apply_heatmap(port, vmin=None, vmax=None, bins=11):
    """Colour every column by size. Returns (rows, lo, hi, n)."""
    cols = call(port, "GetElementsByType", {"elementType": "Column"}, tapir=False)["elements"]
    cols.sort(key=lambda e: e["elementId"]["guid"])
    if not cols:
        raise RuntimeError("No columns in the model.")

    det = call(port, "GetDetailsOfElements", {"elements": cols})["detailsOfElements"]

    rows = []
    for e, d in zip(cols, det):
        dd = d.get("details", {})
        if dd.get("circleBased"):
            size = dd.get("width", 0.0)
        else:
            size = max(dd.get("width", 0.0), dd.get("depth", 0.0))
        rows.append({
            "guid": e["elementId"]["guid"],
            "floor": d.get("floorIndex"),
            "x": round(dd.get("origin", {}).get("x", 0.0), 3),
            "y": round(dd.get("origin", {}).get("y", 0.0), 3),
            "size": round(size, 3),
        })

    lo = vmin if vmin is not None else min(r["size"] for r in rows)
    hi = vmax if vmax is not None else max(r["size"] for r in rows)
    span = (hi - lo) or 1.0
    n = max(bins, 2)

    for r in rows:
        t = (r["size"] - lo) / span
        b = min(max(int(round(t * (n - 1))), 0), n - 1)  # snap to bin
        r["bin"] = b
        r["rgba"] = lerp_ramp(b / (n - 1))

    call(port, "HighlightElements", {
        "elements": [{"elementId": {"guid": r["guid"]}} for r in rows],
        "highlightedColors": [r["rgba"] for r in rows],
        "nonHighlightedColor": GREY,
        "wireframe3D": True,
    })
    return rows, lo, hi, n


def legend(rows, lo, hi, n):
    """List of (size_m, rgb, count) per bin."""
    span = (hi - lo) or 1.0
    out = []
    for b in range(n):
        out.append((lo + span * b / (n - 1),
                    lerp_ramp(b / (n - 1))[:3],
                    sum(1 for r in rows if r["bin"] == b)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int)
    ap.add_argument("--min", type=float, help="size (m) mapped to blue")
    ap.add_argument("--max", type=float, help="size (m) mapped to red")
    ap.add_argument("--bins", type=int, default=11)
    ap.add_argument("--csv")
    ap.add_argument("--clear", action="store_true")
    a = ap.parse_args()

    port = a.port or find_port()

    if a.clear:
        clear_highlight(port)
        print("Highlight cleared.")
        return

    try:
        rows, lo, hi, n = apply_heatmap(port, a.min, a.max, a.bins)
    except RuntimeError as e:
        raise SystemExit(str(e))

    print(f"{len(rows)} columns, range {lo*1000:.0f}-{hi*1000:.0f} mm, {n} bins")
    for size, rgb, count in legend(rows, lo, hi, n):
        print(f"  {size*1000:6.0f} mm  rgb{tuple(rgb)}  {count:4d} cols")

    if a.csv:
        with open(a.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["guid", "floor", "x", "y", "size", "bin", "rgba"])
            w.writeheader()
            w.writerows(rows)
        print(f"Wrote {a.csv}")


if __name__ == "__main__":
    main()
