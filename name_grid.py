# /// script
# dependencies = [
#     "archicad",
#     "perisso @ git+https://github.com/runxel/perisso.git",
# ]
# ///

import os
from archicad import ACConnection
import string

def get_grid_letter(index):
    """Convert 0-based index to A, B, C, ..., Z, AA, AB, etc."""
    result = ""
    while index >= 0:
        result = chr(65 + (index % 26)) + result
        index = (index // 26) - 1
    return result

def get_closest_floor(z, stories):
    """Return the index of the closest story."""
    # stories is expected to be a list of dicts with 'level'
    if not stories: return "0"
    
    closest_idx = 0
    min_dist = float('inf')
    
    for idx, story in enumerate(stories):
        dist = abs(story["level"] - z)
        if dist < min_dist:
            min_dist = dist
            closest_idx = idx
            
    return str(closest_idx)

def get_grid_label(x, y, x_grid, y_grid):
    x_label = x_grid.get(x, "?")
    y_label = y_grid.get(y, "?")
    return f"{x_label}{y_label}"

def main():
    conn = ACConnection.connect()
    if not conn:
        print("Failed to connect to Archicad.")
        return

    # Fetch Stories
    try:
        story_res = conn.commands.ExecuteAddOnCommand(
            conn.types.AddOnCommandId("TapirCommand", "GetStories"),
            {}
        )
        stories = story_res.get("stories", [])
        # Sort stories by level
        stories.sort(key=lambda s: s["level"])
    except Exception as e:
        print(f"Failed to fetch stories: {e}")
        stories = []

    print("Fetching Columns and Beams...")
    try:
        cols_res = conn.commands.GetElementsByType("Column")
        beams_res = conn.commands.GetElementsByType("Beam")
    except Exception as e:
        print(f"Failed to fetch elements: {e}")
        return

    col_guids = [el.elementId for el in cols_res]
    beam_guids = [el.elementId for el in beams_res]
    
    all_guids = col_guids + beam_guids
    if not all_guids:
        print("No columns or beams found.")
        return

    print(f"Found {len(col_guids)} Columns and {len(beam_guids)} Beams. Analyzing grid...")

    try:
        boxes_res = conn.commands.Get3DBoundingBoxes(all_guids)
    except Exception as e:
        print(f"Failed to fetch bounding boxes: {e}")
        return

    # Phase 1: Build the grid
    x_coords = set()
    y_coords = set()
    
    # We round coordinates to 1 decimal place to handle slight inaccuracies
    for bb_wrapper in boxes_res:
        bb = bb_wrapper.boundingBox3D
        x_center = round((bb.xMax + bb.xMin) / 2.0, 1)
        y_center = round((bb.yMax + bb.yMin) / 2.0, 1)
        x_coords.add(x_center)
        y_coords.add(y_center)
        
        # For beams, add both endpoints
        if bb.xMax - bb.xMin > 1.0:
            x_coords.add(round(bb.xMin, 1))
            x_coords.add(round(bb.xMax, 1))
        if bb.yMax - bb.yMin > 1.0:
            y_coords.add(round(bb.yMin, 1))
            y_coords.add(round(bb.yMax, 1))

    sorted_x = sorted(list(x_coords))
    sorted_y = sorted(list(y_coords))
    
    x_grid = {x: get_grid_letter(i) for i, x in enumerate(sorted_x)}
    y_grid = {y: str(i + 1) for i, y in enumerate(sorted_y)}

    print(f"Grid setup complete. X-Axes: {len(x_grid)}, Y-Axes: {len(y_grid)}")

    try:
        prop_id = conn.utilities.GetBuiltInPropertyId("General_ElementID")
    except Exception as e:
        print(f"Could not find General_ElementID property: {e}")
        return

    epv_list = []

    # Phase 2: Name Columns
    for i, guid in enumerate(col_guids):
        bb = boxes_res[i].boundingBox3D
        x_center = round((bb.xMax + bb.xMin) / 2.0, 1)
        y_center = round((bb.yMax + bb.yMin) / 2.0, 1)
        z_min = bb.zMin
        
        floor_idx = get_closest_floor(z_min, stories)
        grid_lbl = get_grid_label(x_center, y_center, x_grid, y_grid)
        
        new_id = f"C-{floor_idx}-{grid_lbl}"
        
        prop_val = conn.types.NormalStringPropertyValue(new_id)
        epv_list.append(conn.types.ElementPropertyValue(guid, prop_id, prop_val))

    # Phase 3: Name Beams
    offset = len(col_guids)
    for i, guid in enumerate(beam_guids):
        bb = boxes_res[offset + i].boundingBox3D
        x_center = round((bb.xMax + bb.xMin) / 2.0, 1)
        y_center = round((bb.yMax + bb.yMin) / 2.0, 1)
        z_min = bb.zMin
        
        floor_idx = get_closest_floor(z_min, stories)
        
        # Determine endpoints based on orientation
        if bb.xMax - bb.xMin > bb.yMax - bb.yMin:
            # Spans along X
            pt1_grid = get_grid_label(round(bb.xMin, 1), y_center, x_grid, y_grid)
            pt2_grid = get_grid_label(round(bb.xMax, 1), y_center, x_grid, y_grid)
        else:
            # Spans along Y
            pt1_grid = get_grid_label(x_center, round(bb.yMin, 1), x_grid, y_grid)
            pt2_grid = get_grid_label(x_center, round(bb.yMax, 1), x_grid, y_grid)
            
        new_id = f"B-{floor_idx}-{pt1_grid}-{pt2_grid}"
        
        prop_val = conn.types.NormalStringPropertyValue(new_id)
        epv_list.append(conn.types.ElementPropertyValue(guid, prop_id, prop_val))

    print("Applying new Element IDs...")
    try:
        # We need to chunk it because there might be thousands
        chunk_size = 500
        for i in range(0, len(epv_list), chunk_size):
            chunk = epv_list[i:i+chunk_size]
            conn.commands.SetPropertyValuesOfElements(chunk)
        print("Successfully renamed elements!")
    except Exception as e:
        print(f"Error applying names: {e}")

if __name__ == "__main__":
    main()
