# /// script
# dependencies = [
#     "archicad",
#     "perisso @ git+https://github.com/runxel/perisso.git",
# ]
# ///

import os
import sys
from archicad import ACConnection
import http.server
import socketserver
import webbrowser
import urllib.parse
import threading

def assign_layers(conn, elements_guids, layer_index):
    if not elements_guids or layer_index is None:
        return
    try:
        details = []
        for guid in elements_guids:
            details.append({"elementId": {"guid": guid}, "details": {"layerIndex": layer_index}})
                
        res = conn.commands.ExecuteAddOnCommand(
            conn.types.AddOnCommandId("TapirCommand", "SetDetailsOfElements"),
            {"elementsWithDetails": details}
        )
    except Exception as e:
        print(f"Failed to assign layer: {e}")

def main():
    conn = ACConnection.connect()
    if not conn:
        print("Failed to connect to Archicad.")
        return

    print("Fetching selected elements...")
    try:
        sel_res = conn.commands.ExecuteAddOnCommand(
            conn.types.AddOnCommandId("TapirCommand", "GetSelectedElements"),
            {}
        )
        selected_elements = sel_res.get("elements", [])
        if not selected_elements:
            print("No elements selected. Please select some elements in Archicad first.")
            return
    except Exception as e:
        print(f"Failed to get selection: {e}")
        return

    selected_guids = [el["elementId"]["guid"] for el in selected_elements]
    print(f"Found {len(selected_guids)} selected elements.")

    # Get sets of GUIDs for the types we care about
    try:
        slabs = {e.elementId.guid for e in conn.commands.GetElementsByType("Slab")}
        cols = {e.elementId.guid for e in conn.commands.GetElementsByType("Column")}
        beams = {e.elementId.guid for e in conn.commands.GetElementsByType("Beam")}
        roofs = {e.elementId.guid for e in conn.commands.GetElementsByType("Roof")}
    except Exception as e:
        print(f"Failed to get project elements: {e}")
        return

    selected_by_type = {
        "Slabs": [],
        "Columns": [],
        "Beams": [],
        "Roofs": []
    }

    for guid in selected_guids:
        if guid in slabs:
            selected_by_type["Slabs"].append(guid)
        elif guid in cols:
            selected_by_type["Columns"].append(guid)
        elif guid in beams:
            selected_by_type["Beams"].append(guid)
        elif guid in roofs:
            selected_by_type["Roofs"].append(guid)

    categories_to_show = [cat for cat, guids in selected_by_type.items() if guids]

    if not categories_to_show:
        print("Selected elements are not Slabs, Columns, Beams, or Roofs. Exiting.")
        return

    print(f"Selected categories: {categories_to_show}")

    # Fetch layers
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
        return
        
    layer_names = list(layer_dict.keys())
    if not layer_names:
        print("No layers found.")
        return
        
    layer_names.sort()
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Setup Layers for Selection</title>
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
    
    for cat in categories_to_show:
        html_content += f"""
                <div class="form-group">
                    <label>{cat}:</label>
                    <select name="{cat}">
                        {options}
                    </select>
                </div>
        """
        
    html_content += """
                <button type="submit">Assign Layers</button>
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
            
            for cat in categories_to_show:
                if cat in parsed:
                    RequestHandler.selections[cat] = parsed[cat][0]
                    
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"<html><head><style>body{font-family:sans-serif;text-align:center;padding:50px;}</style></head><body><h2>Success! Returning to Archicad...</h2><p>You may now close this tab.</p><script>setTimeout(function(){window.close();}, 1500);</script></body></html>")
            
            # Shutdown the server
            threading.Thread(target=self.server.shutdown).start()
            
        def log_message(self, format, *args):
            pass

    try:
        print("Waiting for user layer selection...")
        with socketserver.TCPServer(("127.0.0.1", 0), RequestHandler) as httpd:
            port = httpd.server_address[1]
            webbrowser.open(f"http://127.0.0.1:{port}")
            httpd.serve_forever()
            
        for cat in categories_to_show:
            if cat in RequestHandler.selections:
                name = RequestHandler.selections[cat]
                layer_index = layer_dict[name]
                print(f"Assigning {cat} to layer {name}...")
                assign_layers(conn, selected_by_type[cat], layer_index)
                
        print("Done!")
                
    except Exception as e:
        print(f"Error during UI selection: {e}")

if __name__ == "__main__":
    main()
