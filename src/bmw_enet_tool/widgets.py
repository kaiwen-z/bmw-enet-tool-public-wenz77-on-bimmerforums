"""Tkinter gauge and layout widgets."""
import math
import tkinter as tk

from .ui_theme import (
    BG,
    BORDER,
    BOX_OUTLINE,
    BOX_TITLE,
    DIM,
    GAUGE_BG,
    LABEL_C,
    NEEDLE_C,
    OVERLAY_LABEL_DIM,
    OVERLAY_TEXT,
    PANEL,
    RAW_C,
    RING_DANG,
    RING_DIM,
    RING_NORM,
    RING_WARN,
    STRIP_BG,
    STIPPLE,
    TICK_MID,
    UNIT_C,
    VALUE_C,
)

# ─────────────────────────────────────────────────────────
#  Circular gauge widget
# ─────────────────────────────────────────────────────────
class Gauge(tk.Canvas):
    """
    A single circular instrument gauge.
    Arc spans from 220° to -40° (bottom-left to bottom-right, 260° sweep).
    """
    SWEEP = 260          # degrees of arc
    START = 220          # angle of lo end (degrees, tkinter: 0=right, CCW)

    def __init__(self, master, label, unit, lo, hi, warn, danger, decimals,
                 size=160, **kwargs):
        super().__init__(master, width=1, height=1,
                         bg=GAUGE_BG, bd=0, highlightthickness=0, **kwargs)
        self.lo       = lo
        self.hi       = hi
        self.warn     = warn
        self.danger   = danger
        self.decimals = decimals
        self.label    = label
        self.unit     = unit
        self.size     = size
        self._value   = None
        self._raw     = None
        self._last_size = (0, 0)
        self._cx      = size / 2
        self._cy      = size / 2
        self._r_outer = size / 2 - 4
        self._r_ring  = size / 2 - 10
        self._r_inner = size / 2 - 20
        self._r_needle= size / 2 - 24
        self._needle_id = None
        self._arc_id    = None
        self.bind("<Configure>", self._on_resize)

    def _angle_for(self, value):
        """Convert a value to canvas angle (tkinter: 0=3 o'clock, CCW)."""
        fraction = max(0.0, min(1.0, (value - self.lo) / (self.hi - self.lo)))
        # START° at lo, going clockwise → subtract fraction*SWEEP
        deg = self.START - fraction * self.SWEEP
        return deg

    def _polar(self, angle_deg, radius):
        rad = math.radians(angle_deg)
        x   = self._cx + radius * math.cos(rad)
        y   = self._cy - radius * math.sin(rad)
        return x, y

    def _draw_static(self):
        s, cx, cy = self.size, self._cx, self._cy
        r_o = self._r_outer

        # Outer bezel ring
        self.create_oval(cx-r_o, cy-r_o, cx+r_o, cy+r_o,
                         outline=BORDER, width=1, fill=GAUGE_BG)

        # Tick marks
        for i in range(21):
            fraction = i / 20
            ang      = self.START - fraction * self.SWEEP
            r1 = self._r_inner - 2
            r2 = r1 - (7 if i % 5 == 0 else 4)
            x1, y1 = self._polar(ang, r1)
            x2, y2 = self._polar(ang, r2)
            color = RING_DANG if fraction >= 0.9 else (RING_WARN if fraction >= 0.7 else TICK_MID)
            self.create_line(x1, y1, x2, y2, fill=color, width=2)

        # Label at bottom centre
        self.create_text(cx, cy + self._r_inner * 0.72,
                         text=self.label, fill=LABEL_C,
                         font=("Segoe UI", max(6, int(self.size/22))), anchor="center")

        # Unit label
        self.create_text(cx, cy + self._r_inner * 0.95,
                         text=self.unit, fill=UNIT_C,
                         font=("Segoe UI", max(5, int(self.size/28))), anchor="center")

        # Centre cap placeholder tag
        self._cap_id = self.create_oval(cx-6, cy-6, cx+6, cy+6,
                                        fill=BORDER, outline="")
        # Needle (will be redrawn)
        self._needle_id  = None
        self._value_id   = self.create_text(cx, cy - self._r_inner * 0.18,
                                            text="—", fill=DIM,
                                            font=("Courier New", max(8, int(self.size/14)),
                                                  "bold"),
                                            anchor="center")
        self._raw_id     = self.create_text(cx, cy + self._r_inner * 0.48,
                                            text="raw: —", fill=RAW_C,
                                            font=("Courier New", max(6, int(self.size/28))),
                                            anchor="center")
        # Arc drawn over static elements
        self._arc_id = None
        self._draw_arc(self.lo)

    def _on_resize(self, event):
        w, h = event.width, event.height
        if (w, h) == self._last_size or w < 20 or h < 20:
            return
        self._last_size = (w, h)
        s = min(w, h)
        self.size      = s
        self._cx       = w / 2
        self._cy       = h / 2
        self._r_outer  = s / 2 - 4
        self._r_ring   = s / 2 - 10
        self._r_inner  = s / 2 - 20
        self._r_needle = s / 2 - 24
        self._needle_id = None
        self._arc_id    = None
        self.delete("all")
        self._draw_static()
        self._redraw()
        if hasattr(self, "_active") and not self._active:
            self.set_active(False)

    def _draw_arc(self, value):
        """Draw the coloured progress arc."""
        if self._arc_id:
            self.delete(self._arc_id)
        frac  = max(0.0, min(1.0, (value - self.lo) / (self.hi - self.lo)))
        color = (RING_DANG if frac >= (self.danger - self.lo) / (self.hi - self.lo)
                 else RING_WARN if frac >= (self.warn - self.lo) / (self.hi - self.lo)
                 else RING_NORM)
        sweep_deg = frac * self.SWEEP
        r  = self._r_ring
        cx, cy = self._cx, self._cy
        x0, y0 = cx - r, cy - r
        x1, y1 = cx + r, cy + r
        # Colored arc: start at lo end (START), sweep clockwise (negative extent)
        self._arc_id = self.create_arc(x0, y0, x1, y1,
                                       start=self.START,
                                       extent=-sweep_deg,
                                       style="arc", outline=color, width=5)
        # Background arc: remainder from colored tip to hi end
        self.create_arc(x0, y0, x1, y1,
                        start=self.START - sweep_deg,
                        extent=-(self.SWEEP - sweep_deg),
                        style="arc", outline=RING_DIM, width=5)

    def update_value(self, physical: float, raw_int: int):
        self._value = physical
        self._raw   = raw_int
        self._redraw()

    def set_stale(self):
        """Called on disconnect — grey out."""
        self._value = None
        self._raw   = None
        self._redraw()

    def _redraw(self):
        cx, cy = self._cx, self._cy
        # Remove old needle
        if self._needle_id:
            self.delete(self._needle_id); self._needle_id = None

        if self._value is None:
            self.itemconfig(self._value_id, text="—", fill=DIM)
            self.itemconfig(self._raw_id,   text="raw: —", fill=RAW_C)
            self._draw_arc(self.lo)
            return

        v = self._value
        # Arc
        self._draw_arc(v)

        # Needle
        ang = self._angle_for(v)
        nx, ny = self._polar(ang, self._r_needle)
        frac   = max(0.0, min(1.0, (v - self.lo) / (self.hi - self.lo)))
        ncol   = (RING_DANG if frac >= (self.danger - self.lo)/(self.hi - self.lo)
                  else RING_WARN if frac >= (self.warn - self.lo)/(self.hi - self.lo)
                  else NEEDLE_C)
        self._needle_id = self.create_line(cx, cy, nx, ny,
                                           fill=ncol, width=2, capstyle="round")
        # Redraw cap on top
        self.tag_raise(self._cap_id)

        # Value text
        fmt  = f"{v:.{self.decimals}f}"
        vcol = (RING_DANG if frac >= (self.danger-self.lo)/(self.hi-self.lo)
                else RING_WARN if frac >= (self.warn-self.lo)/(self.hi-self.lo)
                else VALUE_C)
        self.itemconfig(self._value_id, text=fmt, fill=vcol)
        self.itemconfig(self._raw_id,   text=f"raw: {self._raw}", fill=RAW_C)
        self._raise_overlay()

    def _raise_overlay(self):
        """Keep the inactive overlay on top after every redraw."""
        self.tag_raise("overlay")

    def set_active(self, active: bool, on_toggle=None):
        """Show or hide the inactive overlay. Binds click to on_toggle callback."""
        self._active = active
        if on_toggle is not None:
            self._on_toggle = on_toggle
        self.delete("overlay")
        if not active:
            cx, cy = self._cx, self._cy
            r = self._r_outer
            self.create_oval(cx-r, cy-r, cx+r, cy+r,
                             fill=GAUGE_BG, outline="", stipple=STIPPLE,
                             tags="overlay")
            self.create_oval(cx-r, cy-r, cx+r, cy+r,
                             fill="", outline=BORDER, tags="overlay")
            fs = max(8, int(self.size / 16))
            fs_lbl = max(6, int(self.size / 22))
            self.create_text(cx, cy, text="CLICK TO\nACTIVATE",
                             fill=OVERLAY_TEXT, font=("Segoe UI", fs),
                             justify="center", tags="overlay")
            self.create_text(cx, cy + self._r_inner * 0.72, text=self.label,
                             fill=OVERLAY_LABEL_DIM, font=("Segoe UI", fs_lbl, "bold"),
                             tags="overlay")
            self.configure(cursor="hand2")
            self.bind("<Button-1>", self._toggle)
        else:
            self.configure(cursor="hand2")
            self.bind("<Button-1>", self._toggle)

    def _toggle(self, _event=None):
        if hasattr(self, "_on_toggle") and self._on_toggle:
            self._on_toggle()


