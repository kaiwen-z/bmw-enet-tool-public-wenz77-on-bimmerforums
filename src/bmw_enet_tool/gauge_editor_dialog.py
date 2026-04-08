"""Add-gauge dialog: sensor picker + gauge-kind selector."""
import tkinter as tk

from .sensors import get_sensors
from .ui_theme import (
    ACCENT,
    ACCENT_ACTIVE,
    BG,
    BTN_ACTIVE_BG,
    BTN_BG,
    DIM,
    ENTRY_BG,
    LABEL_C,
    TEXT,
    WHITE,
)


class GaugeEditorDialog(tk.Toplevel):
    """Modal dialog for adding a gauge to the canvas."""

    def __init__(self, master, placed_ids=None):
        super().__init__(master)
        self.title("Add Gauge")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.result = None  # (sensor_id, kind) on OK
        self._placed = placed_ids or set()

        self.transient(master)
        self.grab_set()

        w, h = 320, 400
        px = master.winfo_rootx() + (master.winfo_width() - w) // 2
        py = master.winfo_rooty() + (master.winfo_height() - h) // 2
        self.geometry(f"{w}x{h}+{px}+{py}")

        sensors = get_sensors()
        self._available = [
            (s["sensor_id"], s["label"])
            for s in sensors
            if s["sensor_id"] not in self._placed
        ]

        if not self._available:
            tk.Label(self, text="All sensors are already placed.",
                     bg=BG, fg=DIM, font=("Segoe UI", 10)).pack(pady=30)
            tk.Button(self, text="OK", bg=BTN_BG, fg=TEXT,
                      activebackground=BTN_ACTIVE_BG, font=("Segoe UI", 9),
                      bd=0, command=self.destroy, cursor="hand2"
                      ).pack(pady=10, ipadx=20, ipady=4)
            self.protocol("WM_DELETE_WINDOW", self.destroy)
            return

        tk.Label(self, text="SENSOR", bg=BG, fg=DIM,
                 font=("Segoe UI", 8, "bold"),
                 anchor="w").pack(fill="x", padx=16, pady=(14, 4))

        list_frame = tk.Frame(self, bg=BG)
        list_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        self._listbox = tk.Listbox(
            list_frame, bg=ENTRY_BG, fg=TEXT, font=("Segoe UI", 9),
            selectbackground=ACCENT, selectforeground=WHITE,
            selectmode="browse", bd=0, highlightthickness=0, relief="flat",
            activestyle="none",
        )
        scrollbar = tk.Scrollbar(list_frame, command=self._listbox.yview)
        self._listbox.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self._listbox.pack(side="left", fill="both", expand=True)

        for _sid, lbl in self._available:
            self._listbox.insert("end", f"  {lbl}")
        if self._available:
            self._listbox.selection_set(0)

        tk.Label(self, text="GAUGE TYPE", bg=BG, fg=DIM,
                 font=("Segoe UI", 8, "bold"),
                 anchor="w").pack(fill="x", padx=16, pady=(4, 4))

        self._kind_var = tk.StringVar(value="circular")
        kind_frame = tk.Frame(self, bg=BG)
        kind_frame.pack(fill="x", padx=16, pady=(0, 12))
        for label, val in [("Circular", "circular"),
                           ("Bar", "bar"),
                           ("Digital", "digital")]:
            tk.Radiobutton(
                kind_frame, text=label, variable=self._kind_var, value=val,
                bg=BG, fg=LABEL_C, selectcolor=ENTRY_BG,
                activebackground=BG, activeforeground=TEXT,
                font=("Segoe UI", 9), anchor="w",
                indicatoron=True, highlightthickness=0,
            ).pack(side="left", padx=(0, 12))

        btn_row = tk.Frame(self, bg=BG)
        btn_row.pack(fill="x", padx=16, pady=(4, 14))
        tk.Button(btn_row, text="Cancel", bg=BTN_BG, fg=DIM,
                  activebackground=BTN_ACTIVE_BG, activeforeground=TEXT,
                  font=("Segoe UI", 9), bd=0, cursor="hand2",
                  command=self.destroy).pack(side="right", ipadx=16, ipady=4)
        tk.Button(btn_row, text="OK", bg=ACCENT, fg=WHITE,
                  activebackground=ACCENT_ACTIVE, activeforeground=WHITE,
                  font=("Segoe UI", 9, "bold"), bd=0, cursor="hand2",
                  command=self._on_ok).pack(side="right", padx=(0, 6),
                                            ipadx=20, ipady=4)

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Return>", lambda _e: self._on_ok())
        self.bind("<Escape>", lambda _e: self.destroy())

    def _on_ok(self):
        sel = self._listbox.curselection()
        if not sel:
            return
        sensor_id = self._available[sel[0]][0]
        kind = self._kind_var.get()
        self.result = (sensor_id, kind)
        self.destroy()
