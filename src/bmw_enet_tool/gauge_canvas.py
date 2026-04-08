"""Free-form gauge host frame with placed, movable, resizable tiles."""
import math
import tkinter as tk

from .sensors import SENSORS, get_sensor_by_id, index_of
from .ui_theme import BG, GAUGE_BG, LABEL_C, PANEL
from .widgets import BarGauge, DigitalGauge, Gauge

MIN_REL_W = 0.08
MIN_REL_H = 0.06
CHROME_H = 30
RESIZE_HIT = 7
# Rounded tile + subtle hover (outline via background canvas, not loud Frame chrome).
ROUND_R = 8
TILE_BORDER = "#242c3a"
HOVER_BORDER = "#39465a"
RZ_FILL = "#1a2636"
RZ_BORDER = "#3f5570"
_RECT_EPS = 1e-5
# Bar tiles: short horizontal bands (~default layout 0.32 x 0.115).
BAR_STRIP_REL_W = 0.32
BAR_MAX_REL_H = 0.115
BAR_PREF_REL_W = 0.30
GRID_MINOR = "#0f131c"
GRID_MAJOR = "#141b28"
GRID_SECTION = "#2a4262"
# Fixed logical grid dimensions (locked to window size).
GRID_COLS = 24
GRID_ROWS = 24
GRID_MAJOR_EVERY = 4
BAR_CLUSTER_DIST = 0.24