# ─────────────────────────────────────────────────────────
#  Digital readout gauge widget
# ─────────────────────────────────────────────────────────
class DigitalGauge(tk.Canvas):
    """Circular bezel with a large centred numeric readout — no needle or arc."""

    def __init__(self, master, label, unit, lo, hi, warn, danger, decimals,
                 size=160, **kwargs):
        super().__init__(master, width=1, height=1,
                         bg=GAUGE_BG, bd=0, highlightthickness=0, **kwargs)
        self.lo       = lo
        self.hi       = hi
        self.warn     = warn
        self.danger   = danger
        self.decimals = decimals
        self.label    = label
        self.unit     = unit
        self.size     = size
        self._value   = None
        self._raw     = None
        self._last_size = (0, 0)
        self._cx      = size / 2
        self._cy      = size / 2
        self._r_outer = size / 2 - 4
        self._ring_id = None
        self.bind("<Configure>", self._on_resize)

    def _draw_static(self):
        cx, cy = self._cx, self._cy
        r_o = self._r_outer

        self.create_oval(cx - r_o, cy - r_o, cx + r_o, cy + r_o,
                         outline=BORDER, width=1, fill=GAUGE_BG)

        r_accent = r_o - 6
        self._ring_id = self.create_oval(
            cx - r_accent, cy - r_accent, cx + r_accent, cy + r_accent,
            outline=RING_DIM, width=2, fill="")

        fs_val  = max(17, int(self.size / 5.3))
        fs_unit = max(8, int(self.size / 16))
        fs_lbl  = max(6, int(self.size / 22))
        fs_raw  = max(6, int(self.size / 28))

        self._value_id = self.create_text(
            cx, cy - r_o * 0.08, text="—", fill=DIM,
            font=("Courier New", fs_val, "bold"), anchor="center")

        self._unit_id = self.create_text(
            cx, cy + r_o * 0.30, text=self.unit, fill=UNIT_C,
            font=("Segoe UI", fs_unit), anchor="center")

        self.create_text(cx, cy + r_o * 0.55, text=self.label, fill=LABEL_C,
                         font=("Segoe UI", fs_lbl), anchor="center")

        self._raw_id = self.create_text(
            cx, cy + r_o * 0.78, text="raw: —", fill=RAW_C,
            font=("Courier New", fs_raw), anchor="center")

    def _on_resize(self, event):
        w, h = event.width, event.height
        if (w, h) == self._last_size or w < 20 or h < 20:
            return
        self._last_size = (w, h)
        s = min(w, h)
        self.size     = s
        self._cx      = w / 2
        self._cy      = h / 2
        self._r_outer = s / 2 - 4
        self._ring_id = None
        self.delete("all")
        self._draw_static()
        self._redraw()
        if hasattr(self, "_active") and not self._active:
            self.set_active(False)

    def update_value(self, physical: float, raw_int: int):
        self._value = physical
        self._raw   = raw_int
        self._redraw()

    def set_stale(self):
        self._value = None
        self._raw   = None
        self._redraw()

    def _redraw(self):
        if self._value is None:
            self.itemconfig(self._value_id, text="—", fill=DIM)
            self.itemconfig(self._raw_id,   text="raw: —", fill=RAW_C)
            if self._ring_id:
                self.itemconfig(self._ring_id, outline=RING_DIM)
            return

        v = self._value
        frac = max(0.0, min(1.0, (v - self.lo) / (self.hi - self.lo)))
        vcol = (RING_DANG if frac >= (self.danger - self.lo) / (self.hi - self.lo)
                else RING_WARN if frac >= (self.warn - self.lo) / (self.hi - self.lo)
                else VALUE_C)
        ring_col = (RING_DANG if frac >= (self.danger - self.lo) / (self.hi - self.lo)
                    else RING_WARN if frac >= (self.warn - self.lo) / (self.hi - self.lo)
                    else RING_NORM)

        fmt = f"{v:.{self.decimals}f}"
        self.itemconfig(self._value_id, text=fmt, fill=vcol)
        self.itemconfig(self._raw_id,   text=f"raw: {self._raw}", fill=RAW_C)
        if self._ring_id:
            self.itemconfig(self._ring_id, outline=ring_col)
        self._raise_overlay()

    def _raise_overlay(self):
        self.tag_raise("overlay")

    def set_active(self, active: bool, on_toggle=None):
        self._active = active
        if on_toggle is not None:
            self._on_toggle = on_toggle
        self.delete("overlay")
        if not active:
            cx, cy = self._cx, self._cy
            r = self._r_outer
            self.create_oval(cx - r, cy - r, cx + r, cy + r,
                             fill=GAUGE_BG, outline="", stipple=STIPPLE,
                             tags="overlay")
            self.create_oval(cx - r, cy - r, cx + r, cy + r,
                             fill="", outline=BORDER, tags="overlay")
            fs = max(8, int(self.size / 16))
            fs_lbl = max(6, int(self.size / 22))
            self.create_text(cx, cy, text="CLICK TO\nACTIVATE",
                             fill=OVERLAY_TEXT, font=("Segoe UI", fs),
                             justify="center", tags="overlay")
            self.create_text(cx, cy + r * 0.55, text=self.label,
                             fill=OVERLAY_LABEL_DIM, font=("Segoe UI", fs_lbl, "bold"),
                             tags="overlay")
            self.configure(cursor="hand2")
            self.bind("<Button-1>", self._toggle)
        else:
            self.configure(cursor="hand2")
            self.bind("<Button-1>", self._toggle)

    def _toggle(self, _event=None):
        if hasattr(self, "_on_toggle") and self._on_toggle:
            self._on_toggle()


