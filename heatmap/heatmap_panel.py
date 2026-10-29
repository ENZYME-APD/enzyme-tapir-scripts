#!/usr/bin/env python3
"""
Small floating panel to switch the column heatmap on and off in Archicad.

Put this file next to column_heatmap.py and run:
  python3 heatmap_panel.py

Buttons: Show heatmap / Clear. Optional min/max (mm) to fix the colour range;
leave blank to use the model's own range. The legend updates on each run.
Needs tkinter (included with python.org Python; Homebrew: brew install python-tk).
"""
import tkinter as tk
from tkinter import ttk

import column_heatmap as hm


class Panel(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Column heatmap")
        self.attributes("-topmost", True)  # stay above Archicad
        self.resizable(False, False)
        self.port = None

        f = ttk.Frame(self, padding=10)
        f.grid()

        ttk.Label(f, text="Min mm").grid(row=0, column=0, sticky="w")
        self.vmin = ttk.Entry(f, width=7)
        self.vmin.grid(row=0, column=1, padx=4)
        ttk.Label(f, text="Max mm").grid(row=0, column=2, sticky="w")
        self.vmax = ttk.Entry(f, width=7)
        self.vmax.grid(row=0, column=3, padx=4)
        ttk.Label(f, text="Bins").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.bins = ttk.Spinbox(f, from_=2, to=30, width=5)
        self.bins.set(11)
        self.bins.grid(row=1, column=1, padx=4, pady=(6, 0), sticky="w")

        ttk.Button(f, text="Show heatmap", command=self.show).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=8, padx=(0, 4))
        ttk.Button(f, text="Clear", command=self.clear).grid(
            row=2, column=2, columnspan=2, sticky="ew", pady=8)

        self.legend = tk.Frame(f)
        self.legend.grid(row=3, column=0, columnspan=4, sticky="w")

        self.status = ttk.Label(f, text="Ready", foreground="#666")
        self.status.grid(row=4, column=0, columnspan=4, sticky="w", pady=(6, 0))

    def get_port(self):
        if self.port is None:
            self.port = hm.find_port()
        return self.port

    @staticmethod
    def mm(entry):
        v = entry.get().strip()
        return float(v) / 1000 if v else None

    def show(self):
        try:
            rows, lo, hi, n = hm.apply_heatmap(
                self.get_port(), self.mm(self.vmin), self.mm(self.vmax), int(self.bins.get()))
        except (Exception, SystemExit) as e:
            self.port = None
            self.status.config(text=f"Error: {e}")
            return
        for w in self.legend.winfo_children():
            w.destroy()
        for i, (size, rgb, count) in enumerate(hm.legend(rows, lo, hi, n)):
            tk.Label(self.legend, width=2, bg="#%02x%02x%02x" % tuple(rgb)).grid(row=i, column=0, pady=1)
            tk.Label(self.legend, text=f"{size*1000:5.0f} mm   {count} cols").grid(
                row=i, column=1, sticky="w", padx=6)
        self.status.config(text=f"{len(rows)} columns highlighted")

    def clear(self):
        try:
            hm.clear_highlight(self.get_port())
        except (Exception, SystemExit) as e:
            self.port = None
            self.status.config(text=f"Error: {e}")
            return
        for w in self.legend.winfo_children():
            w.destroy()
        self.status.config(text="Highlight cleared")


if __name__ == "__main__":
    Panel().mainloop()
