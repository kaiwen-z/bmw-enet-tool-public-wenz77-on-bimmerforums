#!/usr/bin/env python3
"""
BMW Sensor Log Plotter
Interactive time-series viewer for BMW ENET dashboard CSV logs.

Usage:
    python plot_bmw_log.py <csv_file>
    python plot_bmw_log.py              (opens file picker)
    python -m src.bmw_enet_tool.log_viewer <csv_file>
    python -m src.bmw_enet_tool.log_viewer   (opens file picker)

Controls:
    - Click sensor rows in the left panel to show/hide lines
    - Scroll wheel over the plot to zoom in/out
    - Click-drag on the plot to pan left/right
    - Drag the bottom slider to pan through time
    - Mode buttons (top-right): Raw, Min-Max %, Z-Score, Dual Y
"""

import sys, os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.rcParams["toolbar"] = "None"
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.widgets import Slider, Button
from matplotlib.patches import Rectangle
from matplotlib.legend_handler import HandlerPatch

BG       = "#0a0c10"
PANEL    = "#0f1219"
BORDER   = "#1c2030"
GAUGE_BG = "#070910"
ACCENT   = "#1e90d8"
LABEL_C  = "#c8d8ec"
DIM      = "#8898b8"
TEXT     = "#d8e4f0"
GRID_C   = "#2a3050"
DISABLED_BG = "#0a0d12"
DISABLED_FG = "#404858"

GOLDEN_ANGLE = 137.508
MODES = ["Raw", "Min-Max %", "Z-Score", "Dual Y"]

SIDE_FONT = ("Segoe UI", 8)
SIDE_ROW_H = 0.032
SIDE_ROW_GAP = 0.002
SIDE_PAD = 0.012
SWATCH_SZ = 0.008


def generate_colors(n):
    import colorsys
    colors = []
    for i in range(n):
        hue = (i * GOLDEN_ANGLE / 360.0) % 1.0
        sat = 0.65 + 0.15 * ((i % 3) / 2.0)
        val = 0.90 + 0.10 * ((i % 2) / 1.0)
        r, g, b = colorsys.hsv_to_rgb(hue, sat, val)
        colors.append(f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}")
    return colors


def pick_file():
    import tkinter as tk
    from tkinter import filedialog
    try:
        from .paths import application_base_dir
        start_dir = application_base_dir()
    except ImportError:
        start_dir = os.path.dirname(os.path.abspath(__file__))
    root = tk.Tk()
    root.withdraw()
    path = filedialog.askopenfilename(
        title="Select BMW Sensor Log",
        initialdir=start_dir,
        filetypes=[("Log files", "*.jsonl *.csv"), ("All files", "*.*")],
    )
    root.destroy()
    return path


def _load_jsonl(filepath):
    """Parse a JSONL log into a DataFrame with a ``datetime`` column and
    one column per sensor using ``label (unit)`` naming for compatibility
    with the existing plot code."""
    import json
    rows = []
    sensor_meta = {}  # sensor_id -> {label, unit}
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue
            if entry.get("type") == "header":
                for info in entry.get("sensors", []):
                    sensor_meta[info["sensor_id"]] = info
                continue
            ts = entry.get("ts", "")
            readings = entry.get("d", {})
            row = {"datetime": ts}
            for sid, val in readings.items():
                meta = sensor_meta.get(sid, {})
                col = f"{meta.get('label', sid)} ({meta.get('unit', '?')})"
                row[col] = val
            rows.append(row)
    df = pd.DataFrame(rows)
    if "datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    return df


def _load_csv(filepath):
    """Load a legacy CSV log into a DataFrame."""
    return pd.read_csv(filepath, parse_dates=["datetime"], encoding="latin-1")


