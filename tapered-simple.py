# /// script
# dependencies = [
#     "archicad",
#     "perisso @ git+https://github.com/runxel/perisso.git",
# ]
# ///

import sys
import os
import subprocess

try:
    from perisso import tapir
    from perisso import Coordinate, Polyline
    from archicad import ACConnection
except ImportError as e:
    print(f"Import Error: {e}")
    print("Please make sure perisso and archicad packages are installed.")
    sys.exit(1)

def distribute_points(length, step):
    pts = list(range(0, int(length), int(step)))
    if pts[-1] != length:
        pts.append(length)
    return pts

def get_grid_columns(width_x, length_y):
    pts = []
    # 6m spans
    for x in range(0, int(width_x) + 1, 6):
        for y in range(0, int(length_y) + 1, 6):
            pts.append((float(x), float(y)))
    return pts

def get_grid_beam_lines(width_x, length_y):
    lines = []
    # Horizontal beams (along X)
    for y in range(0, int(length_y) + 1, 6):
        for x in range(0, int(width_x), 6):
            lines.append(((float(x), float(y)), (float(x+6), float(y))))
            
    # Vertical beams (along Y)
    for x in range(0, int(width_x) + 1, 6):
        for y in range(0, int(length_y), 6):
            lines.append(((float(x), float(y)), (float(x), float(y+6))))
    return lines

def setup_properties(conn):
    print("Setting up properties...")
    try:
        prop_id = conn.utilities.GetUserDefinedPropertyId("Scripting", "ScriptID")
        print(f"Successfully retrieved ScriptID property: {prop_id}")
        return prop_id
    except Exception as e:
        print(f"Warning: Could not get 'ScriptID' property in 'Scripting' group. Please create it manually: {e}")
        return None

def manage_existing_elements(conn, prop_id):
    if not prop_id:
        return
        
    print("Checking for previously generated elements...")
    elements_to_delete = []
    
    # Check Slabs, Columns, Beams
    for type_name in ["Slab", "Column", "Beam"]:
        try:
            # Built-in namespace for standard archicad JSON API
            els = conn.commands.GetElementsByType(type_name)
            if els:
                all_els = [e.elementId for e in els]
                
                # Fetch the scriptID property
                try:
                    prop_values = conn.commands.GetPropertyValuesOfElements(all_els, [prop_id])
                except Exception as e:
                    print(f"Warning: Failed to get property values: {e}")
                    continue
                
                for el, vals_wrapper in zip(all_els, prop_values):
                    # vals_wrapper is PropertyValuesOfElement (has propertyValues list)
                    if hasattr(vals_wrapper, "propertyValues"):
                        for v in vals_wrapper.propertyValues:
                            val = None
                            if hasattr(v, "propertyValue") and v.propertyValue and hasattr(v.propertyValue, "value"):
                                val = v.propertyValue.value
                            elif hasattr(v, "propertyValue") and v.propertyValue and isinstance(v.propertyValue, dict) and "value" in v.propertyValue:
                                val = v.propertyValue["value"]
                                
                            if val in ["Tapered", "tapered.py"]:
                                elements_to_delete.append({"elementId": {"guid": str(el.guid)}})
        except Exception as e:
            print(f"Warning while scanning {type_name}s: {e}")
            
    if elements_to_delete:
        print(f"Found {len(elements_to_delete)} elements tagged with 'Tapered'.")
        script = f'display dialog "Found {len(elements_to_delete)} previously generated \'Tapered\' elements.\\n\\nDo you want to delete them?" with title "Delete old elements" buttons {{"Yes", "No"}} default button "No" with icon caution'
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        
        if "button returned:Yes" in result.stdout:
            try:
                # Tapir's DeleteElements command
                conn.commands.ExecuteAddOnCommand(
                    conn.types.AddOnCommandId("TapirCommand", "DeleteElements"),
                    {"elements": elements_to_delete}
                )
                print(f"Successfully deleted {len(elements_to_delete)} elements.")
            except Exception as e:
                print(f"Failed to delete elements: {e}")




