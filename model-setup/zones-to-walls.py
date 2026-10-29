# /// script
# dependencies = [
#     "archicad",
#     "perisso @ git+https://github.com/runxel/perisso.git",
# ]
# ///

import math
from archicad import ACConnection

def distance(p1, p2):
    return math.hypot(p2[0] - p1[0], p2[1] - p1[1])

def is_point_on_segment(p, a, b, tol=1e-3):
    cross = (p[1] - a[1]) * (b[0] - a[0]) - (p[0] - a[0]) * (b[1] - a[1])
    if abs(cross) > tol:
        return False
    dot = (p[0] - a[0]) * (b[0] - a[0]) + (p[1] - a[1]) * (b[1] - a[1])
    sq_len = (b[0] - a[0])**2 + (b[1] - a[1])**2
    if dot > tol and dot < sq_len - tol:
        return True
    return False

def get_minimal_segments(zone_edges, all_points):
    minimal_segments = []
    for edge in zone_edges:
        a, b = edge
        points_on_edge = []
        for p in all_points:
            if is_point_on_segment(p, a, b):
                points_on_edge.append(p)
                
        if not points_on_edge:
            minimal_segments.append((a, b))
        else:
            points_on_edge.sort(key=lambda p: distance(a, p))
            current = a
            for p in points_on_edge:
                minimal_segments.append((current, p))
                current = p
            minimal_segments.append((current, b))
    return minimal_segments

def normalize_segment(seg):
    a, b = seg
    a = (round(a[0], 3), round(a[1], 3))
    b = (round(b[0], 3), round(b[1], 3))
    return tuple(sorted((a, b)))

def ensure_layers(conn):
    print("Checking and ensuring required layers exist...")
    res = conn.commands.ExecuteAddOnCommand(
        conn.types.AddOnCommandId("TapirCommand", "GetAttributesByType"),
        {"attributeType": "Layer"}
    )
    existing_layers = {attr.get("name"): attr.get("index") for attr in res.get("attributes", [])}
    
    needed_layers = ["enzyme-facade-wall", "enzyme-internal-partition"]
    layers_to_create = []
    
    for l in needed_layers:
        if l not in existing_layers:
            layers_to_create.append({"name": l})
            
    if layers_to_create:
        print(f"Creating missing layers: {layers_to_create}")
        conn.commands.ExecuteAddOnCommand(
            conn.types.AddOnCommandId("TapirCommand", "CreateLayers"),
            {
                "layerDataArray": layers_to_create,
                "overwriteExisting": False
            }
        )
        # Re-fetch layer indices
        res = conn.commands.ExecuteAddOnCommand(
            conn.types.AddOnCommandId("TapirCommand", "GetAttributesByType"),
            {"attributeType": "Layer"}
        )
        existing_layers = {attr.get("name"): attr.get("index") for attr in res.get("attributes", [])}
        
    return {l: existing_layers[l] for l in needed_layers if l in existing_layers}

