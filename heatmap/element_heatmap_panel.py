#!/usr/bin/env python3
"""
Floating panel for element_heatmap.py.

  python3 element_heatmap_panel.py

Step 1  Elements: whole model or current selection, optionally filtered by
        type, layer and classification. Nothing picked in a list means all
        of it; "Clear" above a list resets it. The three lists are linked: picking
        in one narrows the others to what exists, with element counts.
        Search box above each list; Cmd-click to pick several.
        Press "Find elements".
Step 2  Property: the list fills with the properties of those elements.
        Search, then click one.
Step 3  Colours: pick a style, optional Min/Max/Bins, then "Show heatmap".
        "Legend window" opens a separate, resizable legend that follows
        every new heatmap.

The model is indexed once when the panel opens (type, layer, classification
of every element). Press "Reload lists" after changing the model.

Errors are shown in a dialog and printed in the Terminal.
Needs tkinter (python.org Python includes it; Homebrew: brew install python-tk).
"""
__version__ = "2.1.2"

import os
import traceback
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, colorchooser

import element_heatmap as hm


def hexcol(rgb):
    return "#%02x%02x%02x" % tuple(rgb[:3])


class SearchList(ttk.Frame):
    """Listbox with a search box. Keeps the selection while filtering."""

    def __init__(self, parent, title, multi=True, height=8, width=24, on_change=None):
        super().__init__(parent)
        self.items = []        # [(key, label)]
        self.shown = []        # keys currently visible
        self.chosen = set()    # selected keys
        self.multi = multi
        self.on_change = on_change
        self._updating = False

        head = ttk.Frame(self)
        head.pack(fill="x")
        self.title_lbl = ttk.Label(head, text=title)
        self.title_lbl.pack(side="left")
        self.clear_btn = ttk.Button(head, text="Clear", width=5, command=self.clear_and_notify)
        if multi:
            self.clear_btn.pack(side="right")
        self.count = ttk.Label(head, text="", foreground="#888")
        self.count.pack(side="right", padx=(0, 6))

        self.q = tk.StringVar()
        self.q.trace_add("write", lambda *_: self.render())
        ttk.Entry(self, textvariable=self.q).pack(fill="x", pady=(2, 2))

        box = ttk.Frame(self)
        box.pack(fill="both", expand=True)
        self.lb = tk.Listbox(box, selectmode="extended" if multi else "browse",
                             exportselection=False, height=height, width=width)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.lb.yview)
        self.lb.configure(yscrollcommand=sb.set)
        self.lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.lb.bind("<<ListboxSelect>>", self._picked)

    def set_items(self, items, keep_chosen=False):
        """items: [(key, label)]. keep_chosen keeps picks that are no longer listed."""
        self.items = list(items)
        if not keep_chosen:
            self.chosen &= {k for k, _ in items}
        self.render()

    def render(self):
        q = self.q.get().strip().lower()
        top = self.lb.yview()[0] if self.lb.size() else 0
        self._updating = True
        self.lb.delete(0, "end")
        self.shown = []
        for k, label in self.items:
            if not q or q in label.lower():
                self.shown.append(k)
                self.lb.insert("end", label)
                if k in self.chosen:
                    self.lb.selection_set("end")
        self.lb.yview_moveto(top)
        self._updating = False
        self._count()

    def _picked(self, _):
        if self._updating:
            return
        visible = set(self.shown)
        now = {self.shown[i] for i in self.lb.curselection()}
        if self.multi:
            self.chosen = (self.chosen - visible) | now
        else:
            self.chosen = now
        self._count()
        if self.on_change:
            self.on_change(self)

    def _count(self):
        n = len(self.chosen)
        if not self.multi:
            self.count.config(text=f"{len(self.items)}")
        elif n:
            self.count.config(text=f"{n} selected", foreground="#2a7")
        else:
            self.count.config(text=f"All ({len(self.items)})", foreground="#888")
        self.clear_btn.state(["!disabled"] if n else ["disabled"])

    def clear(self):
        self.chosen.clear()
        self.render()

    def clear_and_notify(self):
        self.clear()
        if self.on_change:
            self.on_change(self)

    def selected(self):
        return [k for k in self.chosen]