def tag_elements(conn, elements_list, prop_id):
    if not prop_id or not elements_list:
        return
    try:
        prop_val = conn.types.NormalStringPropertyValue("tapered.py")
        epvs = [conn.types.ElementPropertyValue(el, prop_id, prop_val) for el in elements_list]
        conn.commands.SetPropertyValuesOfElements(epvs)
    except Exception as e:
        print(f"Warning: Failed to tag elements: {e}")

def main():
    conn = ACConnection.connect()
    assert conn, "Could not connect to Archicad."
    
    # 1. Setup Property and Handle Cleanup
    prop_id = setup_properties(conn)
    manage_existing_elements(conn, prop_id)
    
    print("Adapting to existing story settings...")
    try:
        res = conn.commands.ExecuteAddOnCommand(
            conn.types.AddOnCommandId("TapirCommand", "GetStories"),
            {}
        )
        stories = res.get("stories", [])
        
        # Sort stories by level
        stories.sort(key=lambda s: s.get("level", 0.0))
        
        if len(stories) < 11:
            missing = 11 - len(stories)
            script = f'display dialog "The project has only {len(stories)} stories. The tapered building requires 11 floors.\\n\\nDo you want to automatically create {missing} more stories by copying the top one?" with title "Not Enough Stories" buttons {{"Yes", "No"}} default button "Yes"'
            user_res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
            
            if "button returned:Yes" in user_res.stdout:
                # Add missing stories based on the last one
                last_story = stories[-1] if stories else {"level": 0.0, "name": "Ground", "dispOnSections": True}
                last_level = last_story.get("level", 0.0)
                
                # Guess typical height from last two stories, or default to 3.0m
                if len(stories) >= 2:
                    typical_height = last_level - stories[-2].get("level", 0.0)
                    if typical_height <= 0:
                        typical_height = 3.0
                else:
                    typical_height = 3.0
                    
                for i in range(missing):
                    new_level = last_level + typical_height * (i + 1)
                    new_index = len(stories) + 1
                    stories.append({
                        "name": f"Generated Floor {new_index}",
                        "level": new_level,
                        "dispOnSections": True
                    })
                
                conn.commands.ExecuteAddOnCommand(
                    conn.types.AddOnCommandId("TapirCommand", "SetStories"),
                    {"stories": stories}
                )
                print(f"Successfully generated {missing} new stories.")
            else:
                print("Proceeding with insufficient stories. Geometry may be compressed or skipped.")
                
    except Exception as e:
        print(f"Warning: Could not fetch or set stories natively via Tapir: {e}")
        stories = [{"level": 0.0, "name": "Fallback", "dispOnSections": True}]
        
    floors_info = []
    for idx, story in enumerate(stories):
        if idx >= 11:
            break
            
        if idx < 2:
            length = 36
            width = 36
        elif idx < 3:
            length = 36
            width = 24
        elif idx < 5:
            length = 30
            width = 18
        elif idx < 7:
            length = 24
            width = 18
        elif idx < 9:
            length = 18
            width = 12
        else:
            length = 12
            width = 12
            
        z = story.get("level", 0.0)
        
        # Calculate height to the next story if available, else fallback to 3.0m
        if idx + 1 < len(stories):
            height = stories[idx + 1].get("level", 0.0) - z
        else:
            height = 3.0
            
        floors_info.append({
            "name": story.get("name", f"Floor {idx}"),
            "z": z,
            "length": length,
            "width": width,
            "height": height,
            "floorIndex": idx
        })
        

    roof_z = floors_info[-1]["z"] + floors_info[-1]["height"]

    print("Generating geometry...")
    all_slabs = []
    all_columns = []
    all_beams = []
    
    for i, floor in enumerate(floors_info):
        # Create Slab
        l = floor["length"]
        w = floor["width"]
        z = floor["z"]
        # Counter-clockwise polygon
        coords = [
            Coordinate(0, 0, z),
            Coordinate(w, 0, z),
            Coordinate(w, l, z),
            Coordinate(0, l, z)
        ]
        poly = Polyline(coords)
        try:
            slabs = tapir.CreateSlabs(polylines=poly, level=z)
            if slabs and "elements" in slabs:
                all_slabs.extend([e["elementId"] for e in slabs["elements"]])
            print(f"Created slab for {floor['name']}")
        except Exception as e:
            print(f"Error creating slab: {e}")
            
        # Create Columns
        # Columns should only be built to support the floor above them. 
        # If the building tapers, we use the next floor's length and width to avoid sticking-out columns.
        col_length = floors_info[i+1]["length"] if i + 1 < len(floors_info) else l
        col_width = floors_info[i+1]["width"] if i + 1 < len(floors_info) else w
        
        col_pts_2d = get_grid_columns(col_width, col_length)
        col_data = [{"coordinates": {"x": p[0], "y": p[1], "z": z}, "height": floor["height"]} for p in col_pts_2d]
        try:
            res = conn.commands.ExecuteAddOnCommand(
                conn.types.AddOnCommandId("TapirCommand", "CreateColumns"),
                {"columnsData": col_data}
            )
            if res and "elements" in res:
                all_columns.extend([e["elementId"] for e in res["elements"]])
            print(f"Created {len(col_pts_2d)} columns for {floor['name']}")
        except Exception as e:
            print(f"Error creating columns: {e}")
            
        # Create Beams
        beam_lines = get_grid_beam_lines(w, l)
        beam_data = []
        for p1, p2 in beam_lines:
            beam_data.append({
                "begCoordinate": {"x": p1[0], "y": p1[1]},
                "endCoordinate": {"x": p2[0], "y": p2[1]},
                "width": 0.4,
                "height": 0.7,
                "zCoordinate": z,
                "floorIndex": floor["floorIndex"]
            })
        try:
            res = conn.commands.ExecuteAddOnCommand(
                conn.types.AddOnCommandId("TapirCommand", "CreateBeams"),
                {"beamsData": beam_data}
            )
            if res and "elements" in res:
                all_beams.extend([e["elementId"] for e in res["elements"]])
            print(f"Created {len(beam_lines)} beams for {floor['name']}")
        except Exception as e:
            print(f"Error creating beams: {e}")

    # Roof Slab
    all_roof_slabs = []
    all_roof_beams = []
    
    roof_length = floors_info[-1]["length"]
    roof_width = floors_info[-1]["width"]
    coords = [
        Coordinate(0, 0, roof_z),
        Coordinate(roof_width, 0, roof_z),
        Coordinate(roof_width, roof_length, roof_z),
        Coordinate(0, roof_length, roof_z)
    ]
    poly = Polyline(coords)
    try:
        slabs = tapir.CreateSlabs(polylines=poly, level=roof_z)
        if slabs and "elements" in slabs:
            all_roof_slabs.extend([e["elementId"] for e in slabs["elements"]])
        print(f"Created roof slab")
    except Exception as e:
        print(f"Error creating roof slab: {e}")
        
    # Roof Beams
    roof_beam_lines = get_grid_beam_lines(roof_width, roof_length)
    roof_beam_data = []
    for p1, p2 in roof_beam_lines:
        roof_beam_data.append({
            "begCoordinate": {"x": p1[0], "y": p1[1]},
            "endCoordinate": {"x": p2[0], "y": p2[1]},
            "width": 0.4,
            "height": 0.7,
            "zCoordinate": roof_z,
            # Roof is considered part of F4 for floor indexing, or we can omit it if it's derived from Z
            "floorIndex": floors_info[-1]["floorIndex"]
        })
    try:
        res = conn.commands.ExecuteAddOnCommand(
            conn.types.AddOnCommandId("TapirCommand", "CreateBeams"),
            {"beamsData": roof_beam_data}
        )
        if res and "elements" in res:
            all_roof_beams.extend([e["elementId"] for e in res["elements"]])
        print(f"Created {len(roof_beam_lines)} beams for Roof")
    except Exception as e:
        print(f"Error creating roof beams: {e}")
        

        
    # Tag all created elements
    print("Tagging newly created elements...")
    tag_elements(conn, all_slabs + all_roof_slabs, prop_id)
    tag_elements(conn, all_columns, prop_id)
    tag_elements(conn, all_beams + all_roof_beams, prop_id)
        
    print("Done! Check Archicad for the generated tapered structure.")
    
if __name__ == "__main__":
    main()
