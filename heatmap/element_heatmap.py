#!/usr/bin/env python3
"""
Element heatmap for Archicad via Tapir.

Colours any set of elements by the value of any property and highlights
them in Archicad.

Elements come from the current selection or from the whole model, narrowed
by element type, layer and/or classification (all filters combine with AND;
several values inside one filter combine with OR).

Numeric properties (length, area, volume, angle, number, integer) get a
blue -> red ramp split into bins. Anything else (text, enums, booleans) gets
one fixed colour per distinct value. Elements with no value are dark grey.

Deterministic: elements sorted by GUID, numbers rounded before binning,
categories sorted alphabetically, fixed palettes.

Values are in Archicad's base units: metres, m2, m3, radians.

Command line (the panel, element_heatmap_panel.py, uses the same functions):
  python3 element_heatmap.py --type Column --list-properties
  python3 element_heatmap.py --type Column --property "Column/Width"
  python3 element_heatmap.py --selection --property "General Parameters/Height"
  python3 element_heatmap.py --type Wall --layer "Structural - Bearing" \
                             --property "Wall/Thickness" --min 0.1 --max 0.4
  python3 element_heatmap.py --classification "Column" --property "ID"
  python3 element_heatmap.py --clear

Standard library only.
"""
__version__ = "2.1.2"

import argparse
import csv
import json
import urllib.request

# ---------------------------------------------------------------- palettes
RAMPS = {  # numeric styles, low -> high
    "Blue-Red": [(43, 131, 186), (171, 221, 164), (255, 255, 191), (253, 174, 97), (215, 25, 28)],
    "Viridis": [(68, 1, 84), (59, 82, 139), (33, 145, 140), (94, 201, 98), (253, 231, 37)],
    "Magma": [(0, 0, 4), (81, 18, 124), (183, 55, 121), (252, 137, 97), (252, 253, 191)],
    "Green-Red": [(26, 152, 80), (145, 207, 96), (254, 224, 139), (252, 141, 89), (215, 48, 39)],
    "Cool-Warm": [(59, 76, 192), (141, 176, 254), (221, 221, 221), (244, 154, 123), (180, 4, 38)],
    "Blues": [(239, 243, 255), (189, 215, 231), (107, 174, 214), (49, 130, 189), (8, 81, 156)],
    "Greys": [(240, 240, 240), (189, 189, 189), (130, 130, 130), (80, 80, 80), (20, 20, 20)],
}
CATEGORICALS = {  # text / enum styles
    "Bold": [(31, 119, 180), (255, 127, 14), (44, 160, 44), (214, 39, 40),
             (148, 103, 189), (140, 86, 75), (227, 119, 194), (188, 189, 34),
             (23, 190, 207), (255, 187, 120), (152, 223, 138), (174, 199, 232)],
    "Pastel": [(141, 211, 199), (255, 255, 179), (190, 186, 218), (251, 128, 114),
               (128, 177, 211), (253, 180, 98), (179, 222, 105), (252, 205, 229),
               (217, 217, 217), (188, 128, 189), (204, 235, 197), (255, 237, 111)],
    "Vivid": [(230, 25, 75), (60, 180, 75), (255, 225, 25), (0, 130, 200),
              (245, 130, 48), (145, 30, 180), (70, 240, 240), (240, 50, 230),
              (210, 245, 60), (250, 190, 212), (0, 128, 128), (170, 110, 40)],
}
RAMP = RAMPS["Blue-Red"]
CATEGORICAL = CATEGORICALS["Bold"]
NO_VALUE = (90, 90, 90)
GREY = [200, 200, 200, 60]  # elements not in the heatmap

ELEMENT_TYPES = [
    "Wall", "Column", "Beam", "Slab", "Roof", "Shell", "Morph", "Mesh",
    "Window", "Door", "Skylight", "Opening", "Object", "Lamp", "Zone",
    "Stair", "Railing", "CurtainWall", "CurtainWallPanel", "CurtainWallFrame",
    "ColumnSegment", "BeamSegment", "Hatch",
]