class LegendWindow(tk.Toplevel):
    """Separate, resizable legend that the panel refreshes after every heatmap."""

    def __init__(self, master):
        super().__init__(master)
        self.title("Heatmap legend")
        self.attributes("-topmost", True)
        self.geometry("360x520")
        self.minsize(260, 200)
        self.data = None

        self.head = ttk.Label(self, text="No heatmap yet", font=("TkDefaultFont", 13, "bold"),
                              padding=(10, 8, 10, 0), wraplength=330)
        self.head.pack(fill="x")
        self.sub = ttk.Label(self, text="", foreground="#888", padding=(10, 0, 10, 6))
        self.sub.pack(fill="x")

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=10)
        self.canvas = tk.Canvas(body, highlightthickness=0)
        sb = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.rows = ttk.Frame(self.canvas)
        self.rows.bind("<Configure>",
                       lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.win = self.canvas.create_window((0, 0), window=self.rows, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.win, width=e.width))
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.rows.columnconfigure(1, weight=1)

        bar = ttk.Frame(self, padding=10)
        bar.pack(fill="x")
        ttk.Button(bar, text="Copy as text", command=self.copy).pack(side="left")
        self.note = ttk.Label(bar, text="", foreground="#888")
        self.note.pack(side="left", padx=8)
        self.bind("<Configure>", lambda e: self.head.config(wraplength=max(200, self.winfo_width() - 30)))

    def update_legend(self, title, subtitle, legend):
        self.data = (title, subtitle, legend)
        self.head.config(text=title)
        self.sub.config(text=subtitle)
        for w in self.rows.winfo_children():
            w.destroy()
        for i, (label, rgb, count) in enumerate(legend):
            tk.Label(self.rows, width=3, bg=hexcol(rgb)).grid(row=i, column=0, pady=2, sticky="w")
            ttk.Label(self.rows, text=label).grid(row=i, column=1, sticky="w", padx=8)
            ttk.Label(self.rows, text=str(count), foreground="#888").grid(row=i, column=2, sticky="e")
        self.note.config(text="")

    def copy(self):
        if not self.data:
            return
        title, subtitle, legend = self.data
        lines = [title, subtitle, ""] + [f"{label}\t{count}\t{hexcol(rgb)}" for label, rgb, count in legend]
        self.clipboard_clear()
        self.clipboard_append("\n".join(lines))
        self.note.config(text="Copied")


