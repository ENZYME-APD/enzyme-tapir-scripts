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

    print(f"Found {len(grid_stacks)} vertical column stacks.")

    new_columns_data = []
    guids_to_delete = []

    # Process each stack (from top to bottom)
    for (x, y), stack in grid_stacks.items():
        # Sort descending by Z (highest column first)
        stack.sort(key=lambda col: col["z"], reverse=True)
        
        for idx, col in enumerate(stack):
            # Base size 0.4m, grows by 0.025m for every column above it
            size = 0.4 + (idx * 0.025)
            
            new_columns_data.append({
                "coordinates": {"x": col["x"], "y": col["y"], "z": col["z"]},
                "height": col["height"],
                "width": size,
                "depth": size
            })
            guids_to_delete.append({"guid": col["guid"]})

    print(f"Replacing {len(new_columns_data)} columns with optimized sizes...")
    
    # Create the new optimized columns
    try:
        res = conn.commands.ExecuteAddOnCommand(
            conn.types.AddOnCommandId("TapirCommand", "CreateColumns"),
            {"columnsData": new_columns_data}
        )
        created_elements = res.get("elements", [])
        print(f"Successfully created {len(created_elements)} optimized columns.")
    except Exception as e:
        print(f"Failed to create new columns: {e}")
        return

    # Delete the old columns
    try:
        conn.commands.DeleteElements([conn.types.ElementId(g["guid"]) for g in guids_to_delete])
        print(f"Cleaned up {len(guids_to_delete)} old columns.")
    except Exception as e:
        print(f"Failed to delete old columns: {e}")

if __name__ == "__main__":
    main()