def main():
    conn = ACConnection.connect()
    if not conn:
        print("Failed to connect to Archicad.")
        return

    print("Fetching selected elements...")
    sel_res = conn.commands.ExecuteAddOnCommand(
        conn.types.AddOnCommandId("TapirCommand", "GetSelectedElements"),
        {}
    )
    selected_guids = {el["elementId"]["guid"] for el in sel_res.get("elements", [])}
    
    if not selected_guids:
        print("No elements selected. Please select zones in Archicad.")
        return

    # Filter to only Zones
    all_zones = conn.commands.GetElementsByType("Zone")
    zone_guids = [str(z.elementId.guid).upper() for z in all_zones if str(z.elementId.guid).upper() in selected_guids]

    if not zone_guids:
        print("No Zones in your selection.")
        return

    print(f"Found {len(zone_guids)} selected Zones. Retrieving geometry...")

    # Get Zone Details (for polygon Outline)
    details_res = conn.commands.ExecuteAddOnCommand(
        conn.types.AddOnCommandId("TapirCommand", "GetDetailsOfElements"),
        {"elements": [{"elementId": {"guid": g}} for g in zone_guids]}
    )
    zone_details_list = details_res.get("detailsOfElements", [])

    # Get Bounding Boxes (for zMin and height)
    boxes_res = conn.commands.Get3DBoundingBoxes([conn.types.ElementId(g) for g in zone_guids])
    
    # Extract topology points and edges
    zone_edges_map = {}
    all_points = set()
    zone_info = {}

    for i, guid in enumerate(zone_guids):
        # We need the inner 'details' object from the response item
        if i >= len(zone_details_list):
            print(f"Warning: Details not found for zone {guid}")
            continue
            
        z_item = zone_details_list[i]
        z_det = z_item.get("details", {})
        bb = boxes_res[i].boundingBox3D
        
        polygon = z_det.get("polygonOutline", [])
        if not polygon or len(polygon) < 3:
            print(f"Zone {guid} has no valid polygonOutline, skipping.")
            continue
            
        z_min = bb.zMin
        height = bb.zMax - bb.zMin
        zone_info[guid] = {"zMin": z_min, "height": height}
        
        edges = []
        for j in range(len(polygon)):
            a = (polygon[j]["x"], polygon[j]["y"])
            # In Tapir polygons, the last point is sometimes duplicate of the first point,
            # but we can safely handle it
            next_pt = polygon[(j+1) % len(polygon)]
            b = (next_pt["x"], next_pt["y"])
            if distance(a, b) > 1e-4:
                edges.append((a, b))
                all_points.add(a)
                all_points.add(b)
                
        zone_edges_map[guid] = edges

    print("Calculating topology and segment intersections...")
    
    segment_counts = {}
    segment_owners = {}
    directed_segments = {}
    
    for guid, edges in zone_edges_map.items():
        min_segs = get_minimal_segments(edges, list(all_points))
        for seg in min_segs:
            n_seg = normalize_segment(seg)
            if distance(n_seg[0], n_seg[1]) < 1e-4:
                continue
            if n_seg not in segment_counts:
                segment_counts[n_seg] = 0
                segment_owners[n_seg] = []
                directed_segments[n_seg] = seg
            segment_counts[n_seg] += 1
            segment_owners[n_seg].append(guid)
            
    print(f"Extracted {len(segment_counts)} unique wall segments.")
    
    layer_indices = ensure_layers(conn)
    facade_layer = layer_indices.get("enzyme-facade-wall")
    partition_layer = layer_indices.get("enzyme-internal-partition")

    facade_walls = []
    partition_walls = []
    partition_lengths = []
    
    for n_seg, count in segment_counts.items():
        # Get the height/z from the first zone that owns this segment
        owner_guid = segment_owners[n_seg][0]
        z_min = zone_info[owner_guid]["zMin"]
        height = zone_info[owner_guid]["height"]
        
        # Use the directed segment to preserve consistent CCW drawing direction
        a, b = directed_segments[n_seg]
        wall = {
            "begCoordinate": {"x": a[0], "y": a[1]},
            "endCoordinate": {"x": b[0], "y": b[1]},
            "zCoordinate": z_min,
            "height": height
        }
        
        if count == 1:
            # Facade
            wall["thickness"] = 0.35
            wall["referenceLineLocation"] = "Inside"
            facade_walls.append(wall)
        else:
            # Partition
            wall["thickness"] = 0.15
            wall["referenceLineLocation"] = "Center"
            partition_walls.append(wall)
            partition_lengths.append(distance(a, b))

    print(f"Creating {len(facade_walls)} facade walls and {len(partition_walls)} partition walls...")
    
    facade_guids = []
    partition_guids = []

    if facade_walls:
        res = conn.commands.ExecuteAddOnCommand(
            conn.types.AddOnCommandId("TapirCommand", "CreateWalls"),
            {"wallsData": facade_walls}
        )
        facade_guids = [el["elementId"]["guid"] for el in res.get("elements", [])]
        
    if partition_walls:
        res = conn.commands.ExecuteAddOnCommand(
            conn.types.AddOnCommandId("TapirCommand", "CreateWalls"),
            {"wallsData": partition_walls}
        )
        partition_guids = [el["elementId"]["guid"] for el in res.get("elements", [])]

    print("Assigning layers to the new walls...")
    
    if facade_guids and facade_layer is not None:
        conn.commands.ExecuteAddOnCommand(
            conn.types.AddOnCommandId("TapirCommand", "SetDetailsOfElements"),
            {"elementsWithDetails": [{"elementId": {"guid": g}, "details": {"layerIndex": facade_layer}} for g in facade_guids]}
        )
        
    if partition_guids and partition_layer is not None:
        conn.commands.ExecuteAddOnCommand(
            conn.types.AddOnCommandId("TapirCommand", "SetDetailsOfElements"),
            {"elementsWithDetails": [{"elementId": {"guid": g}, "details": {"layerIndex": partition_layer}} for g in partition_guids]}
        )

    print("Successfully generated all walls from zones!")

if __name__ == "__main__":
    main()