class Panel(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Element heatmap v{__version__}")
        self.attributes("-topmost", True)
        self.port = None
        self.index = {}        # guid -> {"type", "layer", "classes", "all_classes"}
        self.layer_names = {}  # layer index -> name
        self.class_tree = []   # [(guid, label, depth, descendants, system)]
        self.selection = None  # guids of the Archicad selection, when used
        self.guids = []
        self.props = {}        # guid -> (label, type)
        self.last = None
        self.legend_data = None
        self.legend_win = None
        self.stale = True

        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)

        # ---------------- step 1
        s1 = ttk.LabelFrame(root, text="1  Elements", padding=8)
        s1.grid(row=0, column=0, sticky="nsew")
        root.rowconfigure(0, weight=2)
        top = ttk.Frame(s1)
        top.grid(row=0, column=0, columnspan=3, sticky="ew")
        self.use_sel = tk.BooleanVar(value=False)
        ttk.Radiobutton(top, text="Whole model", variable=self.use_sel, value=False,
                        command=self.source_changed).pack(side="left")
        ttk.Radiobutton(top, text="Current selection", variable=self.use_sel, value=True,
                        command=self.source_changed).pack(side="left", padx=10)
        ttk.Button(top, text="Reload lists", command=self.load_lists).pack(side="right")

        self.type_l = SearchList(s1, "Type", on_change=self.filters_changed)
        self.layer_l = SearchList(s1, "Layer", on_change=self.filters_changed)
        self.class_l = SearchList(s1, "Classification", width=30, on_change=self.filters_changed)
        for c, w in enumerate((self.type_l, self.layer_l, self.class_l)):
            w.grid(row=1, column=c, sticky="nsew", padx=(0, 8), pady=(6, 0))
            s1.columnconfigure(c, weight=1)
        s1.rowconfigure(1, weight=1)

        bar = ttk.Frame(s1)
        bar.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        ttk.Button(bar, text="Find elements", command=self.find).pack(side="left")
        ttk.Button(bar, text="Clear filters", command=self.clear_filters).pack(side="left", padx=6)
        self.found_lbl = ttk.Label(bar, text="Nothing picked in a list = all of it. Lists are linked; numbers are counts.",
                                   foreground="#888")
        self.found_lbl.pack(side="left", padx=6)

        # ---------------- step 2
        s2 = ttk.LabelFrame(root, text="2  Property", padding=8)
        s2.grid(row=1, column=0, sticky="nsew", pady=8)
        root.rowconfigure(1, weight=2)
        self.prop_l = SearchList(s2, "Find elements first", multi=False, height=7, width=60,
                                 on_change=self.prop_picked)
        self.prop_l.pack(fill="both", expand=True)

        # ---------------- step 3
        s3 = ttk.LabelFrame(root, text="3  Colours", padding=8)
        s3.grid(row=2, column=0, sticky="ew")
        r1 = ttk.Frame(s3)
        r1.pack(fill="x")
        self.num_lbl = ttk.Label(r1, text="Number scale", width=15)
        self.num_lbl.pack(side="left")
        self.ramp = ttk.Combobox(r1, state="readonly", width=11, values=list(hm.RAMPS))
        self.ramp.set("Blue-Red")
        self.ramp.pack(side="left", padx=(4, 8))
        self.preview = tk.Canvas(r1, width=120, height=14, highlightthickness=0)
        self.preview.pack(side="left")
        self.rev = tk.BooleanVar(value=False)
        ttk.Checkbutton(r1, text="Reverse", variable=self.rev).pack(side="left", padx=(12, 0))
        self.applies = ttk.Label(r1, text="", foreground="#888")
        self.applies.pack(side="left", padx=10)

        r1b = ttk.Frame(s3)
        r1b.pack(fill="x", pady=(4, 0))
        self.cat_lbl = ttk.Label(r1b, text="Category colours", width=15)
        self.cat_lbl.pack(side="left")
        self.cat = ttk.Combobox(r1b, state="readonly", width=11, values=list(hm.CATEGORICALS))
        self.cat.set("Bold")
        self.cat.pack(side="left", padx=(4, 8))
        self.cat_preview = tk.Canvas(r1b, width=120, height=14, highlightthickness=0)
        self.cat_preview.pack(side="left")
        ttk.Label(r1b, text="(text, list and yes/no properties)", foreground="#888").pack(side="left", padx=10)

        for w in (self.ramp, self.cat):
            w.bind("<<ComboboxSelected>>", lambda e: self.draw_preview())
        self.rev.trace_add("write", lambda *_: self.draw_preview())

        r1c = ttk.Frame(s3)
        r1c.pack(fill="x", pady=(4, 0))
        ttk.Label(r1c, text="Other elements", width=15).pack(side="left")
        self.other_hex = "#c8c8c8"
        self.other_btn = tk.Button(r1c, width=3, bg=self.other_hex, activebackground=self.other_hex,
                                   relief="ridge", command=self.pick_other)
        self.other_btn.pack(side="left", padx=(4, 8))
        ttk.Label(r1c, text="Opacity %").pack(side="left")
        self.other_op = ttk.Spinbox(r1c, from_=0, to=100, increment=5, width=4,
                                    command=self.reapply)
        self.other_op.set(24)
        self.other_op.bind("<Return>", lambda e: self.reapply())
        self.other_op.pack(side="left", padx=(2, 10))
        self.wire = tk.BooleanVar(value=True)
        ttk.Checkbutton(r1c, text="Wireframe in 3D", variable=self.wire,
                        command=self.reapply).pack(side="left")

        r2 = ttk.Frame(s3)
        r2.pack(fill="x", pady=(6, 0))
        ttk.Label(r2, text="Min").pack(side="left")
        self.vmin = ttk.Entry(r2, width=8)
        self.vmin.pack(side="left", padx=(2, 8))
        ttk.Label(r2, text="Max").pack(side="left")
        self.vmax = ttk.Entry(r2, width=8)
        self.vmax.pack(side="left", padx=(2, 8))
        ttk.Label(r2, text="Bins").pack(side="left")
        self.bins = ttk.Spinbox(r2, from_=2, to=30, width=4)
        self.bins.set(11)
        self.bins.pack(side="left", padx=2)
        ttk.Label(r2, text="(numbers only; m, m², m³, rad; blank = data range)",
                  foreground="#888").pack(side="left", padx=8)

        r3 = ttk.Frame(s3)
        r3.pack(fill="x", pady=(8, 0))
        ttk.Button(r3, text="Show heatmap", command=self.show).pack(side="left")
        ttk.Button(r3, text="Clear", command=self.clear).pack(side="left", padx=6)
        ttk.Button(r3, text="Save CSV…", command=self.save_csv).pack(side="left")

        # ---------------- legend
        lf = ttk.LabelFrame(root, text="Legend", padding=8)
        lf.grid(row=3, column=0, sticky="nsew", pady=(8, 0))
        root.rowconfigure(3, weight=1)
        lbar = ttk.Frame(lf)
        lbar.pack(fill="x")
        ttk.Button(lbar, text="Legend window", command=self.open_legend).pack(side="right")
        self.legend_head = ttk.Label(lbar, text="", foreground="#888")
        self.legend_head.pack(side="left")
        body = ttk.Frame(lf)
        body.pack(fill="both", expand=True, pady=(4, 0))
        self.canvas = tk.Canvas(body, height=110, highlightthickness=0)
        sb = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.legend = ttk.Frame(self.canvas)
        self.legend.bind("<Configure>",
                         lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.legend, anchor="nw")
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.status = ttk.Label(root, text="", foreground="#888")
        self.status.grid(row=4, column=0, sticky="w", pady=(6, 0))

        self.draw_preview()
        self.update_idletasks()
        self.minsize(self.winfo_reqwidth(), self.winfo_reqheight())
        self.after(100, self.load_lists)

    # ---------------------------------------------------------------- helpers
    def say(self, text):
        self.status.config(text=text)
        self.update_idletasks()

    def get_port(self):
        if self.port is None:
            self.port = hm.find_port()
        return self.port

    def guarded(self, fn, what):
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            return fn()
        except Exception as e:
            traceback.print_exc()
            self.port = None
            self.say(f"{what} failed")
            messagebox.showerror("Element heatmap", f"{what} failed:\n\n{e}", parent=self)
        finally:
            self.config(cursor="")

    @staticmethod
    def num(entry):
        v = entry.get().strip().replace(",", ".")
        return float(v) if v else None

    def draw_preview(self):
        c = self.preview
        c.delete("all")
        rp = list(hm.RAMPS[self.ramp.get()])
        if self.rev.get():
            rp.reverse()
        for i in range(24):
            c.create_rectangle(i * 5, 0, i * 5 + 5, 14, width=0,
                               fill=hexcol(hm.lerp_ramp(i / 23, rp)))
        c = self.cat_preview
        c.delete("all")
        cp = list(hm.CATEGORICALS[self.cat.get()])
        if self.rev.get():
            cp.reverse()
        for i, rgb in enumerate(cp[:12]):
            c.create_rectangle(i * 10, 0, i * 10 + 9, 14, width=0, fill=hexcol(rgb))

    def other_rgba(self):
        try:
            op = float(self.other_op.get())
        except ValueError:
            op = 24
        return hm.hex_to_rgba(self.other_hex, op)

    def pick_other(self):
        rgb, hx = colorchooser.askcolor(color=self.other_hex, title="Colour of other elements",
                                        parent=self)
        if hx:
            self.other_hex = hx
            self.other_btn.config(bg=hx, activebackground=hx)
            self.reapply()

    def reapply(self):
        """Re-send the current heatmap with the new other-elements settings."""
        if not self.last:
            return
        def work():
            hm.highlight(self.get_port(), self.last[1], self.other_rgba(), self.wire.get())
            self.say("Other elements updated")
        self.guarded(work, "Updating colours")

    def set_applies(self, ptype):
        """Grey out the colour row that does not apply to the picked property."""
        if not ptype:
            num, cat = True, True
        else:
            num = ptype in hm.NUMERIC_TYPES
            cat = not num
        self.ramp.state(["!disabled", "readonly"] if num else ["disabled"])
        self.cat.state(["!disabled", "readonly"] if cat else ["disabled"])
        for w in (self.vmin, self.vmax, self.bins):
            w.state(["!disabled"] if num else ["disabled"])
        self.num_lbl.config(foreground="" if num else "#999")
        self.cat_lbl.config(foreground="" if cat else "#999")
        self.applies.config(text="" if not ptype else
                            ("→ uses Number scale" if num else "→ uses Category colours"))

    # ------------------------------------------------------------ linked lists
    def base(self):
        """Elements the filters work on: whole model or the Archicad selection."""
        if self.use_sel.get() and self.selection is not None:
            return self.selection
        return list(self.index)

    def picks(self):
        classes = set(self.class_l.selected())
        return set(self.type_l.selected()), set(self.layer_l.selected()), classes

    def refresh_facets(self, source=None):
        """Re-list each filter with only the options that exist, given the others."""
        types, layers, classes = self.picks()
        base = self.base()
        recs = [self.index[g] for g in base if g in self.index]

        def ok(r, t=True, l=True, c=True):
            if t and types and r["type"] not in types:
                return False
            if l and layers and r["layer"] not in layers:
                return False
            if c and classes and not (r["all_classes"] & classes):
                return False
            return True

        if source is not self.type_l:
            counts = {}
            for r in recs:
                if ok(r, t=False):
                    counts[r["type"]] = counts.get(r["type"], 0) + 1
            keys = sorted(set(counts) | types)
            self.type_l.set_items([(k, f"{k}  ({counts.get(k, 0)})") for k in keys], keep_chosen=True)

        if source is not self.layer_l:
            counts = {}
            for r in recs:
                if ok(r, l=False):
                    counts[r["layer"]] = counts.get(r["layer"], 0) + 1
            keys = sorted(set(counts) | layers,
                          key=lambda i: self.layer_names.get(i, f"Layer {i}").lower())
            self.layer_l.set_items([(k, f"{self.layer_names.get(k, f'Layer {k}')}  ({counts.get(k, 0)})")
                                    for k in keys], keep_chosen=True)

        if source is not self.class_l:
            counts = {}
            for r in recs:
                if ok(r, c=False):
                    for g in r["all_classes"]:
                        counts[g] = counts.get(g, 0) + 1
            items = []
            for g, label, depth, _, system in self.class_tree:
                if g and (counts.get(g) or g in classes):
                    sys_note = f"   [{system}]" if depth == 0 else ""
                    items.append((g, f"{'  ' * depth}{label}  ({counts.get(g, 0)}){sys_note}"))
            self.class_l.set_items(items, keep_chosen=True)

        n = sum(1 for r in recs if ok(r))
        return n

    def filters_changed(self, source=None):
        n = self.refresh_facets(source)
        self.stale = True
        self.found_lbl.config(text=f"{n} elements match — press Find elements",
                              foreground="#c60" if self.guids else "#888")

    def source_changed(self):
        if self.use_sel.get():
            def work():
                p = self.get_port()
                sel = [e["elementId"]["guid"] for e in hm.call_any(p, "GetSelectedElements")["elements"]]
                missing = [g for g in sel if g not in self.index]
                if missing:
                    extra = hm.build_index(p, missing)
                    hm.expand_classes(extra, self.class_tree)
                    self.index.update(extra)
                self.selection = sorted(set(sel))
                self.say(f"{len(self.selection)} elements selected in Archicad")
            self.guarded(work, "Reading the selection")
        else:
            self.selection = None
        self.filters_changed()

    # ---------------------------------------------------------------- actions
    def load_lists(self):
        def work():
            p = self.get_port()
            self.say("Reading layers…")
            self.layer_names = {idx: name for idx, name in hm.list_layers(p)}
            self.say("Reading classifications…")
            self.class_tree = hm.list_classifications(p)
            self.say("Indexing elements…")
            self.index = hm.build_index(p, progress=self.say)
            hm.expand_classes(self.index, self.class_tree)
            if self.use_sel.get():
                self.source_changed()
            n = self.refresh_facets()
            self.found_lbl.config(text=f"{n} elements in the model. Lists are linked; numbers are counts.",
                                  foreground="#888")
            self.say(f"Connected on port {p}. Step 1: set filters and press Find elements.")
        self.guarded(work, "Reading the model")

    def clear_filters(self):
        for l in (self.type_l, self.layer_l, self.class_l):
            l.q.set("")
            l.clear()
        self.filters_changed()

    def find(self):
        def work():
            if self.use_sel.get():
                self.source_changed()
            types, layers, classes = self.picks()
            self.guids = sorted(hm.match(self.index, self.base(), types, layers, classes))
            self.stale = False
            if not self.guids:
                self.found_lbl.config(text="No elements match", foreground="#c00")
                self.prop_l.set_items([])
                self.say("No elements match the filters.")
                return
            self.found_lbl.config(text=f"{len(self.guids)} elements found", foreground="#2a2")
            self.say("Reading their properties…")
            props = hm.list_properties(self.get_port(), self.guids)
            self.props = {g: (label, typ) for g, label, typ in props}
            self.prop_l.set_items([(g, f"{label}   [{typ}]") for g, label, typ in props])
            self.prop_l.title_lbl.config(text="Search properties")
            self.say("Step 2: pick a property.")
        self.guarded(work, "Finding elements")

    def prop_picked(self, _=None):
        sel = self.prop_l.selected()
        if sel:
            label, ptype = self.props[sel[0]]
            self.set_applies(ptype)
            self.say(f"Step 3: {label} → Show heatmap")
        else:
            self.set_applies(None)

    def show(self):
        def work():
            if self.stale or not self.guids:
                self.find()
                if not self.guids:
                    return
            sel = self.prop_l.selected()
            if not sel:
                self.say("Pick a property in step 2 first.")
                return
            pg = sel[0]
            label = self.props[pg][0]
            self.say("Reading values and colouring…")
            values, colours, legend, mode = hm.run(
                self.get_port(), self.guids, pg,
                self.num(self.vmin), self.num(self.vmax), int(self.bins.get()),
                self.ramp.get(), self.cat.get(), self.rev.get(),
                self.other_rgba(), self.wire.get())
            self.last = (values, colours, label)
            style = self.ramp.get() if mode == "numeric" else self.cat.get()
            sub = f"{len(colours)} elements · {style}{' reversed' if self.rev.get() else ''}"
            self.legend_data = (label, sub, legend)
            self.draw_legend()
            self.say(f"{len(colours)} elements coloured by {label} ({mode})")
        self.guarded(work, "Showing the heatmap")

    def draw_legend(self):
        for w in self.legend.winfo_children():
            w.destroy()
        if not self.legend_data:
            self.legend_head.config(text="")
            return
        label, sub, legend = self.legend_data
        self.legend_head.config(text=f"{label} — {sub}")
        for i, (text, rgb, count) in enumerate(legend):
            tk.Label(self.legend, width=2, bg=hexcol(rgb)).grid(row=i, column=0, pady=1)
            ttk.Label(self.legend, text=text).grid(row=i, column=1, sticky="w", padx=6)
            ttk.Label(self.legend, text=str(count), foreground="#888").grid(row=i, column=2, sticky="e")
        if self.legend_win is not None and self.legend_win.winfo_exists():
            self.legend_win.update_legend(*self.legend_data)

    def open_legend(self):
        if self.legend_win is None or not self.legend_win.winfo_exists():
            self.legend_win = LegendWindow(self)
        else:
            self.legend_win.lift()
        if self.legend_data:
            self.legend_win.update_legend(*self.legend_data)

    def clear(self):
        def work():
            hm.clear_highlight(self.get_port())
            self.legend_data = None
            self.draw_legend()
            if self.legend_win is not None and self.legend_win.winfo_exists():
                self.legend_win.update_legend("No heatmap", "", [])
            self.say("Highlight cleared")
        self.guarded(work, "Clearing")

    def save_csv(self):
        if not self.last:
            self.say("Show a heatmap first.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv",
                                            filetypes=[("CSV", "*.csv")], parent=self)
        if path:
            values, colours, label = self.last
            hm.write_csv(path, values, colours, label)
            self.say(f"Saved {path}")


if __name__ == "__main__":
    print(f"Element heatmap panel v{__version__}  ({os.path.abspath(__file__)})")
    print(f"Engine v{getattr(hm, '__version__', '?')}  ({os.path.abspath(hm.__file__)})")
    if getattr(hm, "__version__", None) != __version__:
        print("WARNING: panel and engine versions differ - an old element_heatmap.py is being imported.")
    Panel().mainloop()