# -------------------------------------------------------------- connection
def call(port, command, params=None, tapir=True):
    """POST one command to Archicad's JSON API (Tapir add-on or built-in)."""
    if tapir:
        body = {"command": "API.ExecuteAddOnCommand",
                "parameters": {"addOnCommandId": {"commandNamespace": "TapirCommand",
                                                  "commandName": command},
                               "addOnCommandParameters": params or {}}}
    else:
        body = {"command": f"API.{command}"}
        if params is not None:
            body["parameters"] = params
    req = urllib.request.Request(f"http://127.0.0.1:{port}",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        res = json.load(r)
    if not res.get("succeeded", False):
        raise RuntimeError(f"{command} failed: {res.get('error')}")
    result = res.get("result", {})
    if tapir:
        result = result.get("addOnCommandResponse", result)
        if isinstance(result, dict) and "error" in result and len(result) == 1:
            raise RuntimeError(f"{command} failed: {result['error']}")
    return result


def find_port():
    for port in range(19723, 19744):
        try:
            call(port, "IsAlive", tapir=False)
            return port
        except Exception:
            continue
    raise RuntimeError("No running Archicad found on ports 19723-19743.")


def call_any(port, command, params=None):
    """Try Archicad's built-in command first, then the Tapir one of the same name."""
    try:
        return call(port, command, params, tapir=False)
    except Exception as first:
        try:
            return call(port, command, params, tapir=True)
        except Exception:
            raise first


def _ids(guids):
    return [{"elementId": {"guid": g}} for g in guids]


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


# ---------------------------------------------------------- model lookups
def list_layers(port):
    """[(index, name)] sorted by name."""
    attrs = call(port, "GetAttributesByType", {"attributeType": "Layer"})["attributes"]
    return sorted(((a["index"], a["name"].strip()) for a in attrs
                   if a["name"].strip() and a["name"].isprintable()),
                  key=lambda x: x[1].lower())


def list_classifications(port):
    """[(guid, label, depth, [descendant guids incl. self], system name)]."""
    out = []
    for sysm in call_any(port, "GetAllClassificationSystems")["classificationSystems"]:
        tree = call_any(port, "GetAllClassificationsInSystem",
                    {"classificationSystemId": sysm["classificationSystemId"]})
        out.append((None, sysm["name"], -1, [], sysm["name"]))

        def walk(items, depth):
            guids = []
            for it in items:
                c = it.get("classificationItem", it)
                g = c["classificationItemId"]["guid"]
                label = c["id"] + (f"  {c['name']}" if c.get("name") else "")
                pos = len(out)
                out.append(None)  # placeholder, filled after children
                sub = walk(c.get("children") or [], depth + 1)
                out[pos] = (g, label, depth, [g] + sub, sysm["name"])
                guids += [g] + sub
            return guids

        walk(tree.get("classificationItems", []), 0)
    return out


# --------------------------------------------------------- collect elements
def collect_elements(port, use_selection=False, element_types=None,
                     layer_indices=None, classification_guids=None):
    """Sorted list of element GUIDs matching the source and filters."""
    if use_selection:
        guids = [e["elementId"]["guid"] for e in call_any(port, "GetSelectedElements")["elements"]]
        if classification_guids:
            keep = set()
            for cg in classification_guids:
                keep.update(e["elementId"]["guid"] for e in call_any(
                    port, "GetElementsByClassification",
                    {"classificationItemId": {"guid": cg}})["elements"])
            guids = [g for g in guids if g in keep]
    elif classification_guids:
        found = set()
        for cg in classification_guids:
            found.update(e["elementId"]["guid"] for e in call_any(
                port, "GetElementsByClassification",
                {"classificationItemId": {"guid": cg}})["elements"])
        guids = list(found)
    elif element_types:
        found = set()
        for t in element_types:
            found.update(e["elementId"]["guid"] for e in call(
                port, "GetElementsByType", {"elementType": t}, tapir=False)["elements"])
        guids = list(found)
    else:
        guids = [e["elementId"]["guid"] for e in call(port, "GetAllElements", {}, tapir=False)["elements"]]

    if guids and (element_types or layer_indices):
        params = {}
        if element_types:
            params["elementTypes"] = list(element_types)
        if layer_indices:
            params["layerIndices"] = list(layer_indices)
        kept = []
        for chunk in _chunks(sorted(set(guids)), 2000):
            params["elements"] = _ids(chunk)
            kept += [e["elementId"]["guid"] for e in call(port, "FilterElements", params)["elements"]]
        guids = kept

    return sorted(set(guids))


# ------------------------------------------------------------ element index
def build_index(port, guids=None, progress=None):
    """Type, layer and classifications of every element, read once.

    Returns {guid: {"type": str, "layer": int, "classes": set(item guids)}}.
    With guids=None the whole model is indexed.
    """
    if guids is None:
        guids = [e["elementId"]["guid"] for e in
                 call(port, "GetAllElements", {}, tapir=False)["elements"]]
    guids = sorted(set(guids))
    idx = {}
    done = 0
    for chunk in _chunks(guids, 2000):
        det = call(port, "GetDetailsOfElements",
                   {"elements": _ids(chunk), "fields": ["type", "layerIndex"]})["detailsOfElements"]
        for g, d in zip(chunk, det):
            idx[g] = {"type": d.get("type") or "Unknown", "layer": d.get("layerIndex"),
                      "classes": set()}
        done += len(chunk)
        if progress:
            progress(f"Indexing elements… {done}/{len(guids)}")
    systems = call_any(port, "GetAllClassificationSystems")["classificationSystems"]
    sys_ids = [{"classificationSystemId": s["classificationSystemId"]} for s in systems]
    if sys_ids:
        for chunk in _chunks(guids, 2000):
            res = call_any(port, "GetClassificationsOfElements",
                           {"elements": _ids(chunk), "classificationSystemIds": sys_ids})
            for g, ec in zip(chunk, res.get("elementClassifications", [])):
                for c in ec.get("classificationIds", []) or []:
                    c = c.get("classificationId", c)
                    item = c.get("classificationItemId") if isinstance(c, dict) else None
                    if item and g in idx:
                        idx[g]["classes"].add(item["guid"])
    return idx


def expand_classes(idx, classifications):
    """Add every ancestor item to each element's classes, so picking a parent
    classification matches elements classified with any of its sub-items."""
    ancestors = {}
    for g, _, _, desc, _ in classifications:
        if g:
            for d in desc:
                ancestors.setdefault(d, set()).add(g)
    for rec in idx.values():
        rec["all_classes"] = set(rec["classes"])
        for c in rec["classes"]:
            rec["all_classes"] |= ancestors.get(c, set())
    return idx


def match(idx, guids, types=None, layers=None, classes=None):
    """GUIDs (from `guids`) whose index record passes the filters."""
    types = set(types or [])
    layers = set(layers or [])
    classes = set(classes or [])
    out = []
    for g in guids:
        r = idx.get(g)
        if r is None:
            continue
        if types and r["type"] not in types:
            continue
        if layers and r["layer"] not in layers:
            continue
        if classes and not (r.get("all_classes", r["classes"]) & classes):
            continue
        out.append(g)
    return out


# --------------------------------------------------------------- properties
def list_properties(port, guids, sample=25):
    """Properties available on the first `sample` elements.

    Returns [(property_guid, "Group/Name", value_type)] sorted by label.
    """
    if not guids:
        return []
    res = call_any(port, "GetAllPropertyIdsOfElements", {"elements": _ids(guids[:sample])})
    pids, seen = [], set()
    for item in res.get("propertyIdsOfElements", []):
        inner = item.get("propertyIdsOfElement", item)   # Tapir wraps, built-in doesn't
        for p in inner.get("propertyIds", []):
            g = p["propertyId"]["guid"]
            if g not in seen:
                seen.add(g)
                pids.append(g)
    props = []
    for chunk in _chunks(pids, 300):
        det = call_any(port, "GetDetailsOfProperties",
                       {"properties": [{"propertyId": {"guid": g}} for g in chunk]})
        for d in det.get("propertyDefinitions", []):
            pd = d.get("propertyDefinition", d)
            if not pd or "propertyId" not in pd:
                continue
            group = (pd.get("group") or {}).get("name", "")
            label = f"{group}/{pd.get('name', '')}" if group else pd.get("name", "")
            props.append((pd["propertyId"]["guid"], label, pd.get("type", "")))
    return sorted(props, key=lambda p: p[1].lower())


def find_property(props, query):
    """Match 'Group/Name', or just 'Name' when unique (case-insensitive)."""
    q = query.strip().lower()
    exact = [p for p in props if p[1].lower() == q]
    if exact:
        return exact[0]
    by_name = [p for p in props if p[1].lower().split("/", 1)[-1] == q]
    if len(by_name) == 1:
        return by_name[0]
    if by_name:
        raise RuntimeError("Ambiguous property name, use Group/Name: "
                           + ", ".join(p[1] for p in by_name))
    raise RuntimeError(f"Property not found: {query}")


def _plain(v):
    """Archicad property value -> float, str or None."""
    if v is None:
        return None
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict):  # enum value
        for k in ("displayValue", "nonLocalizedValue"):
            if v.get(k) not in (None, ""):
                return str(v[k])
        return None
    if isinstance(v, list):
        parts = [_plain(x) for x in v]
        parts = [str(p) for p in parts if p is not None]
        return ", ".join(sorted(parts)) if parts else None
    s = str(v).strip()
    if s in ("", "<Undefined>"):
        return None
    return s


