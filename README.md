# enzyme-tapir-scripts

Python scripts that automate Archicad through the [Tapir add-on](https://github.com/ENZYME-APD/tapir-archicad-automation).
Archicad must be running with Tapir loaded. Scripts find it on ports 19723–19743.

## Scripts

### heatmap/
Colour elements in Archicad by a property value, using Tapir's highlight.
Standard library only (no `pip install` needed).

| Script | What it does |
|---|---|
| `element_heatmap_panel.py` | Panel: pick elements (selection, or model filtered by type / layer / classification), pick any property, show or clear the heatmap, save a CSV |
| `element_heatmap.py` | Engine and command line for the panel, e.g. `--type Column --property "Column/Width"`, `--list-properties`, `--clear` |
| `column_heatmap.py` | Columns only, coloured by size. `--min 0.4 --max 0.65 --bins 11`, `--csv`, `--clear` |
| `heatmap_panel.py` | Small panel for `column_heatmap.py` |
| `clear_highlight.py` | Turns any highlight and 3D wireframe off |

Numeric properties get a blue → red ramp; text, enum and yes/no properties get one colour per value.
Values are in Archicad base units (m, m², m³, radians).

### structure/
| Script | What it does |
|---|---|
| `columnOptimisation.py` | Column optimisation |
| `tapered.py` | Tapered elements, with a panel |
| `tapered-simple.py` | Tapered elements, no panel |
| `name_grid.py` | Names grid lines (A, B, C … / 1, 2, 3 …) |

### model-setup/
| Script | What it does |
|---|---|
| `setup-layers.py` | Layer setup (opens a page in the browser) |
| `zones-to-walls.py` | Creates walls from zones |

### documentation/
| Script | What it does |
|---|---|
| `auto_dimension.py` | Automatic dimensions, with a panel |

### properties/
| Script | What it does |
|---|---|
| `add_custom_property_ui.py` | Creates a custom property and assigns it to the selected elements |
| `simple_properties.py` | Simple property read/write example |

### examples/
| Script | What it does |
|---|---|
| `create_elements.py` | Creates one of every element type Tapir can create, on a 10 m grid |
| `aclib.py` | Small helper used by `create_elements.py` |

## Setup
Most scripts outside `heatmap/` use the `archicad` package, some also [perisso](https://github.com/runxel/perisso):

```
pip install -r requirements.txt
pip install git+https://github.com/runxel/perisso.git
```

Scripts with a `# /// script` header also run with `uv run <script>.py`, which installs what they need.
Panels use tkinter (python.org Python includes it; Homebrew: `brew install python-tk`).
