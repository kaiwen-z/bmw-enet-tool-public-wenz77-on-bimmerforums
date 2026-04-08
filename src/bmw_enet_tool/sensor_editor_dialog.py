"""Sensor add / edit dialog with calibration inputs."""
import tkinter as tk

from .sensors import generate_sensor_id
from .ui_theme import (
    ACCENT,
    ACCENT_ACTIVE,
    BG,
    BTN_ACTIVE_BG,
    BTN_BG,
    DIM,
    ENTRY_BG,
    BORDER,
    LABEL_C,
    TEXT,
    WHITE,
)
from .widgets import CanvasScrollbar


class SensorEditorDialog(tk.Toplevel):
    """Modal dialog for creating or editing a sensor definition."""

    def __init__(self, master, sensor_data=None):
        super().__init__(master)
        self._editing = sensor_data is not None
        self.title("Edit Sensor" if self._editing else "Add Sensor")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(300, 380)
        self.result = None

        self.transient(master)
        self.grab_set()

        w, h = 380, 520
        px = master.winfo_rootx() + (master.winfo_width() - w) // 2
        py = master.winfo_rooty() + (master.winfo_height() - h) // 2
        self.geometry(f"{w}x{h}+{px}+{py}")

        sd = sensor_data or {}

        _lbl_kw = dict(bg=BG, fg=DIM, font=("Segoe UI", 7, "bold"), anchor="w")
        _ent_kw = dict(bg=ENTRY_BG, fg=TEXT, insertbackground=ACCENT,
                       relief="flat", font=("Courier New", 9), bd=0,
                       highlightthickness=1, highlightcolor=ACCENT,
                       highlightbackground=BORDER)

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True)

        canvas = tk.Canvas(
            body, bg=BG, highlightthickness=0, bd=0,
            yscrollincrement=24)

        def _canvas_yview(*args):
            canvas.yview(*args)
            sb.set(*canvas.yview())

        # Canvas-drawn scrollbar (pack right *before* canvas so the canvas cannot cover it).
        sb = CanvasScrollbar(
            body, command=_canvas_yview,
            troughcolor=BORDER, thumbcolor=ACCENT, thumbactive=ACCENT_ACTIVE,
            bar_width=18)
        canvas.configure(yscrollcommand=sb.set)

        scroll_inner = tk.Frame(canvas, bg=BG)
        scroll_win = canvas.create_window((0, 0), window=scroll_inner, anchor="nw")

        def _on_inner_configure(_event=None):
            canvas.update_idletasks()
            try:
                cw = max(canvas.winfo_width() or 1, scroll_inner.winfo_reqwidth() or 1)
                ch = (scroll_inner.winfo_reqheight() or scroll_inner.winfo_height() or 1)
                if ch > 0:
                    canvas.configure(scrollregion=(0, 0, cw, ch))
            except tk.TclError:
                canvas.configure(scrollregion=canvas.bbox("all") or (0, 0, 0, 0))
            sb.set(*canvas.yview())

        def _on_canvas_configure(event):
            canvas.itemconfig(scroll_win, width=event.width)

        scroll_inner.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            sb.set(*canvas.yview())

        def _bind_wheel_recursive(widget):
            widget.bind("<MouseWheel>", _on_mousewheel)
            for child in widget.winfo_children():
                _bind_wheel_recursive(child)

        sb.pack(side="right", fill="y", padx=(0, 2))
        canvas.pack(side="left", fill="both", expand=True)

        def _row(parent, label, default=""):
            tk.Label(parent, text=label, **_lbl_kw).pack(fill="x", padx=16, pady=(6, 1))
            var = tk.StringVar(value=str(default))
            tk.Entry(parent, textvariable=var, **_ent_kw).pack(
                fill="x", padx=16, ipady=3)
            return var

        form = scroll_inner

        # ?? Identity ??
        tk.Label(form, text="IDENTITY", bg=BG, fg=LABEL_C,
                 font=("Segoe UI", 8, "bold")).pack(fill="x", padx=12, pady=(10, 0))
        self._v_label = _row(form, "Label", sd.get("label", ""))
        self._v_did = _row(form, "DID Address (hex)",
                           f"0x{sd['did']:04X}" if "did" in sd else "")
        self._v_ecu = _row(form, "ECU Address (hex)",
                           f"0x{sd['ecu']:02X}" if "ecu" in sd else "0x12")
        self._v_size = _row(form, "Response Size (bytes)",
                            sd.get("size", 2))

        # ?? Display ??
        tk.Label(form, text="DISPLAY", bg=BG, fg=LABEL_C,
                 font=("Segoe UI", 8, "bold")).pack(fill="x", padx=12, pady=(10, 0))
        self._v_unit = _row(form, "Unit", sd.get("unit", ""))
        self._v_dec = _row(form, "Decimals", sd.get("decimals", 1))
        self._v_min = _row(form, "Gauge Min", sd.get("min", 0))
        self._v_max = _row(form, "Gauge Max", sd.get("max", ""))

        # ?? Thresholds ??
        tk.Label(form, text="THRESHOLDS", bg=BG, fg=LABEL_C,
                 font=("Segoe UI", 8, "bold")).pack(fill="x", padx=12, pady=(10, 0))
        self._v_warn = _row(form, "Warning", sd.get("warn", ""))
        self._v_danger = _row(form, "Danger", sd.get("danger", ""))

        # ?? Calibration ??
        tk.Label(form, text="CALIBRATION", bg=BG, fg=LABEL_C,
                 font=("Segoe UI", 8, "bold")).pack(fill="x", padx=12, pady=(10, 0))
        self._v_cal_raw = _row(form, "Raw Reference (hex)",
                               f"0x{sd['calibration_raw']:X}"
                               if "calibration_raw" in sd else "")
        self._v_cal_val = _row(form, "Physical Value",
                               sd.get("calibration_value", ""))

        # Bottom padding so the last field is not clipped by the scroll area edge
        tk.Frame(form, bg=BG).pack(fill="x", pady=(0, 12))

        _bind_wheel_recursive(scroll_inner)
        canvas.bind("<MouseWheel>", _on_mousewheel)

        # ?? Buttons ??
        btn_row = tk.Frame(self, bg=BG)
        btn_row.pack(fill="x", padx=16, pady=(12, 14))
        tk.Button(btn_row, text="Cancel", bg=BTN_BG, fg=DIM,
                  activebackground=BTN_ACTIVE_BG, activeforeground=TEXT,
                  font=("Segoe UI", 9), bd=0, cursor="hand2",
                  command=self.destroy).pack(side="right", ipadx=16, ipady=4)
        tk.Button(btn_row, text="OK", bg=ACCENT, fg=WHITE,
                  activebackground=ACCENT_ACTIVE, activeforeground=WHITE,
                  font=("Segoe UI", 9, "bold"), bd=0, cursor="hand2",
                  command=self._on_ok).pack(side="right", padx=(0, 6),
                                            ipadx=20, ipady=4)

        self._sensor_data = sd
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Return>", lambda _e: self._on_ok())
        self.bind("<Escape>", lambda _e: self.destroy())

    # ?? Helpers ??
    @staticmethod
    def _parse_hex(text):
        text = text.strip()
        if text.startswith(("0x", "0X")):
            return int(text, 16)
        return int(text, 16)

    @staticmethod
    def _parse_num(text):
        text = text.strip()
        if not text:
            return None
        return float(text)

    # ?? OK handler ??
    def _on_ok(self):
        try:
            label = self._v_label.get().strip()
            if not label:
                raise ValueError("Label is required")
            did = self._parse_hex(self._v_did.get())
            ecu = self._parse_hex(self._v_ecu.get())
            size = int(self._v_size.get().strip())
            unit = self._v_unit.get().strip() or "?"
            decimals = int(self._v_dec.get().strip())
            lo = self._parse_num(self._v_min.get()) or 0
            hi = self._parse_num(self._v_max.get())
            if hi is None:
                raise ValueError("Gauge Max is required")
            warn = self._parse_num(self._v_warn.get())
            if warn is None:
                warn = hi * 0.8
            danger = self._parse_num(self._v_danger.get())
            if danger is None:
                danger = hi * 0.9
            cal_raw = self._parse_hex(self._v_cal_raw.get())
            cal_val_txt = self._v_cal_val.get().strip()
            cal_val = float(cal_val_txt) if cal_val_txt else None
            if cal_val is None:
                raise ValueError("Calibration physical value is required")
        except Exception as exc:
            from tkinter import messagebox
            messagebox.showerror("Validation Error", str(exc), parent=self)
            return

        if self._editing:
            sid = self._sensor_data["sensor_id"]
        else:
            sid = generate_sensor_id(label)

        offset = self._sensor_data.get("offset", 0.0) if self._editing else 0.0
        scale = (cal_val - offset) / cal_raw if cal_raw else 1.0

        self.result = {
            "sensor_id": sid,
            "label": label,
            "did": did,
            "ecu": ecu,
            "size": size,
            "unit": unit,
            "min": lo,
            "max": hi,
            "warn": warn,
            "danger": danger,
            "decimals": decimals,
            "scale": scale,
            "offset": offset,
            "calibration_raw": cal_raw,
            "calibration_value": cal_val,
        }
        self.destroy()