def get_values(port, guids, property_guid):
    """{element guid: float | str | None}, using Archicad's typed values."""
    out = {}
    prop = [{"propertyId": {"guid": property_guid}}]
    for chunk in _chunks(guids, 500):
        res = call(port, "GetPropertyValuesOfElements",
                   {"elements": _ids(chunk), "properties": prop}, tapir=False)
        for g, item in zip(chunk, res["propertyValuesForElements"]):
            val = None
            if "propertyValues" in item:
                pv = item["propertyValues"][0]
                v = pv.get("propertyValue")
                if v and v.get("status", "normal") == "normal":
                    val = _plain(v.get("value"))
            out[g] = val
    return out


# ------------------------------------------------------------------ colours
def lerp_ramp(t, ramp=None):
    ramp = ramp or RAMP
    t = min(max(t, 0.0), 1.0)
    pos = t * (len(ramp) - 1)
    i = min(int(pos), len(ramp) - 2)
    f = pos - i
    a, b = ramp[i], ramp[i + 1]
    return [round(a[k] + (b[k] - a[k]) * f) for k in range(3)] + [255]


def extend_palette(base, n):
    """`base` colours, then extra distinct ones (golden-angle hues) up to n."""
    import colorsys
    out = list(base)
    k = 0
    while len(out) < n:
        h = (0.11 + k * 0.618033988749895) % 1.0
        s, v = (0.65, 0.85) if k % 2 == 0 else (0.45, 0.65)
        out.append(tuple(round(c * 255) for c in colorsys.hsv_to_rgb(h, s, v)))
        k += 1
    return out