# ─────────────────────────────────────────────────────────
#  Horizontal bar gauge widget
# ─────────────────────────────────────────────────────────
class BarGauge(tk.Canvas):
    """A compact horizontal bar gauge for pressure sensors."""
    W, H = 310, 58

    def __init__(self, master, label, unit, lo, hi, warn, danger, decimals, **kwargs):
        super().__init__(master, width=1, height=self.H,
                         bg=GAUGE_BG, bd=0, highlightthickness=0, **kwargs)
        self.lo, self.hi   = lo, hi
        self.warn, self.danger = warn, danger
        self.decimals      = decimals
        self.label, self.unit = label, unit
        self._value        = None
        self._raw          = None
        self._W            = self.W
        self._H            = self.H
        self._last_w       = 0
        self._val_id       = None
        self._raw_id       = None
        self._bar_id       = None
        self.bind("<Configure>", self._on_bar_resize)

    def _draw_static(self):
        W, H = self._W, self._H
        # Label top-left
        self.create_text(8, 8, anchor="nw", text=self.label,
                         fill=LABEL_C, font=("Segoe UI", 8, "bold"), tags="static")
        # Unit top-right
        self.create_text(W-8, 8, anchor="ne", text=self.unit,
                         fill=UNIT_C, font=("Segoe UI", 7), tags="static")
        # Track background
        bx0, by0, bx1, by1 = 8, 26, W-8, 42
        self.create_rectangle(bx0, by0, bx1, by1, fill=STRIP_BG, outline=BORDER, width=1, tags="static")
        # Warn marker
        wx = bx0 + int((self.warn - self.lo) / (self.hi - self.lo) * (bx1 - bx0))
        self.create_line(wx, by0-3, wx, by1+3, fill=RING_WARN, width=1, dash=(2,2), tags="static")
        # Danger marker
        dx = bx0 + int((self.danger - self.lo) / (self.hi - self.lo) * (bx1 - bx0))
        self.create_line(dx, by0-3, dx, by1+3, fill=RING_DANG, width=1, dash=(2,2), tags="static")
        # Value display (centered above bar so it never overlaps)
        self._val_id = self.create_text(W/2, 18,
                                        text="—",
                                        fill=VALUE_C,
                                        font=("Courier New", 12, "bold"),
                                        anchor="center")

        # Raw value bottom right
        self._raw_id = self.create_text(W-8, H-6,
                                        anchor="se",
                                        text="raw: —",
                                        fill=RAW_C,
                                        font=("Courier New", 7))
        self._bar_id = None
        self._draw_bar(self.lo)

    def _draw_bar(self, value):
        if self._bar_id:
            self.delete(self._bar_id)
        W = self._W
        bx0, by0, bx1, by1 = 9, 27, W-9, 41
        frac  = max(0.0, min(1.0, (value - self.lo) / (self.hi - self.lo)))
        color = (RING_DANG if frac >= (self.danger-self.lo)/(self.hi-self.lo)
                 else RING_WARN if frac >= (self.warn-self.lo)/(self.hi-self.lo)
                 else RING_NORM)
        fill_x = bx0 + int(frac * (bx1 - bx0))
        if fill_x > bx0:
            self._bar_id = self.create_rectangle(bx0, by0, fill_x, by1,
                                                  fill=color, outline="")
        else:
            self._bar_id = self.create_rectangle(bx0, by0, bx0+1, by1,
                                                  fill=RING_DIM, outline="")

    def _on_bar_resize(self, event):
        w = event.width
        if w == self._last_w or w < 20:
            return
        self._last_w = w
        self._W = w
        self.delete("all")
        self._bar_id = None
        self._draw_static()
        if self._value is not None:
            self.update_value(self._value, self._raw)
        if hasattr(self, "_active") and not self._active:
            self.set_active(False)

    def set_active(self, active: bool, on_toggle=None):
        self._active = active
        if on_toggle is not None:
            self._on_toggle = on_toggle
        self.delete("overlay")
        if not active:
            W, H = self._W, self._H
            self.create_rectangle(0, 0, W, H,
                                  fill=GAUGE_BG, outline="", stipple=STIPPLE,
                                  tags="overlay")
            self.create_rectangle(0, 0, W, H,
                                  fill="", outline=BORDER, tags="overlay")
            self.create_text(W // 2, H // 2, text="CLICK TO ACTIVATE",
                             fill=OVERLAY_TEXT, font=("Segoe UI", 7),
                             tags="overlay")
            self.create_text(8, 8, anchor="nw", text=self.label,
                             fill=OVERLAY_LABEL_DIM, font=("Segoe UI", 8, "bold"),
                             tags="overlay")
            self.configure(cursor="hand2")
            self.bind("<Button-1>", self._toggle)
        else:
            self.configure(cursor="hand2")
            self.bind("<Button-1>", self._toggle)

    def _toggle(self, _event=None):
        if hasattr(self, "_on_toggle") and self._on_toggle:
            self._on_toggle()

    def update_value(self, physical: float, raw_int: int):
        self._value = physical
        self._raw   = raw_int
        self._draw_bar(physical)
        frac  = max(0.0, min(1.0, (physical - self.lo) / (self.hi - self.lo)))
        vcol  = (RING_DANG if frac >= (self.danger-self.lo)/(self.hi-self.lo)
                 else RING_WARN if frac >= (self.warn-self.lo)/(self.hi-self.lo)
                 else VALUE_C)
        self.itemconfig(self._val_id, text=f"{physical:.{self.decimals}f}", fill=vcol)
        self.itemconfig(self._raw_id, text=f"raw: {raw_int}", fill=RAW_C)

    def set_stale(self):
        self._value = None; self._raw = None
        self._draw_bar(self.lo)
        self.itemconfig(self._val_id, text="—", fill=DIM)
        self.itemconfig(self._raw_id, text="raw: —", fill=RAW_C)