def _load_log(filepath):
    """Auto-detect format and return a DataFrame."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".jsonl":
        return _load_jsonl(filepath)
    if ext == ".csv":
        return _load_csv(filepath)
    # Sniff first non-empty line
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.strip():
                if line.strip().startswith("{"):
                    return _load_jsonl(filepath)
                break
    return _load_csv(filepath)


def main(filepath=None, replay_idx=None):
    if filepath is None:
        filepath = sys.argv[1] if len(sys.argv) > 1 else pick_file()
    if not filepath:
        sys.exit(0)

    df = _load_log(filepath)
    sensor_cols = [c for c in df.columns if c != "datetime"]
    df[sensor_cols] = df[sensor_cols].apply(pd.to_numeric, errors="coerce").fillna(0)
    if not sensor_cols:
        print("No sensor columns found in the log.")
        sys.exit(1)

    n_sensors = len(sensor_cols)
    times = mdates.date2num(df["datetime"].values)
    n_pts = len(times)
    full_xmin, full_xmax = times[0], times[-1]
    full_span = full_xmax - full_xmin
    raw_data = [df[col].values.astype(float) for col in sensor_cols]

    # Zoom limits
    min_visible_pts = min(40, n_pts)
    min_span = (times[min_visible_pts] - times[0]) if n_pts > min_visible_pts else full_span
    min_span = max(min_span, 1.0 / 86400.0)
    max_zoom = full_span / min_span if min_span > 0 else 1.0

    # Dual-Y grouping: split by data range — larger ranges left, smaller right
    data_ranges = []
    for d in raw_data:
        finite = d[np.isfinite(d)]
        data_ranges.append(np.ptp(finite) if len(finite) else 0.0)
    sorted_r = sorted(data_ranges)
    threshold = sorted_r[len(sorted_r) // 2] if sorted_r else 0.0
    group_right = {i for i, r in enumerate(data_ranges) if r <= threshold}
    if len(group_right) == 0 and n_sensors > 1:
        group_right.add(data_ranges.index(min(data_ranges)))
    if len(group_right) == n_sensors and n_sensors > 1:
        group_right.discard(data_ranges.index(max(data_ranges)))

    state = {"zoom": 1.0, "pos": 0.0, "mode": "Min-Max %"}
    disabled = set()
    colors = generate_colors(n_sensors)

    # --- Measure sidebar width from longest sensor name ---
    short_names = [c.split("(")[0].strip() for c in sensor_cols]
    fig_tmp = plt.figure(figsize=(16, 8))
    renderer = fig_tmp.canvas.get_renderer()
    max_tw = 0.0
    for name in short_names:
        t = fig_tmp.text(0, 0, name, fontsize=SIDE_FONT[1], family=SIDE_FONT[0])
        bb = t.get_window_extent(renderer=renderer)
        tw = bb.width / (fig_tmp.get_size_inches()[0] * fig_tmp.dpi)
        if tw > max_tw:
            max_tw = tw
        t.remove()
    plt.close(fig_tmp)

    SIDE_W = SIDE_PAD * 2 + SWATCH_SZ + 0.008 + max_tw + 0.01
    SIDE_W = max(SIDE_W, 0.10)
    PLOT_L = SIDE_W + 0.015

    # --- Figure + layout ---
    fig, ax = plt.subplots(figsize=(16, 8))
    fig.canvas.manager.set_window_title(
        f"Log Viewer — {os.path.basename(filepath)}")
    plt.subplots_adjust(bottom=0.16, top=0.91, left=PLOT_L, right=0.90)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(PANEL)
    ax.set_title(os.path.basename(filepath), fontsize=10, color=DIM, pad=8)
    ax.set_ylabel("Value", fontsize=9, color=LABEL_C)
    ax.grid(True, alpha=0.5, linewidth=0.5, color=GRID_C)
    ax.tick_params(labelsize=8, colors=DIM)
    for spine in ax.spines.values():
        spine.set_color(BORDER)

    # --- Sidebar background + divider ---
    side_bg = fig.add_axes([0, 0, SIDE_W, 1], facecolor=PANEL)
    side_bg.set_xticks([])
    side_bg.set_yticks([])
    for s in side_bg.spines.values():
        s.set_visible(False)
    side_bg.set_navigate(False)
    side_bg.set_zorder(-1)

    divider = fig.add_axes([SIDE_W, 0, 0.0015, 1], facecolor=BORDER)
    divider.set_xticks([])
    divider.set_yticks([])
    for s in divider.spines.values():
        s.set_visible(False)
    divider.set_navigate(False)
    divider.set_zorder(-1)

    # List frame with title
    toggle_row_total = SIDE_ROW_H + SIDE_ROW_GAP * 5
    list_h = toggle_row_total + n_sensors * (SIDE_ROW_H + SIDE_ROW_GAP) + SIDE_ROW_GAP
    list_top_y = 0.94
    list_bot_y = list_top_y - list_h - 0.01

    fig.text(SIDE_W / 2, list_top_y + 0.012, "SENSORS",
             fontsize=8, fontweight="bold", color=DIM,
             family="Segoe UI", ha="center", va="bottom")

    list_border = fig.add_axes(
        [SIDE_PAD / 2, list_bot_y, SIDE_W - SIDE_PAD, list_top_y - list_bot_y],
        facecolor="none")
    list_border.set_xticks([])
    list_border.set_yticks([])
    for s in list_border.spines.values():
        s.set_color("#2a3050")
        s.set_linewidth(1)
    list_border.patch.set_visible(False)
    list_border.set_navigate(False)
    list_border.set_zorder(0)

    # Secondary Y-axis (hidden until Dual Y mode)
    ax2 = ax.twinx()
    ax2.set_visible(False)
    ax2.tick_params(labelsize=8, colors=DIM)
    for spine in ax2.spines.values():
        spine.set_color(BORDER)

    # --- Plot lines on both axes ---
    plot_lines = []
    plot_lines2 = []
    for i in range(n_sensors):
        line, = ax.plot(times, raw_data[i], linewidth=1.3,
                        color=colors[i], alpha=0.9)
        line2, = ax2.plot(times, raw_data[i], linewidth=1.3,
                          color=colors[i], alpha=0.9, visible=False)
        plot_lines.append(line)
        plot_lines2.append(line2)

    # --- Timestamp formatter ---
    class TruncMicrosFormatter(matplotlib.ticker.Formatter):
        def __call__(self, x, pos=None):
            dt = mdates.num2date(x)
            return dt.strftime("%H:%M:%S") + f".{dt.microsecond // 10000:02d}"

    ax.xaxis.set_major_formatter(TruncMicrosFormatter())
    ax.tick_params(axis="x", rotation=0)

    class AdaptiveDateLocator(matplotlib.ticker.Locator):
        """Places ticks based on available pixel width so labels never overlap."""
        LABEL_PX = 90

        def __call__(self):
            vmin, vmax = self.axis.get_view_interval()
            if vmax <= vmin:
                return [vmin]
            ax_w = self.axis.axes.get_window_extent().width
            n_ticks = max(2, int(ax_w / self.LABEL_PX))
            return np.linspace(vmin, vmax, n_ticks).tolist()

    ax.xaxis.set_major_locator(AdaptiveDateLocator())

    # --- Visibility helpers ---
    def update_line_visibility():
        for i in range(n_sensors):
            if i in disabled:
                plot_lines[i].set_visible(False)
                plot_lines2[i].set_visible(False)
            elif state["mode"] == "Dual Y":
                plot_lines[i].set_visible(i not in group_right)
                plot_lines2[i].set_visible(i in group_right)
            else:
                plot_lines[i].set_visible(True)
                plot_lines2[i].set_visible(False)

    # --- Sidebar sensor rows ---
    sensor_btns = []
    row_x = SIDE_PAD
    row_w = SIDE_W - SIDE_PAD * 2

    # Swatch position as fraction of row width
    sw_frac = SWATCH_SZ / row_w
    text_start = (SWATCH_SZ + 0.006) / row_w

    def _update_sidebar():
        for i, (btn, swatch) in enumerate(sensor_btns):
            if i in disabled:
                btn.label.set_color(DISABLED_FG)
                swatch.set_alpha(0.2)
                btn.ax.set_facecolor(DISABLED_BG)
                btn.color = DISABLED_BG
                btn.hovercolor = "#10131a"
            else:
                btn.label.set_color(TEXT)
                swatch.set_alpha(1.0)
                btn.ax.set_facecolor(PANEL)
                btn.color = PANEL
                btn.hovercolor = "#1a2030"

    def toggle_sensor(idx):
        if idx in disabled:
            disabled.discard(idx)
        else:
            disabled.add(idx)
        update_line_visibility()
        _update_sidebar()
        rescale_y()
        fig.canvas.draw_idle()

    sensor_start_y = list_top_y - toggle_row_total
    toggle_btn_y = list_top_y - SIDE_ROW_H - SIDE_ROW_GAP * 3
    toggle_btn_w = (row_w - 0.005) / 2

    def all_sensors_off(_):
        disabled.update(range(n_sensors))
        update_line_visibility()
        _update_sidebar()
        rescale_y()
        fig.canvas.draw_idle()

    def all_sensors_on(_):
        disabled.clear()
        update_line_visibility()
        _update_sidebar()
        rescale_y()
        fig.canvas.draw_idle()

    off_ax = fig.add_axes([row_x, toggle_btn_y, toggle_btn_w, SIDE_ROW_H])
    off_ax.set_navigate(False)
    for s in off_ax.spines.values():
        s.set_visible(False)
    off_btn = Button(off_ax, "All Off", color=BORDER, hovercolor="#2a3050")
    off_btn.label.set_color(DIM)
    off_btn.label.set_fontsize(7)
    off_btn.label.set_family(SIDE_FONT[0])
    off_btn.on_clicked(all_sensors_off)

    on_ax = fig.add_axes([row_x + toggle_btn_w + 0.005, toggle_btn_y,
                          toggle_btn_w, SIDE_ROW_H])
    on_ax.set_navigate(False)
    for s in on_ax.spines.values():
        s.set_visible(False)
    on_btn = Button(on_ax, "All On", color=BORDER, hovercolor="#2a3050")
    on_btn.label.set_color(DIM)
    on_btn.label.set_fontsize(7)
    on_btn.label.set_family(SIDE_FONT[0])
    on_btn.on_clicked(all_sensors_on)

    for i in range(n_sensors):
        y = sensor_start_y - (i + 1) * (SIDE_ROW_H + SIDE_ROW_GAP)
        bax = fig.add_axes([row_x, y, row_w, SIDE_ROW_H])
        bax.set_navigate(False)
        for s in bax.spines.values():
            s.set_visible(False)

        swatch = bax.add_patch(Rectangle(
            (0.02, 0.2), sw_frac, 0.6,
            transform=bax.transAxes,
            facecolor=colors[i], edgecolor="none", zorder=3))

        btn = Button(bax, short_names[i], color=PANEL, hovercolor="#1a2030")
        btn.label.set_color(TEXT)
        btn.label.set_fontsize(SIDE_FONT[1])
        btn.label.set_family(SIDE_FONT[0])
        btn.label.set_ha("left")
        btn.label.set_position((text_start + 0.02, 0.5))
        btn.on_clicked(lambda _, idx=i: toggle_sensor(idx))
        sensor_btns.append((btn, swatch))

    # --- Y-axis rescaling ---
    def rescale_y():
        xmin, xmax = ax.get_xlim()
        mask = (times >= xmin) & (times <= xmax)

        if state["mode"] == "Dual Y":
            for target_ax, lines in [(ax, plot_lines), (ax2, plot_lines2)]:
                segs = []
                for line in lines:
                    if not line.get_visible():
                        continue
                    yd = line.get_ydata()[mask]
                    yd = yd[np.isfinite(yd)]
                    if len(yd):
                        segs.append(yd)
                if segs:
                    all_y = np.concatenate(segs)
                    ylo, yhi = all_y.min(), all_y.max()
                    margin = (yhi - ylo) * 0.08 if yhi != ylo else 1.0
                    target_ax.set_ylim(ylo - margin, yhi + margin)
        else:
            segs = []
            for line in plot_lines:
                if not line.get_visible():
                    continue
                yd = line.get_ydata()[mask]
                yd = yd[np.isfinite(yd)]
                if len(yd):
                    segs.append(yd)
            if segs:
                all_y = np.concatenate(segs)
                ylo, yhi = all_y.min(), all_y.max()
                margin = (yhi - ylo) * 0.08 if yhi != ylo else 1.0
                ax.set_ylim(ylo - margin, yhi + margin)

    # --- Apply view (pan / zoom) ---
    def apply_view():
        span = full_span / state["zoom"]
        pannable = full_span - span
        left = full_xmin + state["pos"] * pannable if pannable > 0 else full_xmin
        ax.set_xlim(left, left + span)
        rescale_y()
        fig.canvas.draw_idle()

    # --- Mode switching ---
    def switch_mode(new_mode):
        state["mode"] = new_mode

        if new_mode == "Dual Y":
            ax2.set_visible(True)
            ax.set_ylabel("Value (left)", fontsize=9, color=LABEL_C)
            ax2.set_ylabel("Value (right)", fontsize=9, color=LABEL_C)
            for i in range(n_sensors):
                plot_lines[i].set_ydata(raw_data[i])
                plot_lines2[i].set_ydata(raw_data[i])
        else:
            ax2.set_visible(False)
            if new_mode == "Raw":
                ax.set_ylabel("Value", fontsize=9, color=LABEL_C)
                for i in range(n_sensors):
                    plot_lines[i].set_ydata(raw_data[i])
            elif new_mode == "Min-Max %":
                ax.set_ylabel("% of Range", fontsize=9, color=LABEL_C)
                for i in range(n_sensors):
                    d = raw_data[i]
                    lo, hi = np.nanmin(d), np.nanmax(d)
                    if hi > lo:
                        plot_lines[i].set_ydata((d - lo) / (hi - lo) * 100.0)
                    else:
                        plot_lines[i].set_ydata(np.zeros_like(d))
            elif new_mode == "Z-Score":
                ax.set_ylabel("\u03c3 from mean", fontsize=9, color=LABEL_C)
                for i in range(n_sensors):
                    d = raw_data[i]
                    mu, sigma = np.nanmean(d), np.nanstd(d)
                    if sigma > 0:
                        plot_lines[i].set_ydata((d - mu) / sigma)
                    else:
                        plot_lines[i].set_ydata(np.zeros_like(d))

        update_line_visibility()
        update_btn_styles()
        apply_view()

    # --- Mode button bar ---
    mode_btns = []
    btn_w, btn_h = 0.095, 0.032
    start_x = 0.56
    btn_y = 0.948

    def update_btn_styles():
        for btn, mode in zip(mode_btns, MODES):
            if mode == state["mode"]:
                btn.ax.set_facecolor(ACCENT)
                btn.color = ACCENT
                btn.hovercolor = ACCENT
                btn.label.set_color("white")
            else:
                btn.ax.set_facecolor(BORDER)
                btn.color = BORDER
                btn.hovercolor = "#2a3050"
                btn.label.set_color(DIM)

    for j, mode in enumerate(MODES):
        bax = fig.add_axes([start_x + j * (btn_w + 0.008), btn_y, btn_w, btn_h])
        bax.set_facecolor(BORDER)
        btn = Button(bax, mode, color=BORDER, hovercolor="#2a3050")
        btn.label.set_color(DIM)
        btn.label.set_fontsize(7)
        btn.on_clicked(lambda _, m=mode: switch_mode(m))
        mode_btns.append(btn)

    update_btn_styles()

    # --- Scroll zoom ---
    def on_scroll(event):
        if event.inaxes not in (ax, ax2) or event.xdata is None:
            return
        zoom_factor = 1.3
        if event.button == "up":
            new_zoom = min(state["zoom"] * zoom_factor, max_zoom)
        else:
            new_zoom = max(state["zoom"] / zoom_factor, 1.0)

        xmin, xmax = ax.get_xlim()
        old_span = xmax - xmin
        new_span = full_span / new_zoom
        cursor_frac = (event.xdata - xmin) / old_span if old_span > 0 else 0.5
        new_left = event.xdata - cursor_frac * new_span
        new_left = max(full_xmin, min(new_left, full_xmax - new_span))

        state["zoom"] = new_zoom
        pannable = full_span - new_span
        state["pos"] = max(0.0, min(1.0,
            (new_left - full_xmin) / pannable if pannable > 0 else 0.0))
        zoom_slider.eventson = False
        zoom_slider.set_val(new_zoom)
        zoom_slider.eventson = True
        slider.set_val(state["pos"])

    fig.canvas.mpl_connect("scroll_event", on_scroll)

    # --- Pan slider ---
    slider_ax = fig.add_axes([PLOT_L, 0.03, 0.90 - PLOT_L, 0.04])
    slider_ax.set_facecolor(GAUGE_BG)
    slider = Slider(slider_ax, "", 0.0, 1.0, valinit=0.0,
                    color=ACCENT, track_color=BORDER,
                    handle_style={"facecolor": ACCENT, "edgecolor": TEXT, "size": 14})
    slider.valtext.set_visible(False)

    def on_slider(val):
        state["pos"] = val
        apply_view()

    slider.on_changed(on_slider)

    # --- Vertical zoom slider (right side) ---
    zoom_label_top = fig.text(0.955, 0.92, "ZOOM", fontsize=7, color=DIM,
                              fontweight="bold", family="Segoe UI",
                              ha="center", va="bottom")
    zoom_label_max = fig.text(0.955, 0.895, f"{max_zoom:.0f}x", fontsize=6,
                              color=DIM, family="Courier New", ha="center")
    zoom_label_min = fig.text(0.955, 0.145, "1x", fontsize=6,
                              color=DIM, family="Courier New", ha="center")

    zoom_slider_ax = fig.add_axes([0.935, 0.16, 0.04, 0.73],
                                  facecolor=GAUGE_BG)
    zoom_slider_ax.set_navigate(False)
    for s in zoom_slider_ax.spines.values():
        s.set_color(BORDER)
        s.set_linewidth(0.5)

    zoom_slider = Slider(zoom_slider_ax, "", 1.0, max_zoom, valinit=1.0,
                         orientation="vertical",
                         color=ACCENT, track_color=BORDER,
                         handle_style={"facecolor": ACCENT, "edgecolor": TEXT,
                                       "size": 12})
    zoom_slider.valtext.set_visible(False)

    def on_zoom_slider(val):
        new_zoom = max(1.0, min(val, max_zoom))
        if abs(new_zoom - state["zoom"]) < 0.01:
            return
        old_span = full_span / state["zoom"]
        new_span = full_span / new_zoom
        xmin, xmax = ax.get_xlim()
        center = (xmin + xmax) / 2.0
        new_left = center - new_span / 2.0
        new_left = max(full_xmin, min(new_left, full_xmax - new_span))

        state["zoom"] = new_zoom
        pannable = full_span - new_span
        state["pos"] = max(0.0, min(1.0,
            (new_left - full_xmin) / pannable if pannable > 0 else 0.0))
        slider.eventson = False
        slider.set_val(state["pos"])
        slider.eventson = True
        apply_view()

    zoom_slider.on_changed(on_zoom_slider)

    # --- Click-drag panning ---
    drag = {"active": False, "x0": None}

    def on_press(event):
        if event.inaxes not in (ax, ax2) or event.button != 1:
            return
        drag["active"] = True
        drag["x0"] = event.xdata

    def on_release(event):
        drag["active"] = False
        drag["x0"] = None

    def on_drag(event):
        if not drag["active"] or event.inaxes not in (ax, ax2) or event.xdata is None:
            return
        dx = drag["x0"] - event.xdata
        xmin, xmax = ax.get_xlim()
        span = xmax - xmin
        new_left = xmin + dx
        new_left = max(full_xmin, min(new_left, full_xmax - span))
        ax.set_xlim(new_left, new_left + span)
        pannable = full_span - span
        state["pos"] = max(0.0, min(1.0,
            (new_left - full_xmin) / pannable if pannable > 0 else 0.0))
        slider.eventson = False
        slider.set_val(state["pos"])
        slider.eventson = True
        rescale_y()
        fig.canvas.draw_idle()
        drag["x0"] = event.xdata

    fig.canvas.mpl_connect("button_press_event", on_press)
    fig.canvas.mpl_connect("button_release_event", on_release)
    fig.canvas.mpl_connect("motion_notify_event", on_drag)

    # --- Cursor crosshair ---
    cursor_line = ax.axvline(x=full_xmin, color=DIM, linewidth=0.7,
                             linestyle="--", visible=False)
    cursor_dots = [ax.plot([], [], "o", color=colors[i], markersize=4,
                           visible=False, zorder=5)[0]
                   for i in range(n_sensors)]
    cursor_dots2 = [ax2.plot([], [], "o", color=colors[i], markersize=4,
                             visible=False, zorder=5)[0]
                    for i in range(n_sensors)]
    cursor_box = ax.annotate("", xy=(0, 0), xytext=(12, 12),
                             textcoords="offset points",
                             fontsize=7, color=TEXT, family="monospace",
                             bbox=dict(boxstyle="round,pad=0.4",
                                       fc=PANEL, ec=BORDER, alpha=0.92),
                             visible=False, zorder=10)

    def on_mouse_move(event):
        if drag["active"]:
            return
        if event.inaxes not in (ax, ax2) or event.xdata is None:
            cursor_line.set_visible(False)
            cursor_box.set_visible(False)
            for d1, d2 in zip(cursor_dots, cursor_dots2):
                d1.set_visible(False)
                d2.set_visible(False)
            fig.canvas.draw_idle()
            return

        x = event.xdata
        idx = np.searchsorted(times, x)
        idx = max(0, min(idx, n_pts - 1))
        if idx > 0 and abs(times[idx - 1] - x) < abs(times[idx] - x):
            idx -= 1
        snap_x = times[idx]

        cursor_line.set_xdata([snap_x])
        cursor_line.set_visible(True)

        dt = mdates.num2date(snap_x)
        ts = dt.strftime("%H:%M:%S") + f".{dt.microsecond // 10000:02d}"
        parts = [ts, "\u2500" * len(ts)]

        for i, col in enumerate(sensor_cols):
            on_right = state["mode"] == "Dual Y" and i in group_right
            active_line = plot_lines2[i] if on_right else plot_lines[i]
            dot = cursor_dots2[i] if on_right else cursor_dots[i]
            other_dot = cursor_dots[i] if on_right else cursor_dots2[i]
            other_dot.set_visible(False)

            if not active_line.get_visible():
                dot.set_visible(False)
                continue

            raw_val = raw_data[i][idx]
            plot_val = active_line.get_ydata()[idx]

            if not np.isfinite(raw_val) or not np.isfinite(plot_val):
                dot.set_visible(False)
                continue

            dot.set_data([snap_x], [plot_val])
            dot.set_visible(True)

            short = col.split("(")[0].strip()[:16]
            parts.append(f"{short:<16s} {raw_val:>10.2f}")

        if len(parts) <= 2:
            cursor_box.set_visible(False)
        else:
            cursor_box.set_text("\n".join(parts))
            if event.inaxes == ax2:
                disp = ax2.transData.transform((snap_x, event.ydata))
                ax_pt = ax.transData.inverted().transform(disp)
                cursor_box.xy = (ax_pt[0], ax_pt[1])
            else:
                cursor_box.xy = (snap_x, event.ydata)

            box_x, _ = fig.transFigure.inverted().transform(
                ax.transData.transform((snap_x, 0)))
            offset_x = -180 if box_x > 0.65 else 12
            cursor_box.set_anncoords("offset points")
            cursor_box.xyann = (offset_x, 12)
            cursor_box.set_visible(True)

        fig.canvas.draw_idle()

    fig.canvas.mpl_connect("motion_notify_event", on_mouse_move)

    # --- Replay sync marker (driven by shared index from dashboard) ---
    if replay_idx is not None:
        _replay_line = ax.axvline(x=full_xmin, color="#5cb8ff", linewidth=0.7,
                                  linestyle="--", alpha=0.85, visible=False, zorder=4)
        _replay_last = [None]

        def _update_replay_marker():
            try:
                idx = replay_idx.value
            except Exception:
                return
            if idx == _replay_last[0]:
                return
            _replay_last[0] = idx
            if 0 <= idx < n_pts:
                _replay_line.set_xdata([times[idx]])
                _replay_line.set_visible(True)
            else:
                _replay_line.set_visible(False)
            fig.canvas.draw_idle()

        _replay_timer = fig.canvas.new_timer(interval=50)
        _replay_timer.add_callback(_update_replay_marker)
        _replay_timer.start()

    switch_mode("Min-Max %")
    plt.show()


if __name__ == "__main__":
    main()
