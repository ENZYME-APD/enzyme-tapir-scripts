# /// script
# dependencies = [
#     "archicad",
#     "perisso @ git+https://github.com/runxel/perisso.git",
# ]
# ///

import os
from archicad import ACConnection
from collections import defaultdict

def main():
    conn = ACConnection.connect()
    if not conn:
        print("Failed to connect to Archicad.")
        return

    print("Fetching all columns...")
    try:
        cols_res = conn.commands.GetElementsByType("Column")
        if not cols_res:
            print("No columns found in the project.")
            return
    except Exception as e:
        print(f"Failed to fetch columns: {e}")
        return

    col_guids = [el.elementId for el in cols_res]
    print(f"Found {len(col_guids)} columns. Analyzing geometry...")

    # Fetch bounding boxes to determine position and height
    try:
        boxes_res = conn.commands.Get3DBoundingBoxes(col_guids)
    except Exception as e:
        print(f"Failed to fetch bounding boxes: {e}")
        return

    # Group by XY center point
    grid_stacks = defaultdict(list)
    
    for i, bb_wrapper in enumerate(boxes_res):
        bb = bb_wrapper.boundingBox3D
        x_center = round((bb.xMax + bb.xMin) / 2.0, 3)
        y_center = round((bb.yMax + bb.yMin) / 2.0, 3)
        
        z_min = bb.zMin
        height = bb.zMax - bb.zMin
        
        grid_stacks[(x_center, y_center)].append({
            "guid": col_guids[i].guid,
            "x": x_center,
            "y": y_center,
            "z": z_min,
            "height": height
        })

    # Get property IDs for Width and Depth
    try:
        width_pid = conn.commands.GetPropertyIds([{"type": "BuiltIn", "nonLocalizedName": "Column_CoreWidth"}])[0].propertyId
        depth_pid = conn.commands.GetPropertyIds([{"type": "BuiltIn", "nonLocalizedName": "Column_CoreDepth"}])[0].propertyId
    except Exception as e:
        print(f"Failed to find core width/depth properties: {e}")
        return
        
    print(f"Found {len(grid_stacks)} vertical column stacks.")

    property_updates = []

    # Process each stack (from top to bottom)
    for (x, y), stack in grid_stacks.items():
        # Sort descending by Z (highest column first)
        stack.sort(key=lambda col: col["z"], reverse=True)
        
        for idx, col in enumerate(stack):
            # Base size 0.4m, grows by 0.025m for every column above it
            size = 0.4 + (idx * 0.025)
            
            # Prepare updates for Width and Depth
            el_id = conn.types.ElementId(col["guid"])
            val = conn.types.NormalLengthPropertyValue(size)
            
            property_updates.append(conn.types.ElementPropertyValue(el_id, width_pid, val))
            property_updates.append(conn.types.ElementPropertyValue(el_id, depth_pid, val))

    print(f"Optimizing {len(property_updates) // 2} columns in place...")
    
    # Update the existing columns
    try:
        conn.commands.SetPropertyValuesOfElements(property_updates)
        print(f"Successfully updated all columns.")
    except Exception as e:
        print(f"Failed to update columns: {e}")

if __name__ == "__main__":
    main()