# ─────────────────────────────────────────────────────────
#  Custom scrollbar (Canvas-drawn so colours work on Windows)
# ─────────────────────────────────────────────────────────
class CanvasScrollbar(tk.Canvas):
    """Vertical scrollbar drawn on Canvas so bg/trough/thumb colours apply on Windows."""
    WIDTH = 14

    def __init__(self, master, command=None, troughcolor=BORDER, thumbcolor=None,
                 thumbactive=UNIT_C, **kwargs):
        _bg = master.cget("bg") if hasattr(master, "cget") else PANEL
        super().__init__(master, width=self.WIDTH, height=100, bg=_bg,
                         bd=0, highlightthickness=0, **kwargs)
        self._command   = command
        self._trough_c  = troughcolor
        self._thumb_c   = thumbcolor if thumbcolor is not None else UNIT_C
        self._thumb_ac  = thumbactive
        self._first     = 0.0
        self._last      = 1.0
        self._thumb_id  = None
        self._drag_y0   = None
        self._drag_frac0 = None
        self.bind("<Configure>", self._on_configure)
        self.bind("<Button-1>", self._on_click)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<MouseWheel>", self._on_wheel)

    def set(self, first, last):
        # Tkinter passes first/last as strings from yscrollcommand
        try:
            self._first = max(0.0, min(1.0, float(first)))
            self._last  = max(0.0, min(1.0, float(last)))
        except (TypeError, ValueError):
            return
        if self._last < self._first:
            self._last = self._first
        self._draw()

    def _on_configure(self, event):
        self._draw()

    def _draw(self):
        self.delete("scrollbar")
        w = self.winfo_width() or self.WIDTH
        h = self.winfo_height() or 100
        # Trough (track background)
        self.create_rectangle(2, 0, w - 2, h, fill=self._trough_c, outline="", tags="scrollbar")
        # Thumb (position indicator) — ensure minimum height so it's always visible
        y1 = int(self._first * h)
        y2 = int(self._last * h)
        if y2 - y1 < 10:
            y2 = min(h, y1 + 10)
        fill = self._thumb_ac if self._drag_y0 is not None else self._thumb_c
        self._thumb_id = self.create_rectangle(
            1, y1, w - 1, y2, fill=fill, outline=RING_NORM, width=1, tags="scrollbar"
        )

    def _frac_from_y(self, y):
        h = self.winfo_height() or 1
        return max(0.0, min(1.0, y / h))

    def _on_click(self, event):
        h = self.winfo_height() or 1
        y1 = int(self._first * h)
        y2 = int(self._last * h)
        if event.y < y1:
            self._command("moveto", max(0.0, self._first - 0.2))
        elif event.y > y2:
            self._command("moveto", min(1.0, self._first + 0.2))
        else:
            self._drag_y0 = event.y
            self._drag_frac0 = self._first
            self._draw()

    def _on_drag(self, event):
        if self._drag_y0 is None or not self._command:
            return
        h = self.winfo_height() or 1
        dy = event.y - self._drag_y0
        frac_delta = dy / h
        new_frac = max(0.0, min(1.0, self._drag_frac0 + frac_delta))
        self._command("moveto", new_frac)
        self._drag_frac0 = new_frac
        self._drag_y0 = event.y

    def _on_release(self, _event):
        self._drag_y0 = None
        self._draw()

    def _on_wheel(self, event):
        if self._command:
            self._command("scroll", int(-1 * (event.delta / 120)), "units")


