import sys
import tkinter as tk
from tkinter import ttk, messagebox
import threading

# Auto-install dependencies if missing
try:
    from archicad import ACConnection
except ModuleNotFoundError:
    import subprocess
    print("Installing archicad package...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "archicad", "--break-system-packages"])
    from archicad import ACConnection

def get_user_layer_mapping(conn):
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
        return None
        
    layer_names = list(layer_dict.keys())
    if not layer_names:
        return None
        
    layer_names.sort()
    
    selections = {}
    categories = ["External Dimensions", "Internal Dimensions"]

    # --- Setup Tkinter UI ---
    root = tk.Tk()
    root.title("Auto Dimension Setup")
    root.geometry("400x200")
    
    # Force window to front
    root.lift()
    root.attributes('-topmost', True)
    root.after(50, lambda: root.attributes('-topmost', False))
    root.focus_force()

    combo_vars = {}
    
    padding = {'padx': 10, 'pady': 5}
    for cat in categories:
        frame = ttk.Frame(root)
        frame.pack(fill='x', **padding)
        ttk.Label(frame, text=f"{cat}:", width=18).pack(side='left')
        var = tk.StringVar()
        # Remove state="readonly" so user can type to search
        combo = ttk.Combobox(frame, textvariable=var, values=layer_names)
        combo.pack(side='right', fill='x', expand=True)
        
        # Capture variables by defaulting kwargs
        def filter_list(event, c=combo, v=var):
            typed = v.get()
            if not typed:
                c['values'] = layer_names
            else:
                c['values'] = [item for item in layer_names if typed.lower() in item.lower()]
                
        combo.bind('<KeyRelease>', filter_list)
        combo.set("") # Start empty so user can just type or click arrow
        combo_vars[cat] = var

    def on_submit():
        for cat in categories:
            name = combo_vars[cat].get()
            selections[cat] = layer_dict[name]
        root.destroy()

    btn_frame = ttk.Frame(root)
    btn_frame.pack(fill='x', pady=15)
    ttk.Button(btn_frame, text="Generate Dimensions", command=on_submit).pack(side='right', padx=10)
    ttk.Button(btn_frame, text="Cancel", command=root.destroy).pack(side='right')

    root.mainloop()

    return selections

def assign_layer(conn, elements, layer_index):
    if not elements or layer_index is None:
        return
    try:
        details = []
        for el in elements:
            if isinstance(el, dict) and "guid" in el:
                details.append({"elementId": el, "details": {"layerIndex": layer_index}})
            elif hasattr(el, "guid"):
                details.append({"elementId": {"guid": str(el.guid)}, "details": {"layerIndex": layer_index}})
                
        conn.commands.ExecuteAddOnCommand(
            conn.types.AddOnCommandId("TapirCommand", "SetDetailsOfElements"),
            {"elementsWithDetails": details}
        )
    except Exception as e:
        print(f"Failed to assign layer: {e}")

def main():
    conn = ACConnection.connect()
    if not conn:
        print("Could not connect to Archicad.")
        return

    # 1. Fetch Selected Elements
    print("Fetching selected elements...")
    sel_res = conn.commands.ExecuteAddOnCommand(
        conn.types.AddOnCommandId("TapirCommand", "GetSelectedElements"), {}
    )
    selected_elements = sel_res.get("elements", [])
    
    if not selected_elements:
        # Check Tkinter
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("No Selection", "Please select Zones, Walls, or other elements to dimension.")
        root.destroy()
        return

    # 2. Extract Types & Details
    element_guids = [el["elementId"] for el in selected_elements]
    
    # Let's get details for all selected elements (this helps identify Zone Labels)
    try:
        details_res = conn.commands.ExecuteAddOnCommand(
            conn.types.AddOnCommandId("TapirCommand", "GetDetailsOfElements"),
            {"elements": selected_elements}
        )
        element_details = details_res.get("detailsOfElements", [])
    except Exception as e:
        print(f"Failed to get details: {e}")
        element_details = []

    # Get bounding boxes for everything as a fallback
    element_guids_objs = [conn.types.ElementId(el["guid"]) for el in element_guids]
    try:
        boxes_res = conn.commands.Get3DBoundingBoxes(element_guids_objs)
    except Exception:
        boxes_res = [None] * len(element_guids)
        
    # Ask for layers
    layers = get_user_layer_mapping(conn)
    if not layers:
        print("Cancelled or failed to get layers.")
        return

    # --- Generate Floor Plan Dimensions ---
    # Filter to only Walls
    wall_guids = []
    valid_boxes = []
    
    for idx, el in enumerate(element_guids):
        guid = str(el["guid"])
        detail = element_details[idx] if idx < len(element_details) else {}
        el_type = detail.get("type", "")
        
        if el_type == "Wall":
            box_err = boxes_res[idx]
            if box_err and hasattr(box_err, 'boundingBox3D'):
                bb = box_err.boundingBox3D
                cx = (bb.xMin + bb.xMax) / 2.0
                cy = (bb.yMin + bb.yMax) / 2.0
                
                # Create horizontal or vertical thickness dim based on aspect ratio
                dx = bb.xMax - bb.xMin
                dy = bb.yMax - bb.yMin
                if dy > dx:
                    direction = {"x": 1.0, "y": 0.0}
                else:
                    direction = {"x": 0.0, "y": 1.0}
                    
                ext_dim_data.append({
                    "wallId": el,
                    "referencePoint": {"x": cx, "y": cy},
                    "direction": direction
                })

    if not ext_dim_data:
        print("No valid walls found in selection to dimension.")
        return

    print(f"Creating wall thickness dimensions for {len(ext_dim_data)} walls...")
    try:
        res = conn.commands.ExecuteAddOnCommand(
            conn.types.AddOnCommandId("TapirCommand", "CreateWallThicknessDimensions"),
            {"dimensionsData": ext_dim_data}
        )
        created = res.get("elements", [])
        assign_layer(conn, [c["elementId"] for c in created], layers.get("External Dimensions"))
    except Exception as e:
        print("Failed to create dimensions:", e)

    print("Dimension generation complete.")

if __name__ == "__main__":
    main()
