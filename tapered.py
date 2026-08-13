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

def get_user_layer_mapping(conn):
    print("Fetching project layers...")
    try:
        res = conn.commands.ExecuteAddOnCommand(
            conn.types.AddOnCommandId("TapirCommand", "GetAttributesByType"),
            {"attributeType": "Layer"}
        )
        attributes = res.get("attributes", [])
        layer_dict = {}
        for attr in attributes:
            if "name" in attr and "index" in attr:
                name = attr["name"]
                clean_name = "".join(c for c in name if c.isprintable()).strip()
                if clean_name:
                    clean_name = clean_name.replace('"', '')
                    layer_dict[clean_name] = attr["index"]
    except Exception as e:
        print(f"Failed to fetch layers: {e}")
        return {}
        
    layer_names = list(layer_dict.keys())
    if not layer_names:
        return {}
        
    layer_names.sort()
    
    import http.server
    import socketserver
    import webbrowser
    import urllib.parse
    import threading

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Tapered Building Layer Setup</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; padding: 20px; background: #f5f5f5; color: #333; }}
            .container {{ max-width: 400px; margin: 40px auto; background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); }}
            h2 {{ margin-top: 0; margin-bottom: 20px; font-size: 20px; text-align: center; }}
            .form-group {{ margin-bottom: 15px; display: flex; align-items: center; justify-content: space-between; }}
            label {{ font-weight: bold; font-size: 14px; width: 30%; }}
            select {{ width: 65%; padding: 8px; border-radius: 6px; border: 1px solid #ccc; font-size: 14px; background: #fff; }}
            button {{ background: #007aff; color: white; border: none; padding: 12px 20px; border-radius: 8px; cursor: pointer; font-size: 16px; font-weight: bold; width: 100%; margin-top: 20px; transition: background 0.2s; }}
            button:hover {{ background: #0056b3; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>Select Layers</h2>
            <form method="POST" action="/submit">
    """
    
    try:
        folder_structure = conn.commands.GetAttributeFolderStructure('Layer')
        
        options = ""
        def walk_folder(folder, path):
            nonlocal options
            current_path = f"{path} / {folder.name}" if path else folder.name
            
            folder_opts = ""
            if folder.attributes:
                for attr in folder.attributes:
                    name = attr.attribute.name
                    if name in layer_dict:
                        folder_opts += f'\\n                        <option value="{name}">{name}</option>'
            
            if folder_opts:
                label = current_path
                if label == "Root":
                    options += folder_opts
                else:
                    options += f'\\n                    <optgroup label="{label}">{folder_opts}\\n                    </optgroup>'
                    
            if folder.subfolders:
                for sub in folder.subfolders:
                    walk_folder(sub.attributeFolder, current_path if folder.name != "Root" else "")
                    
        walk_folder(folder_structure, "")
        
    except Exception as e:
        print(f"Failed to fetch folder structure, falling back to flat list: {e}")
        options = "".join([f'<option value="{name}">{name}</option>' for name in layer_names])
        
    categories = ["Slabs", "Columns", "Beams", "Roof"]
    
    for cat in categories:
        html_content += f"""
                <div class="form-group">
                    <label>{cat}:</label>
                    <select name="{cat}">
                        {options}
                    </select>
                </div>
        """
        
    html_content += """
                <button type="submit">Generate Geometry</button>
            </form>
        </div>
    </body>
    </html>
    """

    class RequestHandler(http.server.BaseHTTPRequestHandler):
        selections = {}
        
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(html_content.encode('utf-8'))
            
        def do_POST(self):
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length).decode('utf-8')
            parsed = urllib.parse.parse_qs(post_data)
            
            for cat in categories:
                if cat in parsed:
                    RequestHandler.selections[cat] = parsed[cat][0]
                    
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"<html><head><style>body{font-family:sans-serif;text-align:center;padding:50px;}</style></head><body><h2>Success! Returning to Archicad...</h2><p>You may now close this tab.</p><script>setTimeout(function(){window.close();}, 1500);</script></body></html>")
            
            # Shutdown the server
            threading.Thread(target=self.server.shutdown).start()
            
        def log_message(self, format, *args):
            pass # Suppress HTTP logs in terminal

    try:
        print("Waiting for user layer selection...")
        with socketserver.TCPServer(("127.0.0.1", 0), RequestHandler) as httpd:
            port = httpd.server_address[1]
            # Open the UI in the default web browser
            webbrowser.open(f"http://127.0.0.1:{port}")
            httpd.serve_forever()
            
        selections = {}
        for cat in categories:
            if cat in RequestHandler.selections:
                name = RequestHandler.selections[cat]
                selections[cat] = layer_dict[name]
                print(f"Mapped {cat} to layer {name}")
                
        return selections
    except Exception as e:
        print(f"Error during UI selection: {e}")
        return {}

def assign_layers(conn, elements, layer_index):
    if not elements or layer_index is None:
        return
    try:
        details = []
        for el in elements:
            if isinstance(el, dict) and "guid" in el:
                details.append({"elementId": el, "details": {"layerIndex": layer_index}})
            elif hasattr(el, "guid"):
                details.append({"elementId": {"guid": str(el.guid)}, "details": {"layerIndex": layer_index}})
                
        res = conn.commands.ExecuteAddOnCommand(
            conn.types.AddOnCommandId("TapirCommand", "SetDetailsOfElements"),
            {"elementsWithDetails": details}
        )
    except Exception as e:
        print(f"Failed to assign layer: {e}")

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
        
    selected_layers = get_user_layer_mapping(conn)

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
        
    if selected_layers:
        print("Assigning selected layers to elements...")
        assign_layers(conn, all_slabs, selected_layers.get("Slabs"))
        assign_layers(conn, all_columns, selected_layers.get("Columns"))
        assign_layers(conn, all_beams, selected_layers.get("Beams"))
        assign_layers(conn, all_roof_slabs, selected_layers.get("Roof"))
        assign_layers(conn, all_roof_beams, selected_layers.get("Roof"))
        
    # Tag all created elements
    print("Tagging newly created elements...")
    tag_elements(conn, all_slabs + all_roof_slabs, prop_id)
    tag_elements(conn, all_columns, prop_id)
    tag_elements(conn, all_beams + all_roof_beams, prop_id)
        
    print("Done! Check Archicad for the generated tapered structure.")
    
if __name__ == "__main__":
    main()