def hex_to_rgba(hexstr, opacity_pct=100):
    s = hexstr.lstrip("#")
    return [int(s[i:i + 2], 16) for i in (0, 2, 4)] + [round(255 * min(max(opacity_pct, 0), 100) / 100)]


def fmt(x):
    return f"{x:.4g}"


def build_colours(values, vmin=None, vmax=None, bins=11,
                  ramp="Blue-Red", categorical="Bold", reverse=False):
    """Decide numeric vs categorical and colour every element.

    Returns (colours {guid: rgba}, legend [(label, rgb, count)], mode).
    """
    present = [v for v in values.values() if v is not None]
    numeric = bool(present) and all(isinstance(v, float) for v in present)
    rp = list(RAMPS.get(ramp, RAMP))
    cp = list(CATEGORICALS.get(categorical, CATEGORICAL))
    if reverse:
        rp.reverse()
        cp.reverse()
    colours, legend = {}, []
    missing = [g for g, v in values.items() if v is None]

    if numeric:
        nums = {g: round(v, 6) for g, v in values.items() if v is not None}
        lo = vmin if vmin is not None else min(nums.values())
        hi = vmax if vmax is not None else max(nums.values())
        span = (hi - lo) or 1.0
        n = max(int(bins), 2)
        counts = [0] * n
        for g, v in nums.items():
            b = min(max(int(round((v - lo) / span * (n - 1))), 0), n - 1)
            counts[b] += 1
            colours[g] = lerp_ramp(b / (n - 1), rp)
        for b in range(n):
            legend.append((fmt(lo + span * b / (n - 1)), lerp_ramp(b / (n - 1), rp)[:3], counts[b]))
        mode = "numeric"
    else:
        cats = sorted({str(v) for v in present}, key=lambda s: (s.lower(), s))
        index = {c: i for i, c in enumerate(cats)}
        cp = extend_palette(cp, len(cats))
        counts = [0] * len(cats)
        for g, v in values.items():
            if v is None:
                continue
            i = index[str(v)]
            counts[i] += 1
            colours[g] = list(cp[i % len(cp)]) + [255]
        for c, i in index.items():
            legend.append((c, cp[i % len(cp)], counts[i]))
        mode = "categorical"

    for g in missing:
        colours[g] = list(NO_VALUE) + [255]
    if missing:
        legend.append(("No value", NO_VALUE, len(missing)))
    return colours, legend, mode


# ---------------------------------------------------------------- highlight
NUMERIC_TYPES = {"integer", "real", "number", "length", "area", "volume", "angle"}


def highlight(port, colours, other=None, wireframe=True):
    """other: [r, g, b, a] for every element not in the heatmap (a = 0-255)."""
    guids = sorted(colours)
    call(port, "HighlightElements", {
        "elements": _ids(guids),
        "highlightedColors": [colours[g] for g in guids],
        "nonHighlightedColor": list(other or GREY),
        "wireframe3D": bool(wireframe),
    })


