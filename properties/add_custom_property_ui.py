"""
Tapir Add Custom Property UI Script

This script provides a graphical interface (using Tkinter) to dynamically create 
and assign new string properties to selected elements in Archicad. 

Workflow:
1. Connect to Archicad via the Python API wrapper.
2. If elements are selected, it queries existing Property Groups.
3. It launches a UI allowing the user to select an existing group or create a new one.
4. Upon submission, it creates the group (if needed), creates the property definition,
   binds it to the classifications of the selected elements, and applies the value.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import sys

# Auto-install the archicad package if missing (useful when running inside Archicad Tapir palette)
try:
    from archicad import ACConnection
except ModuleNotFoundError:
    import subprocess
    try:
        print("Installing 'archicad' module...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "archicad", "--break-system-packages"])
        from archicad import ACConnection
    except Exception as e:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Missing Module", f"The 'archicad' module is required but could not be installed automatically.\n\nError: {e}")
        sys.exit(1)

class CustomPropertyUI:
    """
    Main UI application class for the Custom Property dialog.
    It manages the data fetching from Archicad and handles the UI lifecycle.
    """
    def __init__(self, root, conn):
        self.root = root
        self.conn = conn
        self.root.title("Add Custom Property")
        self.root.geometry("400x300")
        
        # Internal state to hold groups and selected elements
        self.groups = []
        self.selected_elements = []
        
        # Only proceed to setup UI if data fetching was successful
        if self.fetch_data():
            self.setup_ui()

    def fetch_data(self):
        """
        Fetches the initially required data from Archicad:
        - The currently selected elements
        - All existing Property Groups in the project
        Returns True if successful, False if it should abort.
        """
        try:
            # 1. Fetch Selected Elements using TapirCommand.GetSelectedElements
            self.selected_elements = self.conn.commands.ExecuteAddOnCommand(
                self.conn.types.AddOnCommandId("TapirCommand", "GetSelectedElements"), {}
            ).get("elements", [])
            
            if not self.selected_elements:
                messagebox.showerror("Error", "No elements selected in Archicad.")
                self.root.destroy()
                return False

            # 2. Fetch Property Groups using native Archicad JSON API
            group_ids = self.conn.commands.GetAllPropertyGroupIds()
            if group_ids:
                group_details = self.conn.commands.GetPropertyGroups(group_ids)
                # Store the names for the UI dropdown
                self.groups = [g.propertyGroup.name for g in group_details]
            return True
        except Exception as e:
            messagebox.showerror("API Error", str(e))
            self.root.destroy()
            return False

    def setup_ui(self):
        padding = {'padx': 10, 'pady': 5}
        
        # Group
        ttk.Label(self.root, text="Property Group:").pack(anchor='w', **padding)
        self.group_var = tk.StringVar()
        self.group_combo = ttk.Combobox(self.root, textvariable=self.group_var, values=self.groups)
        self.group_combo.pack(fill='x', **padding)
        if self.groups:
            self.group_combo.set(self.groups[0])
            
        # Property Name
        ttk.Label(self.root, text="New Property Name:").pack(anchor='w', **padding)
        self.prop_name_var = tk.StringVar()
        ttk.Entry(self.root, textvariable=self.prop_name_var).pack(fill='x', **padding)
        
        # Property Value
        ttk.Label(self.root, text="Property Value (String):").pack(anchor='w', **padding)
        self.prop_val_var = tk.StringVar()
        ttk.Entry(self.root, textvariable=self.prop_val_var).pack(fill='x', **padding)
        
        # Buttons
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill='x', pady=15)
        
        ttk.Button(btn_frame, text="Submit", command=self.on_submit).pack(side='right', padx=10)
        ttk.Button(btn_frame, text="Cancel", command=self.root.destroy).pack(side='right')

    def on_submit(self):
        group_name = self.group_var.get().strip()
        prop_name = self.prop_name_var.get().strip()
        prop_value = self.prop_val_var.get().strip()
        
        if not group_name or not prop_name:
            messagebox.showwarning("Warning", "Property Group and Name are required.")
            return
            
        try:
            self.execute_assignment(group_name, prop_name, prop_value)
            messagebox.showinfo("Success", f"Successfully assigned '{prop_name}' to {len(self.selected_elements)} elements.")
            self.root.destroy()
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {e}")

    def execute_assignment(self, group_name, prop_name, prop_value):
        """
        Executes the Archicad operations to create the property and assign it.
        """
        # --- Step 1: Create the Property Group (if it doesn't already exist) ---
        if group_name not in self.groups:
            self.conn.commands.ExecuteAddOnCommand(
                self.conn.types.AddOnCommandId("TapirCommand", "CreatePropertyGroups"),
                {"propertyGroups": [{"propertyGroup": {"name": group_name}}]}
            )
            
        # --- Step 2: Fetch Classifications for the selected elements ---
        # A property must be 'available' to classifications to be assigned to elements.
        # First, we fetch all Classification Systems available in the project
        sys_ids = self.conn.commands.GetAllClassificationSystems()
        sys_id_wrappers = [{"classificationSystemId": s.classificationSystemId} for s in sys_ids]
        
        # Next, query which classifications from these systems apply to our selected elements
        classifications = self.conn.commands.GetClassificationsOfElements(self.selected_elements, sys_id_wrappers)
        
        # Extract the unique classification item GUIDs so we can bind our property to them
        class_ids = set()
        for item in classifications:
            # 'item' contains the classifications for a single element
            if hasattr(item, 'classificationIds') and item.classificationIds:
                for sys_cls in item.classificationIds:
                    class_ids.add(sys_cls.classificationId.classificationItemId.guid)
                    
        # Structure the availability list required by the CreatePropertyDefinitions payload
        availability = [{"classificationItemId": {"guid": str(c)}} for c in class_ids]
        
        # --- Step 3: Create the Custom Property Definition ---
        prop_def = {
            "name": prop_name,
            "description": "Created via Tapir UI",
            "type": "string",
            "isEditable": True,
            "defaultValue": {
                "basicDefaultValue": {
                    "type": "string",
                    "status": "normal",
                    "value": "Default"
                }
            },
            "availability": availability,
            "group": {"name": group_name}
        }
        
        self.conn.commands.ExecuteAddOnCommand(
            self.conn.types.AddOnCommandId("TapirCommand", "CreatePropertyDefinitions"),
            {"propertyDefinitions": [{"propertyDefinition": prop_def}]}
        )
        
        # --- Step 4: Fetch the GUID of the newly created property ---
        # The Tapir creation command doesn't return the ID, so we query it via the native API
        prop_id = self.conn.commands.GetPropertyIds([
            {"type": "UserDefined", "localizedName": [group_name, prop_name]}
        ])[0].propertyId
        
        # --- Step 5: Assign the Property Value to the Selected Elements ---
        element_prop_values = []
        for el in self.selected_elements:
            element_prop_values.append({
                "elementId": el["elementId"],
                "propertyId": prop_id,
                "propertyValue": {
                    "type": "string",
                    "status": "normal",
                    "value": prop_value
                }
            })
            
        # Push the values to Archicad
        self.conn.commands.SetPropertyValuesOfElements(element_prop_values)
        
if __name__ == "__main__":
    try:
        conn = ACConnection.connect()
    except Exception as e:
        print(f"Failed to connect to Archicad: {e}")
        sys.exit(1)
        
    root = tk.Tk()
    
    # Force window to front
    root.lift()
    root.attributes('-topmost', True)
    root.after(50, lambda: root.attributes('-topmost', False))
    root.focus_force()
    
    app = CustomPropertyUI(root, conn)
    root.mainloop()