def _rects_overlap(a, b, eps=_RECT_EPS):
    """Return True if relative axis-aligned rects *a* and *b* intersect."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (
        ax + aw <= bx + eps
        or bx + bw <= ax + eps
        or ay + ah <= by + eps
        or by + bh <= ay + eps
    )


def _grid_cell_metrics_region(n, inner_w, inner_h, pad=0.01):
    """Pack *n* tiles in a rectangle of relative size inner_w x inner_h."""
    if n <= 0:
        return 1, 1, pad, inner_w, inner_h
    iw = max(float(inner_w), MIN_REL_W)
    ih = max(float(inner_h), MIN_REL_H)
    aspect = iw / max(ih, 1e-9)
    cols = max(1, min(n, round(math.sqrt(n * aspect))))
    rows = max(1, math.ceil(n / cols))
    p = pad
    for _ in range(80):
        cw = (iw - (cols + 1) * p) / cols
        ch = (ih - (rows + 1) * p) / rows
        if cw >= MIN_REL_W - 1e-9 and ch >= MIN_REL_H - 1e-9:
            return cols, rows, p, cw, ch
        p *= 0.88
        if p < 1e-5:
            break
    p = max(0.0, p)
    cw = max(MIN_REL_W, (iw - (cols + 1) * p) / cols)
    ch = max(MIN_REL_H, (ih - (rows + 1) * p) / rows)
    return cols, rows, p, cw, ch


def _rounded_tile_background(canvas, x1, y1, x2, y2, r, fill, outline, ow):
    """Draw a filled rounded rectangle (corner radius *r*) for the tile face."""
    tag = "tileface"
    canvas.delete(tag)
    if x2 <= x1 + 2 or y2 <= y1 + 2:
        return
    r = int(max(1, min(r, (x2 - x1) // 2, (y2 - y1) // 2)))
    if r <= 1:
        canvas.create_rectangle(
            x1, y1, x2, y2, fill=fill, outline=outline, width=max(ow, 1), tags=tag)
        return
    k = dict(fill=fill, outline="", width=0, tags=tag)
    canvas.create_rectangle(x1 + r, y1, x2 - r, y2, **k)
    canvas.create_rectangle(x1, y1 + r, x2, y2 - r, **k)
    canvas.create_arc(x1, y1, x1 + 2 * r, y1 + 2 * r, start=90, extent=90,
                      style=tk.PIESLICE, **k)
    canvas.create_arc(x2 - 2 * r, y1, x2, y1 + 2 * r, start=0, extent=90,
                      style=tk.PIESLICE, **k)
    canvas.create_arc(x1, y2 - 2 * r, x1 + 2 * r, y2, start=180, extent=90,
                      style=tk.PIESLICE, **k)
    canvas.create_arc(x2 - 2 * r, y2 - 2 * r, x2, y2, start=270, extent=90,
                      style=tk.PIESLICE, **k)
    if outline and ow > 0:
        o = dict(style=tk.ARC, outline=outline, width=ow, tags=tag)
        canvas.create_arc(x1, y1, x1 + 2 * r, y1 + 2 * r, start=90, extent=90, **o)
        canvas.create_arc(x2 - 2 * r, y1, x2, y1 + 2 * r, start=0, extent=90, **o)
        canvas.create_arc(x1, y2 - 2 * r, x1 + 2 * r, y2, start=180, extent=90, **o)
        canvas.create_arc(x2 - 2 * r, y2 - 2 * r, x2, y2, start=270, extent=90, **o)
        canvas.create_line(x1 + r, y1, x2 - r, y1, fill=outline, width=ow, tags=tag)
        canvas.create_line(x1 + r, y2, x2 - r, y2, fill=outline, width=ow, tags=tag)
        canvas.create_line(x1, y1 + r, x1, y2 - r, fill=outline, width=ow, tags=tag)
        canvas.create_line(x2, y1 + r, x2, y2 - r, fill=outline, width=ow, tags=tag)


def _bar_stack_params(n_b, inner_h, gap):
    """Uniform bar band height and y-positions (relative), top-aligned stack."""
    if n_b <= 0:
        return 0.0, []
    gh = max(0.0, float(inner_h))
    bh = min(BAR_MAX_REL_H, (gh - (n_b + 1) * gap) / n_b)
    bh = max(MIN_REL_H, bh)
    if n_b * bh + (n_b + 1) * gap > gh + 1e-9:
        bh = max(MIN_REL_H, (gh - (n_b + 1) * gap) / n_b)
    relies = []
    y = gap
    for _ in range(n_b):
        relies.append(y)
        y += bh + gap
    return bh, relies


def _create_gauge(parent, sensor_id, kind):
    """Instantiate the correct gauge widget for *sensor_id* and *kind*."""
    idx = index_of(sensor_id)
    lbl, _did, _ecu, _sz, _scale, unit, lo, hi, warn, danger, dec = SENSORS[idx]
    if kind == "bar":
        return BarGauge(parent, lbl, unit, lo, hi, warn, danger, dec)
    if kind == "digital":
        return DigitalGauge(parent, lbl, unit, lo, hi, warn, danger, dec, size=195)
    return Gauge(parent, lbl, unit, lo, hi, warn, danger, dec, size=195)


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _rect_center(rect):
    return rect["x"] + rect["w"] * 0.5, rect["y"] + rect["h"] * 0.5


def _set_rect_center(rect, cx, cy):
    rect["x"] = cx - rect["w"] * 0.5
    rect["y"] = cy - rect["h"] * 0.5


def _distance(a, b):
    ax, ay = a
    bx, by = b
    return math.hypot(ax - bx, ay - by)


# ??????????????????????????????????????????????????????????????
#  Single placed tile ? wraps one gauge widget with hover chrome
# ??????????????????????????????????????????????????????????????
class PlacedGaugeFrame(tk.Frame):
    """Wrapper placed on the host with relative coords.  Provides hover
    chrome for move, resize and delete."""

    _CURSORS = {
        "n": "sb_v_double_arrow",
        "s": "sb_v_double_arrow",
        "e": "sb_h_double_arrow",
        "w": "sb_h_double_arrow",
        "nw": "top_left_corner",
        "ne": "top_right_corner",
        "sw": "bottom_left_corner",
        "se": "bottom_right_corner",
    }

    def __init__(self, host, sensor_id, kind, on_delete=None, **kw):
        super().__init__(host, bg=BG, bd=0, highlightthickness=0, **kw)
        self.sensor_id = sensor_id
        self.kind = kind
        self._host = host
        self._on_delete = on_delete
        self._is_dragging = False
        self._chrome_visible = False

        self._decor = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0)
        self._decor.place(x=0, y=0, relwidth=1, relheight=1)
        self._decor.bind("<Configure>", self._on_decor_configure)

        self._inner = tk.Frame(self, bg=GAUGE_BG, bd=0, highlightthickness=0)
        self.gauge = _create_gauge(self._inner, sensor_id, kind)
        self.gauge.pack(fill="both", expand=True)

        # Canvas.lower() is for canvas items; use Tk window stacking for the tile face.
        self.tk.call("lower", self._decor._w)
        self._inner.lift()

        # ?? Chrome bar (below top resize strip, hidden by default) ??
        self._chrome = tk.Frame(self, bg=PANEL, height=CHROME_H)
        self._chrome_hide_id = None
        self._chrome.configure(cursor="fleur")
        self._chrome.bind("<Button-1>", self._move_start)
        self._chrome.bind("<B1-Motion>", self._move_drag)
        self._chrome.bind("<ButtonRelease-1>", self._move_end)

        handle = tk.Label(self._chrome, text=" \u22ee\u22ee ", bg=PANEL, fg=LABEL_C,
                          font=("Segoe UI", 10), cursor="fleur")
        handle.bind("<Button-1>", self._move_start)
        handle.bind("<B1-Motion>", self._move_drag)
        handle.bind("<ButtonRelease-1>", self._move_end)

        del_btn = tk.Label(
            self._chrome, text="\u00d7", bg="#3a2028", fg="#ff6b6b",
            font=("Segoe UI", 14, "bold"), cursor="hand2", padx=10, pady=2)
        del_btn.pack(side="right", padx=(4, 6), pady=3)
        del_btn.bind("<Button-1>", lambda _e: self._do_delete())

        _sdata = get_sensor_by_id(sensor_id) or {}
        self._chrome_title = tk.Label(
            self._chrome, text=_sdata.get("label", sensor_id), bg=PANEL, fg=LABEL_C,
            font=("Segoe UI", 8), anchor="w", cursor="fleur")
        self._chrome_title.bind("<Button-1>", self._move_start)
        self._chrome_title.bind("<B1-Motion>", self._move_drag)
        self._chrome_title.bind("<ButtonRelease-1>", self._move_end)

        handle.pack(side="left", padx=(4, 2))
        self._chrome_title.pack(side="left", fill="x", expand=True, padx=2)

        # ?? Resize hit-zones (edges + corners); placed when chrome visible ??
        _rz_kw = dict(
            bd=0,
            highlightthickness=1,
            highlightbackground=RZ_BORDER,
            highlightcolor=RZ_BORDER,
        )
        # Visible resize affordance for obvious hover feedback.
        self._rz_n = tk.Frame(self, bg=RZ_FILL, cursor=self._CURSORS["n"], **_rz_kw)
        self._rz_s = tk.Frame(self, bg=RZ_FILL, cursor=self._CURSORS["s"], **_rz_kw)
        self._rz_e = tk.Frame(self, bg=RZ_FILL, cursor=self._CURSORS["e"], **_rz_kw)
        self._rz_w = tk.Frame(self, bg=RZ_FILL, cursor=self._CURSORS["w"], **_rz_kw)
        self._rz_nw = tk.Frame(self, bg=RZ_FILL, cursor=self._CURSORS["nw"],
                               width=RESIZE_HIT * 2, height=RESIZE_HIT * 2, **_rz_kw)
        self._rz_ne = tk.Frame(self, bg=RZ_FILL, cursor=self._CURSORS["ne"],
                               width=RESIZE_HIT * 2, height=RESIZE_HIT * 2, **_rz_kw)
        self._rz_sw = tk.Frame(self, bg=RZ_FILL, cursor=self._CURSORS["sw"],
                               width=RESIZE_HIT * 2, height=RESIZE_HIT * 2, **_rz_kw)
        self._rz_se = tk.Frame(self, bg=RZ_FILL, cursor=self._CURSORS["se"],
                               width=RESIZE_HIT * 2, height=RESIZE_HIT * 2, **_rz_kw)
        self._resize_zones = (
            (self._rz_n, "n"), (self._rz_s, "s"), (self._rz_e, "e"), (self._rz_w, "w"),
            (self._rz_nw, "nw"), (self._rz_ne, "ne"),
            (self._rz_sw, "sw"), (self._rz_se, "se"),
        )
        for fr, edge in self._resize_zones:
            fr.bind("<Button-1>", lambda e, ed=edge: self._resize_edge_start(ed, e))
            fr.bind("<B1-Motion>", self._resize_edge_drag)
            fr.bind("<ButtonRelease-1>", self._resize_edge_end)
            fr.bind("<Enter>", self._on_enter)
            fr.bind("<Leave>", self._on_leave)

        # ?? Hover enter/leave on every sub-widget ??
        for w in (self, self._decor, self._inner, self._chrome, self.gauge):
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)
        for child in self._chrome.winfo_children():
            child.bind("<Enter>", self._on_enter)
            child.bind("<Leave>", self._on_leave)

        # ?? Drag state ??
        self._drag_x0 = 0
        self._drag_y0 = 0
        self._drag_relx0 = 0.0
        self._drag_rely0 = 0.0
        self._resize_edge = ""
        self._resize_rx0 = 0.0
        self._resize_ry0 = 0.0
        self._resize_rw0 = 0.0
        self._resize_rh0 = 0.0

    def _on_decor_configure(self, event):
        self._paint_tile_face(event.width, event.height)

    def _paint_tile_face(self, w, h):
        if w < 4 or h < 4:
            return
        r = min(ROUND_R, max(3, w // 10), max(3, h // 10))
        outline = HOVER_BORDER if self._chrome_visible else TILE_BORDER
        ow = 1
        _rounded_tile_background(self._decor, 0, 0, w - 1, h - 1, r,
                                 GAUGE_BG, outline, ow)
        iw = max(4, w - 2 * r)
        ih = max(4, h - 2 * r)
        self._inner.place(x=r, y=r, width=iw, height=ih)

    # ?? Hover chrome visibility ????????????????????????????????
    def _on_enter(self, _event=None):
        if not self._host.is_editing_enabled():
            return
        self._cancel_hide()
        self._host.bring_tile_to_front(self)
        self._show_chrome()

    def _on_leave(self, _event=None):
        if not self._is_dragging:
            self._schedule_hide()

    def _cancel_hide(self, _event=None):
        if self._chrome_hide_id is not None:
            self.after_cancel(self._chrome_hide_id)
            self._chrome_hide_id = None

    def _schedule_hide(self):
        self._cancel_hide()
        self._hide_chrome()

    def _place_resize_zones(self):
        h = RESIZE_HIT
        tb = CHROME_H
        self.update_idletasks()
        ph = max(self.winfo_height(), 1)
        side_h = max(h, ph - tb - h)
        self._rz_n.place(x=0, y=tb, relwidth=1.0, height=h)
        self._rz_s.place(relx=0, rely=1.0, anchor="sw", relwidth=1.0, height=h)
        self._rz_w.place(x=0, y=tb, anchor="nw", width=h, height=side_h)
        self._rz_e.place(relx=1.0, x=0, y=tb, anchor="ne", width=h, height=side_h)
        self._rz_nw.place(x=0, y=tb, anchor="nw")
        self._rz_ne.place(relx=1.0, x=0, y=tb, anchor="ne")
        self._rz_sw.place(x=0, rely=1.0, y=0, anchor="sw")
        self._rz_se.place(relx=1.0, rely=1.0, x=0, y=0, anchor="se")

    def _show_chrome(self):
        self._place_resize_zones()
        self._chrome.place(x=0, y=0, relwidth=1.0, height=CHROME_H)
        self._chrome_visible = True
        if self.kind == "bar":
            pad_top = CHROME_H
            self.gauge.pack_configure(pady=(pad_top, 0))
        self.update_idletasks()
        self._paint_tile_face(self.winfo_width(), self.winfo_height())
        self.tk.call("lower", self._decor._w)
        self._inner.lift()
        for fr, _ in self._resize_zones:
            fr.lift()
        self._chrome.lift()

    def _hide_chrome(self):
        self._chrome.place_forget()
        self._chrome_visible = False
        if self.kind == "bar":
            self.gauge.pack_configure(pady=0)
        for fr, _ in self._resize_zones:
            fr.place_forget()
        self._chrome_hide_id = None
        self.update_idletasks()
        self._paint_tile_face(self.winfo_width(), self.winfo_height())
        self.tk.call("lower", self._decor._w)
        self._inner.lift()

    # ?? Move via drag handle ???????????????????????????????????
    def _move_start(self, event):
        if not self._host.is_editing_enabled():
            return
        self._is_dragging = True
        self._host.bring_tile_to_front(self)
        self._drag_x0 = event.x_root
        self._drag_y0 = event.y_root
        info = self.place_info()
        self._drag_relx0 = float(info.get("relx", 0))
        self._drag_rely0 = float(info.get("rely", 0))

    def _move_drag(self, event):
        hw = self._host.winfo_width() or 1
        hh = self._host.winfo_height() or 1
        dx = (event.x_root - self._drag_x0) / hw
        dy = (event.y_root - self._drag_y0) / hh
        info = self.place_info()
        rw = float(info.get("relwidth", 0.2))
        rh = float(info.get("relheight", 0.2))
        new_rx = max(0.0, min(1.0 - rw, self._drag_relx0 + dx))
        new_ry = max(0.0, min(1.0 - rh, self._drag_rely0 + dy))
        new_rx, new_ry, _, _ = self._host.snap_and_clamp_rect(
            self.sensor_id, new_rx, new_ry, rw, rh, resize=False
        )
        if self._host.rect_overlaps_any(self.sensor_id, (new_rx, new_ry, rw, rh)):
            return
        self.place_configure(relx=new_rx, rely=new_ry)

    def _move_end(self, _event):
        self._is_dragging = False
        self._host.bring_tile_to_front(self)
        self._host.record_user_edit(self.sensor_id)

    # ?? Resize via edge / corner hit-zones ???????????????????????
    def _resize_edge_start(self, which, event):
        if not self._host.is_editing_enabled():
            return
        self._is_dragging = True
        self._resize_edge = which
        self._drag_x0 = event.x_root
        self._drag_y0 = event.y_root
        info = self.place_info()
        self._resize_rx0 = float(info.get("relx", 0))
        self._resize_ry0 = float(info.get("rely", 0))
        self._resize_rw0 = float(info.get("relwidth", 0.2))
        self._resize_rh0 = float(info.get("relheight", 0.2))

    def _resize_edge_drag(self, event):
        which = self._resize_edge
        if not which:
            return
        hw = self._host.winfo_width() or 1
        hh = self._host.winfo_height() or 1
        dx = (event.x_root - self._drag_x0) / hw
        dy = (event.y_root - self._drag_y0) / hh
        rx, ry = self._resize_rx0, self._resize_ry0
        rw, rh = self._resize_rw0, self._resize_rh0
        if which == "e":
            rw = max(MIN_REL_W, min(1.0 - rx, self._resize_rw0 + dx))
        elif which == "w":
            rx = max(0.0, self._resize_rx0 + dx)
            rw = max(MIN_REL_W, self._resize_rx0 + self._resize_rw0 - rx)
            rx = self._resize_rx0 + self._resize_rw0 - rw
        elif which == "s":
            rh = max(MIN_REL_H, min(1.0 - ry, self._resize_rh0 + dy))
        elif which == "n":
            ry = max(0.0, self._resize_ry0 + dy)
            rh = max(MIN_REL_H, self._resize_ry0 + self._resize_rh0 - ry)
            ry = self._resize_ry0 + self._resize_rh0 - rh
        elif which == "se":
            rw = max(MIN_REL_W, min(1.0 - rx, self._resize_rw0 + dx))
            rh = max(MIN_REL_H, min(1.0 - ry, self._resize_rh0 + dy))
        elif which == "sw":
            rx = max(0.0, self._resize_rx0 + dx)
            rw = max(MIN_REL_W, self._resize_rx0 + self._resize_rw0 - rx)
            rx = self._resize_rx0 + self._resize_rw0 - rw
            rh = max(MIN_REL_H, min(1.0 - ry, self._resize_rh0 + dy))
        elif which == "ne":
            rw = max(MIN_REL_W, min(1.0 - rx, self._resize_rw0 + dx))
            ry = max(0.0, self._resize_ry0 + dy)
            rh = max(MIN_REL_H, self._resize_ry0 + self._resize_rh0 - ry)
            ry = self._resize_ry0 + self._resize_rh0 - rh
        elif which == "nw":
            rx = max(0.0, self._resize_rx0 + dx)
            rw = max(MIN_REL_W, self._resize_rx0 + self._resize_rw0 - rx)
            rx = self._resize_rx0 + self._resize_rw0 - rw
            ry = max(0.0, self._resize_ry0 + dy)
            rh = max(MIN_REL_H, self._resize_ry0 + self._resize_rh0 - ry)
            ry = self._resize_ry0 + self._resize_rh0 - rh
        # For resize, keep the user's directional intent (edge/corner) and only
        # apply snap + bounds. Relocation-based collision search can block valid
        # sideways/upward expansions when neighbors are only on other sides.
        rx, ry, rw, rh = self._host.snap_rect_bounds_only(
            self.sensor_id, rx, ry, rw, rh, resize=True
        )
        old_rect = (self._resize_rx0, self._resize_ry0, self._resize_rw0, self._resize_rh0)

        def _is_shrink(nrx, nry, nrw, nrh):
            old_area = old_rect[2] * old_rect[3]
            new_area = nrw * nrh
            strict_subset = (
                nrw <= old_rect[2] + 1e-9 and nrh <= old_rect[3] + 1e-9
                and nrx >= old_rect[0] - 1e-9 and nry >= old_rect[1] - 1e-9
                and nrx + nrw <= old_rect[0] + old_rect[2] + 1e-9
                and nry + nrh <= old_rect[1] + old_rect[3] + 1e-9
            )
            # Allow shrink by area even if one snapped edge jittered by a tiny step.
            return strict_subset or (new_area <= old_area - 1e-9)

        def _can_apply(nrx, nry, nrw, nrh):
            if _is_shrink(nrx, nry, nrw, nrh):
                return True
            return not self._host.rect_overlaps_any(self.sensor_id, (nrx, nry, nrw, nrh))

        # Primary candidate (full pointer intent).
        if _can_apply(rx, ry, rw, rh):
            self.place_configure(relx=rx, rely=ry, relwidth=rw, relheight=rh)
            return

        # If blocked, allow sliding by trying axis-isolated alternatives.
        ox, oy, ow, oh = old_rect
        candidates = []
        if which in ("se", "sw", "ne", "nw"):
            # Horizontal-only
            crx, cry, crw, crh = self._host.snap_rect_bounds_only(
                self.sensor_id, rx, oy, rw, oh, resize=True
            )
            candidates.append((crx, cry, crw, crh))
            # Vertical-only
            crx, cry, crw, crh = self._host.snap_rect_bounds_only(
                self.sensor_id, ox, ry, ow, rh, resize=True
            )
            candidates.append((crx, cry, crw, crh))

        for crx, cry, crw, crh in candidates:
            if _can_apply(crx, cry, crw, crh):
                self.place_configure(relx=crx, rely=cry, relwidth=crw, relheight=crh)
                return

    def _resize_edge_end(self, _event):
        self._is_dragging = False
        self._resize_edge = ""
        self._host.record_user_edit(self.sensor_id)

    # ?? Delete ?????????????????????????????????????????????????
    def _do_delete(self):
        if not self._host.is_editing_enabled():
            return
        if self._on_delete:
            self._on_delete(self.sensor_id)

    def get_bounds(self):
        """Return (relx, rely, relwidth, relheight) from current place()."""
        info = self.place_info()
        return (
            float(info.get("relx", 0)),
            float(info.get("rely", 0)),
            float(info.get("relwidth", 0.2)),
            float(info.get("relheight", 0.2)),
        )

    def destroy(self):
        self._cancel_hide()
        super().destroy()


# ??????????????????????????????????????????????????????????????
#  Host frame that owns all placed gauge tiles
# ??????????????????????????????????????????????????????????????
class GaugeHost(tk.Frame):
    """Container that manages `PlacedGaugeFrame` tiles."""

    def __init__(self, master, **kw):
        super().__init__(master, bg=BG, bd=0, highlightthickness=0, **kw)
        self._grid_canvas = tk.Canvas(self, bg=BG, bd=0, highlightthickness=0)
        self._grid_canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self._grid_canvas.bind("<Configure>", self._on_grid_resize)
        self.tk.call("lower", self._grid_canvas._w)
        self._tiles = {}  # sensor_id (str) -> PlacedGaugeFrame
        self._editing_enabled = True
        self._edit_priority = []  # most recent first

    def _on_grid_resize(self, event):
        self._draw_background_grid(event.width, event.height)

    def _draw_background_grid(self, w, h):
        self._grid_canvas.delete("grid")
        if w < 8 or h < 8:
            return
        cols = max(3, GRID_COLS)
        rows = max(3, GRID_ROWS)
        major_every = max(1, GRID_MAJOR_EVERY)
        sec_x = max(1, cols // 3)
        sec_y = max(1, rows // 3)

        # Vertical lines in normalized cell-space.
        for col in range(cols + 1):
            x = int(round((col / cols) * w))
            is_section = (col % sec_x == 0)
            if is_section:
                c = GRID_SECTION
                lw = 2
            elif col % major_every == 0:
                c = GRID_MAJOR
                lw = 1
            else:
                c = GRID_MINOR
                lw = 1
            self._grid_canvas.create_line(x, 0, x, h, fill=c, width=lw, tags="grid")

        # Horizontal lines in normalized cell-space.
        for row in range(rows + 1):
            y = int(round((row / rows) * h))
            is_section = (row % sec_y == 0)
            if is_section:
                c = GRID_SECTION
                lw = 2
            elif row % major_every == 0:
                c = GRID_MAJOR
                lw = 1
            else:
                c = GRID_MINOR
                lw = 1
            self._grid_canvas.create_line(0, y, w, y, fill=c, width=lw, tags="grid")

    def is_editing_enabled(self):
        return self._editing_enabled

    def set_editing_enabled(self, enabled: bool):
        self._editing_enabled = bool(enabled)
        if not self._editing_enabled:
            for tile in self._tiles.values():
                tile._cancel_hide()
                tile._hide_chrome()

    def clear(self):
        for tile in list(self._tiles.values()):
            tile.place_forget()
            tile.destroy()
        self._tiles.clear()
        self._edit_priority.clear()

    def record_user_edit(self, sensor_id):
        """Mark a gauge as recently edited (move/resize), highest priority first."""
        if sensor_id in self._edit_priority:
            self._edit_priority.remove(sensor_id)
        self._edit_priority.insert(0, sensor_id)

    def add_tile(self, sensor_id, kind, relx, rely, relwidth, relheight,
                 on_delete=None):
        if sensor_id in self._tiles:
            self.remove_tile(sensor_id)
        tile = PlacedGaugeFrame(self, sensor_id, kind, on_delete=on_delete)
        # Keep authored/default layouts reversible: snap to grid without
        # relocation side-effects during initial/profile placement.
        relx, rely, relwidth, relheight = self.snap_rect_bounds_only(
            sensor_id, relx, rely, relwidth, relheight, resize=True
        )
        tile.place(relx=relx, rely=rely, relwidth=relwidth, relheight=relheight)
        self._tiles[sensor_id] = tile
        if sensor_id in self._edit_priority:
            self._edit_priority.remove(sensor_id)
        self._edit_priority.append(sensor_id)
        return tile

    def remove_tile(self, sensor_id):
        tile = self._tiles.pop(sensor_id, None)
        if tile:
            tile.place_forget()
            tile.destroy()
        if sensor_id in self._edit_priority:
            self._edit_priority.remove(sensor_id)

    def placed_sensor_ids(self):
        return set(self._tiles.keys())

    def bring_tile_to_front(self, tile):
        """Raise *tile* above sibling `place()`d gauges on this host."""
        if self._tiles.get(tile.sensor_id) is not tile:
            return
        tile.lift()

    def fit_grid_layout(self, pad=0.01, target_rects=None, iterations=None):
        """Snap every tile to the visible canvas grid."""
        return self.fit_intelligent_layout(pad=pad, target_rects=target_rects, iterations=iterations)

    def _grid_unit_rel(self):
        hw = self.winfo_width()
        hh = self.winfo_height()
        # During first startup the host can still be unrealized (1x1-ish).
        # In that phase we should not snap yet or tiles collapse to minimum sizes.
        if hw < 40 or hh < 40:
            return None, None
        return 1.0 / max(1, GRID_COLS), 1.0 / max(1, GRID_ROWS)

    def _snap_value(self, v, unit):
        if unit <= 1e-9:
            return v
        return round(v / unit) * unit

    def _snap_rect_to_grid(self, relx, rely, relwidth, relheight, resize=False):
        ux, uy = self._grid_unit_rel()
        if ux is None or uy is None:
            rw = _clamp(float(relwidth), MIN_REL_W, 1.0)
            rh = _clamp(float(relheight), MIN_REL_H, 1.0)
            rx = _clamp(float(relx), 0.0, max(0.0, 1.0 - rw))
            ry = _clamp(float(rely), 0.0, max(0.0, 1.0 - rh))
            return rx, ry, rw, rh
        rw = max(MIN_REL_W, self._snap_value(relwidth, ux))
        rh = max(MIN_REL_H, self._snap_value(relheight, uy))
        if resize:
            rx = self._snap_value(relx, ux)
            ry = self._snap_value(rely, uy)
        else:
            rx = self._snap_value(relx, ux)
            ry = self._snap_value(rely, uy)
        rx = _clamp(rx, 0.0, max(0.0, 1.0 - rw))
        ry = _clamp(ry, 0.0, max(0.0, 1.0 - rh))
        return rx, ry, rw, rh

    def _other_tile_rects(self, sensor_id):
        rects = []
        for idx, tile in self._tiles.items():
            if idx == sensor_id:
                continue
            rects.append(tile.get_bounds())
        return rects

    def clamp_rect_no_overlap(self, sensor_id, relx, rely, relwidth, relheight, step=0.004):
        """Clamp rect to host bounds and avoid overlaps by nearest free scan."""
        ux, uy = self._grid_unit_rel()
        if ux is None or uy is None:
            rw = _clamp(float(relwidth), MIN_REL_W, 1.0)
            rh = _clamp(float(relheight), MIN_REL_H, 1.0)
            rx = _clamp(float(relx), 0.0, 1.0 - rw)
            ry = _clamp(float(rely), 0.0, 1.0 - rh)
        else:
            rw = max(MIN_REL_W, self._snap_value(float(relwidth), ux))
            rh = max(MIN_REL_H, self._snap_value(float(relheight), uy))
            rw = _clamp(rw, MIN_REL_W, 1.0)
            rh = _clamp(rh, MIN_REL_H, 1.0)
            rx = _clamp(self._snap_value(float(relx), ux), 0.0, max(0.0, 1.0 - rw))
            ry = _clamp(self._snap_value(float(rely), uy), 0.0, max(0.0, 1.0 - rh))
        cand = (rx, ry, rw, rh)
        occupied = self._other_tile_rects(sensor_id)

        # When snapping is active, do collision checks in integer grid cells so
        # touching edges are consistently allowed (prevents random 1-cell gaps).
        step_x = ux if ux is not None else step
        step_y = uy if uy is not None else step
        x_max = max(0.0, 1.0 - rw)
        y_max = max(0.0, 1.0 - rh)
        nx = max(0, int(round(x_max / max(step_x, 1e-9))))
        ny = max(0, int(round(y_max / max(step_y, 1e-9))))
        w_cells = max(1, int(round(rw / max(step_x, 1e-9))))
        h_cells = max(1, int(round(rh / max(step_y, 1e-9))))
        cx = int(round(rx / max(step_x, 1e-9)))
        cy = int(round(ry / max(step_y, 1e-9)))
        cx = max(0, min(nx, cx))
        cy = max(0, min(ny, cy))

        occ_cells = []
        for ox, oy, ow, oh in occupied:
            gx = int(round(ox / max(step_x, 1e-9)))
            gy = int(round(oy / max(step_y, 1e-9)))
            gw = max(1, int(round(ow / max(step_x, 1e-9))))
            gh = max(1, int(round(oh / max(step_y, 1e-9))))
            occ_cells.append((gx, gy, gw, gh))

        def _cells_overlap(a, b):
            ax, ay, aw, ah = a
            bx, by, bw, bh = b
            return not (
                ax + aw <= bx
                or bx + bw <= ax
                or ay + ah <= by
                or by + bh <= ay
            )

        def _is_free(gx, gy):
            test = (gx, gy, w_cells, h_cells)
            return not any(_cells_overlap(test, rr) for rr in occ_cells)

        if _is_free(cx, cy):
            return (cx * step_x, cy * step_y, w_cells * step_x, h_cells * step_y)

        best = None
        best_cost = None
        max_r = max(nx, ny)
        for r in range(max_r + 1):
            y0 = max(0, cy - r)
            y1 = min(ny, cy + r)
            x0 = max(0, cx - r)
            x1 = min(nx, cx + r)
            for gy in range(y0, y1 + 1):
                for gx in range(x0, x1 + 1):
                    if max(abs(gx - cx), abs(gy - cy)) != r:
                        continue
                    if not _is_free(gx, gy):
                        continue
                    cost = abs(gx - cx) + abs(gy - cy)
                    if best is None or cost < best_cost:
                        best = (gx, gy)
                        best_cost = cost
                if best is not None:
                    break
            if best is not None:
                break
        if best is None:
            return (cx * step_x, cy * step_y, w_cells * step_x, h_cells * step_y)
        return (best[0] * step_x, best[1] * step_y, w_cells * step_x, h_cells * step_y)

    def fit_intelligent_layout(self, pad=0.01, target_rects=None, iterations=None):
        """Legacy name; now performs grid snap fit for all gauges."""
        if not self._tiles:
            return target_rects or {}
        ux, uy = self._grid_unit_rel()
        if ux is None or uy is None:
            self.after(20, self.fit_grid_layout)
            return target_rects or {}
        out = {}
        for idx in sorted(self._tiles):
            rx, ry, rw, rh = self._tiles[idx].get_bounds()
            rx, ry, rw, rh = self.snap_rect_bounds_only(idx, rx, ry, rw, rh, resize=True)
            self._tiles[idx].place_configure(
                relx=rx,
                rely=ry,
                relwidth=rw,
                relheight=rh,
            )
            out[idx] = {"cx": rx + rw * 0.5, "cy": ry + rh * 0.5, "w": rw, "h": rh}
        return out

    def snap_and_clamp_rect(self, sensor_id, relx, rely, relwidth, relheight, resize=False):
        rx, ry, rw, rh = self._snap_rect_to_grid(relx, rely, relwidth, relheight, resize=resize)
        return self.clamp_rect_no_overlap(sensor_id, rx, ry, rw, rh)

    def snap_rect_bounds_only(self, sensor_id, relx, rely, relwidth, relheight, resize=False):
        _ = sensor_id
        rx, ry, rw, rh = self._snap_rect_to_grid(relx, rely, relwidth, relheight, resize=resize)
        rx = _clamp(rx, 0.0, max(0.0, 1.0 - rw))
        ry = _clamp(ry, 0.0, max(0.0, 1.0 - rh))
        return rx, ry, rw, rh

    def rect_overlaps_any(self, sensor_id, rect):
        ux, uy = self._grid_unit_rel()
        others = self._other_tile_rects(sensor_id)
        # When grid is active, check overlap in integer cell-space so exact edge
        # alignment is always treated as flush (non-overlap).
        if ux is not None and uy is not None:
            rx, ry, rw, rh = rect
            ax0 = int(round(rx / max(ux, 1e-9)))
            ay0 = int(round(ry / max(uy, 1e-9)))
            ax1 = int(round((rx + rw) / max(ux, 1e-9)))
            ay1 = int(round((ry + rh) / max(uy, 1e-9)))
            if ax1 <= ax0:
                ax1 = ax0 + 1
            if ay1 <= ay0:
                ay1 = ay0 + 1
            for ox, oy, ow, oh in others:
                bx0 = int(round(ox / max(ux, 1e-9)))
                by0 = int(round(oy / max(uy, 1e-9)))
                bx1 = int(round((ox + ow) / max(ux, 1e-9)))
                by1 = int(round((oy + oh) / max(uy, 1e-9)))
                if bx1 <= bx0:
                    bx1 = bx0 + 1
                if by1 <= by0:
                    by1 = by0 + 1
                if not (
                    ax1 <= bx0
                    or bx1 <= ax0
                    or ay1 <= by0
                    or by1 <= ay0
                ):
                    return True
            return False
        return any(_rects_overlap(rect, other, eps=1e-6) for other in others)

    def grow_tiles_to_fill_space(self, max_rounds=8):
        """Zoom the whole gauge cluster to fill canvas while keeping orientation."""
        if not self._tiles:
            return 0
        if self._grid_unit_rel()[0] is None:
            self.after_idle(self.grow_tiles_to_fill_space)
            return 0

        keys = sorted(self._tiles.keys())
        rects = {idx: self._tiles[idx].get_bounds() for idx in keys}

        min_x = min(r[0] for r in rects.values())
        min_y = min(r[1] for r in rects.values())
        max_x = max(r[0] + r[2] for r in rects.values())
        max_y = max(r[1] + r[3] for r in rects.values())
        bw = max(1e-9, max_x - min_x)
        bh = max(1e-9, max_y - min_y)
        # Fit to canvas preserving global cluster orientation and per-gauge aspect.
        s = min(1.0 / bw, 1.0 / bh)
        if s <= 1.0005:
            return 0

        # Apply same affine transform to every gauge.
        scaled = {}
        for idx in keys:
            rx, ry, rw, rh = rects[idx]
            nrx = (rx - min_x) * s
            nry = (ry - min_y) * s
            nrw = rw * s
            nrh = rh * s
            scaled[idx] = [nrx, nry, nrw, nrh]

        # Keep inside canvas exactly and preserve relative orientation by common shift.
        min_x2 = min(r[0] for r in scaled.values())
        min_y2 = min(r[1] for r in scaled.values())
        max_x2 = max(r[0] + r[2] for r in scaled.values())
        max_y2 = max(r[1] + r[3] for r in scaled.values())
        shift_x = -min_x2 if min_x2 < 0 else 0.0
        shift_y = -min_y2 if min_y2 < 0 else 0.0
        if max_x2 + shift_x > 1.0:
            shift_x -= (max_x2 + shift_x - 1.0)
        if max_y2 + shift_y > 1.0:
            shift_y -= (max_y2 + shift_y - 1.0)

        updates = 0
        for idx in keys:
            nrx, nry, nrw, nrh = scaled[idx]
            nrx += shift_x
            nry += shift_y
            nrx, nry, nrw, nrh = self.snap_rect_bounds_only(
                idx, nrx, nry, nrw, nrh, resize=True
            )
            self._tiles[idx].place_configure(
                relx=nrx,
                rely=nry,
                relwidth=nrw,
                relheight=nrh,
            )
            updates += 1
        return updates

    def suggest_new_tile_rect(self, new_sensor_id, kind, pad=0.01):
        """Return (relx, rely, relwidth, relheight) for a new tile without moving
        existing ones."""
        _ = (new_sensor_id, kind, pad)
        cols = max(3, GRID_COLS)
        rows = max(3, GRID_ROWS)
        occ = [[False for _ in range(cols)] for _ in range(rows)]

        # Mark occupied cells from existing tiles using edge indices.
        for idx in sorted(self._tiles.keys()):
            rx, ry, rw, rh = self._tiles[idx].get_bounds()
            x0 = max(0, min(cols - 1, int(round(rx * cols))))
            y0 = max(0, min(rows - 1, int(round(ry * rows))))
            x1 = max(x0 + 1, min(cols, int(round((rx + rw) * cols))))
            y1 = max(y0 + 1, min(rows, int(round((ry + rh) * rows))))
            for y in range(y0, y1):
                for x in range(x0, x1):
                    occ[y][x] = True

        # Largest free square (maximal square DP).
        dp = [[0 for _ in range(cols)] for _ in range(rows)]
        best_size = 0
        best_br = (0, 0)
        for y in range(rows):
            for x in range(cols):
                if occ[y][x]:
                    dp[y][x] = 0
                    continue
                if x == 0 or y == 0:
                    dp[y][x] = 1
                else:
                    dp[y][x] = 1 + min(dp[y - 1][x], dp[y][x - 1], dp[y - 1][x - 1])
                if dp[y][x] > best_size:
                    best_size = dp[y][x]
                    best_br = (x, y)

        min_side = max(1, int(math.ceil(max(MIN_REL_W * cols, MIN_REL_H * rows))))
        if best_size >= min_side:
            x1, y1 = best_br
            side = best_size
            x0 = x1 - side + 1
            y0 = y1 - side + 1
            return (x0 / cols, y0 / rows, side / cols, side / rows)

        # Fallback: first free minimum footprint if no square can fit minimum size.
        min_w = max(1, int(math.ceil(MIN_REL_W * cols)))
        min_h = max(1, int(math.ceil(MIN_REL_H * rows)))
        for y0 in range(0, rows - min_h + 1):
            for x0 in range(0, cols - min_w + 1):
                blocked = False
                for yy in range(y0, y0 + min_h):
                    for xx in range(x0, x0 + min_w):
                        if occ[yy][xx]:
                            blocked = True
                            break
                    if blocked:
                        break
                if not blocked:
                    return (x0 / cols, y0 / rows, min_w / cols, min_h / rows)
        return (0.0, 0.0, min_w / cols, min_h / rows)

    def get_profile(self):
        """Read back the current layout as a profile dict."""
        gauges = []
        for idx in sorted(self._tiles):
            tile = self._tiles[idx]
            rx, ry, rw, rh = tile.get_bounds()
            gauges.append({
                "sensor_id": idx,
                "kind": tile.kind,
                "relx": round(rx, 4),
                "rely": round(ry, 4),
                "relwidth": round(rw, 4),
                "relheight": round(rh, 4),
            })
        return {"version": 1, "gauges": gauges}

    def get_gauge(self, sensor_id):
        tile = self._tiles.get(sensor_id)
        return tile.gauge if tile else None