# ─────────────────────────────────────────────────────────
#  Rounded group box container
# ─────────────────────────────────────────────────────────
class GroupBox(tk.Canvas):
    """Canvas that draws a rounded-rect border with a section title.
    Place child widgets inside self.inner (a plain Frame)."""
    RADIUS = 10

    def __init__(self, master, title, **kwargs):
        super().__init__(master, bg=BG, bd=0, highlightthickness=0, **kwargs)
        self._title = title
        self.inner  = tk.Frame(self, bg=BG)
        self._win   = self.create_window(0, 0, anchor="nw", window=self.inner)
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, event):
        w, h = event.width, event.height
        self.delete("box")
        r, p = self.RADIUS, 3
        x0, y0, x1, y1 = p, p, w-p, h-p
        # Rounded rect outline via arcs + lines
        kw = dict(style="arc", outline=BOX_OUTLINE, width=1, tags="box")
        self.create_arc(x0,      y0,      x0+2*r, y0+2*r, start=90,  extent=90,  **kw)
        self.create_arc(x1-2*r,  y0,      x1,     y0+2*r, start=0,   extent=90,  **kw)
        self.create_arc(x0,      y1-2*r,  x0+2*r, y1,     start=180, extent=90,  **kw)
        self.create_arc(x1-2*r,  y1-2*r,  x1,     y1,     start=270, extent=90,  **kw)
        lkw = dict(fill=BOX_OUTLINE, width=1, tags="box")
        self.create_line(x0+r, y0,  x1-r, y0,  **lkw)
        self.create_line(x0+r, y1,  x1-r, y1,  **lkw)
        self.create_line(x0,   y0+r, x0,  y1-r, **lkw)
        self.create_line(x1,   y0+r, x1,  y1-r, **lkw)
        # Title cutout
        tw = len(self._title) * 6 + 8
        self.create_rectangle(x0+r+2, y0-2, x0+r+tw, y0+2,
                               fill=BG, outline="", tags="box")
        self.create_text(x0+r+6, y0, anchor="w", text=self._title,
                         fill=BOX_TITLE, font=("Segoe UI", 8, "bold"), tags="box")
        # Resize inner frame
        self.coords(self._win, r+p+2, r+p+2)
        self.itemconfigure(self._win, width=w-2*(r+p+2), height=h-2*(r+p+2))