def clear_highlight(port):
    call(port, "HighlightElements",
         {"elements": [], "highlightedColors": [], "wireframe3D": False})


def run(port, guids, property_guid, vmin=None, vmax=None, bins=11,
        ramp="Blue-Red", categorical="Bold", reverse=False, other=None, wireframe=True):
    """Values -> colours -> highlight. Returns (values, colours, legend, mode)."""
    values = get_values(port, guids, property_guid)
    colours, legend, mode = build_colours(values, vmin, vmax, bins, ramp, categorical, reverse)
    highlight(port, colours, other, wireframe)
    return values, colours, legend, mode


def write_csv(path, values, colours, prop_label):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["guid", prop_label, "r", "g", "b"])
        for g in sorted(values):
            v = values[g]
            w.writerow([g, "" if v is None else v] + colours[g][:3])


# --------------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int)
    ap.add_argument("--selection", action="store_true", help="start from the Archicad selection")
    ap.add_argument("--type", action="append", default=[], help="element type, repeatable")
    ap.add_argument("--layer", action="append", default=[], help="layer name, repeatable")
    ap.add_argument("--classification", action="append", default=[],
                    help="classification ID (e.g. 'Column'), includes sub-items, repeatable")
    ap.add_argument("--property", help="'Group/Name' or a unique 'Name'")
    ap.add_argument("--list-properties", action="store_true")
    ap.add_argument("--min", type=float)
    ap.add_argument("--max", type=float)
    ap.add_argument("--bins", type=int, default=11)
    ap.add_argument("--style", default="Blue-Red", choices=list(RAMPS), help="numeric colour style")
    ap.add_argument("--cat-style", default="Bold", choices=list(CATEGORICALS), help="text/enum colour style")
    ap.add_argument("--reverse", action="store_true")
    ap.add_argument("--other-color", default="#c8c8c8", help="colour of elements not in the heatmap")
    ap.add_argument("--other-opacity", type=int, default=24, help="their opacity, 0-100 %%")
    ap.add_argument("--no-wireframe", action="store_true", help="keep other elements solid in 3D")
    ap.add_argument("--csv")
    ap.add_argument("--clear", action="store_true")
    ap.add_argument("--version", action="version", version=f"element_heatmap {__version__}")
    a = ap.parse_args()

    try:
        port = a.port or find_port()
        if a.clear:
            clear_highlight(port)
            print("Highlight cleared.")
            return

        layer_idx = None
        if a.layer:
            layers = {name.lower(): idx for idx, name in list_layers(port)}
            missing = [l for l in a.layer if l.lower() not in layers]
            if missing:
                raise RuntimeError(f"Layer not found: {', '.join(missing)}")
            layer_idx = [layers[l.lower()] for l in a.layer]

        class_guids = None
        if a.classification:
            items = [c for c in list_classifications(port) if c[0]]
            class_guids = []
            for q in a.classification:
                hits = [c for c in items if c[1].split("  ")[0].lower() == q.lower()]
                if not hits:
                    raise RuntimeError(f"Classification not found: {q}")
                for h in hits:
                    class_guids += h[3]

        unknown = [t for t in a.type if t not in ELEMENT_TYPES]
        if unknown:
            print(f"Note: uncommon element type(s) {unknown}, passing them through.")

        guids = collect_elements(port, a.selection, a.type or None, layer_idx, class_guids)
        print(f"{len(guids)} elements")
        if not guids:
            return

        props = list_properties(port, guids)
        if a.list_properties or not a.property:
            for _, label, typ in props:
                print(f"  {label}  [{typ}]")
            if not a.property:
                print("\nPick one with --property 'Group/Name'.")
            return

        pg, plabel, _ = find_property(props, a.property)
        values, colours, legend, mode = run(port, guids, pg, a.min, a.max, a.bins,
                                            a.style, a.cat_style, a.reverse,
                                            hex_to_rgba(a.other_color, a.other_opacity),
                                            not a.no_wireframe)
        print(f"{plabel}: {mode}")
        for label, rgb, count in legend:
            print(f"  {label:>14}  rgb{tuple(rgb)}  {count}")
        if a.csv:
            write_csv(a.csv, values, colours, plabel)
            print(f"Wrote {a.csv}")
    except RuntimeError as e:
        raise SystemExit(str(e))


if __name__ == "__main__":
    main()
