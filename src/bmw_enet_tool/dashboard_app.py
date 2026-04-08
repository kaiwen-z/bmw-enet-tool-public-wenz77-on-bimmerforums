"""BMW F10 535i Live Sensor Dashboard - application shell (split from sourcecode)."""

import json as _json
import multiprocessing
import os
import queue
import socket
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox
from datetime import datetime

from . import log_viewer
from .paths import application_base_dir
from .protocol import DYN_H, DYN_L, TESTER, hsfz, parse_hsfz
from .sensors import (
    SENSORS, get_sensors, get_sensor_by_id, sensor_id_at, index_of,
    add_sensor, update_sensor, delete_sensor, _resolve_sensor_json_path,
)
from .ui_theme import *  # noqa: F403
from .gauge_canvas import GaugeHost
from .gauge_editor_dialog import GaugeEditorDialog
from .gauge_profile import DEFAULT_GAUGE_PROFILE, load_profile, save_profile
from .sensor_editor_dialog import SensorEditorDialog
from .widgets import CanvasScrollbar


def _launch_log_viewer(filepath):
    """Module-level target for multiprocessing - must be picklable."""
    log_viewer.main(filepath)


def _launch_log_viewer_synced(filepath, shared_idx):
    """Log viewer with shared replay index for cursor synchronisation."""
    log_viewer.main(filepath, replay_idx=shared_idx)


class Dashboard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Live Sensor Dashboard by 77_wenz")
        self.configure(bg=BG)
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = max(1000, min(sw, int(sw * 0.88)))
        h = max(600, min(sh, int(sh * 0.85)))
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(900, 580)

        self._sock      = None
        self._running   = False
        self._pkt_queue = queue.Queue()
        self._rx_buf    = b""
        self._vin       = "—"

        # Sensor polling queue: list of (ecu, did, size, scale_fn, sensor_id)
        self._poll_queue   = []
        self._poll_idx     = 0
        self._poll_pending = None   # (did, size, scale_fn, sensor_id, gen, ecu)
        self._poll_active  = False
        self._poll_delay   = 20

        self._last_sensor_time = None
        self._delay_samples    = []

        # JSON logging
        self._log_file     = None
        self._log_writer   = None   # not used for JSON; kept for compat
        self._logging      = False
        self._log_latest   = {}     # sensor_id -> latest physical value
        self._log_path     = ""
        self._log_row_count = 0

        self._send_lock = threading.Lock()
        self._stall_reconnecting = False

        self._disabled_gauges = set()   # sensor_id strings

        self._poll_gen = 0
        self._last_gauge_update = None
        self._watchdog_id       = None

        # Log replay
        self._replay_data     = []    # list of (ts_str, {sensor_id: phys})
        self._replay_idx      = 0
        self._replay_state    = "idle"
        self._replay_after_id = None
        self._replay_load_gen = 0

        self._build_ui()
        self.bind_all("<Button-1>", self._on_global_click)
        self.bind_all("<space>", self._on_space)
        self.after(10, self._drain_queue)

    # ──────────────────────────────────────────
    #  Build UI
    # ──────────────────────────────────────────
    def _build_ui(self):
        hdr = tk.Frame(self, bg=PANEL, height=56)
        hdr.pack(fill="x"); hdr.pack_propagate(False)

        tk.Label(hdr, text="BMW ENET", bg=PANEL, fg=ACCENT,
                 font=("Segoe UI", 16, "bold")).pack(side="left", padx=(18, 4), pady=14)
        tk.Label(hdr, text="FXX  35i  N55  ·  LIVE DIAGNOSTICS",
                 bg=PANEL, fg=DIM, font=("Segoe UI", 10)).pack(side="left", pady=14)

        vin_frame = tk.Frame(hdr, bg=PANEL)
        vin_frame.pack(side="left", padx=30, pady=10)
        tk.Label(vin_frame, text="VIN", bg=PANEL, fg=META_C,
                 font=SMALL_FONT).pack(anchor="w")
        self._vin_var = tk.StringVar(value="——————————————————")
        tk.Label(vin_frame, textvariable=self._vin_var, bg=PANEL, fg=VIN_C,
                 font=("Courier New", 11, "bold")).pack(anchor="w")

        self._sdot = tk.Label(hdr, text="●", bg=PANEL, fg=DIM, font=("Segoe UI", 16))
        self._sdot.pack(side="right", padx=(4, 18))
        self._slbl = tk.Label(hdr, text="OFFLINE", bg=PANEL, fg=DIM, font=SMALL_FONT)
        self._slbl.pack(side="right")

        ri_frame = tk.Frame(hdr, bg=PANEL)
        ri_frame.pack(side="right", padx=20)
        tk.Label(ri_frame, text="avg sensor delay", bg=PANEL, fg=META_C,
                 font=SMALL_FONT).pack(anchor="e")
        self._delay_var = tk.StringVar(value="— ms")
        tk.Label(ri_frame, textvariable=self._delay_var, bg=PANEL, fg=ACCENT,
                 font=("Courier New", 11, "bold")).pack(anchor="e")

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True)

        # ── Left sidebar ──
        side = tk.Frame(body, bg=PANEL, width=220)
        side.pack(side="left", fill="y"); side.pack_propagate(False)

        self._sep(side)
        tk.Label(side, text="  CONNECTION", bg=PANEL, fg=DIM,
                 font=("Segoe UI", 8, "bold"), anchor="w").pack(fill="x", pady=(4, 6))
        self._ip_var   = tk.StringVar(value="169.254.9.103")
        self._port_var = tk.StringVar(value="6801")

        tk.Label(side, text="Target IP", bg=PANEL, fg=DIM, font=SMALL_FONT,
                 anchor="w").pack(fill="x", padx=16)
        ip_row = tk.Frame(side, bg=PANEL)
        ip_row.pack(fill="x", padx=16, pady=(2, 8))
        tk.Entry(ip_row, textvariable=self._ip_var, bg=ENTRY_BG, fg=TEXT,
                 insertbackground=ACCENT, relief="flat", font=("Courier New", 9),
                 bd=0, highlightthickness=1, highlightcolor=ACCENT,
                 highlightbackground=BORDER).pack(side="left", fill="x", expand=True, ipady=4)
        self._discover_btn = tk.Button(
            ip_row, text="🔍", bg=BTN_BG, fg=TEXT,
            activebackground=BTN_ACTIVE_BG, activeforeground=TEXT,
            font=("Segoe UI", 9), bd=0, padx=6,
            cursor="hand2", command=self._discover_car)
        self._discover_btn.pack(side="right", fill="y", padx=(4, 0))

        self._field(side, "Port", self._port_var)

        self._cbtn = tk.Button(side, text="⬡  CONNECT", bg=ACCENT, fg=WHITE,
                               activebackground=ACCENT_ACTIVE, activeforeground=WHITE,
                               font=("Segoe UI", 10, "bold"), bd=0, pady=10,
                               cursor="hand2", command=self._toggle_connect)
        self._cbtn.pack(fill="x", padx=16, pady=(10, 4))

        self._sep(side)
        tk.Label(side, text="  POLLING", bg=PANEL, fg=DIM,
                 font=("Segoe UI", 8, "bold"), anchor="w").pack(fill="x", pady=(4, 6))

        self._poll_btn = tk.Button(side, text="▶  START POLLING", bg=BTN_BG, fg=DIM,
                                   activebackground=BTN_ACTIVE_BG, activeforeground=TEXT,
                                   font=("Segoe UI", 9, "bold"), bd=0, pady=8,
                                   cursor="hand2", command=self._toggle_polling,
                                   state="disabled")
        self._poll_btn.pack(fill="x", padx=16, pady=(2, 4))

        # ── Logging (collapsible) ──
        self._sep(side)
        self._logging_expanded = False
        logging_hdr = tk.Frame(side, bg=PANEL, cursor="hand2")
        logging_hdr.pack(fill="x", pady=(4, 0))
        self._logging_arrow = tk.Label(logging_hdr, text="▸", bg=PANEL, fg=DIM,
                                       font=("Segoe UI", 8), cursor="hand2")
        self._logging_arrow.pack(side="left", padx=(8, 0))
        tk.Label(logging_hdr, text="LOGGING", bg=PANEL, fg=DIM,
                 font=("Segoe UI", 8, "bold"), anchor="w",
                 cursor="hand2").pack(side="left", padx=2)

        logging_container = tk.Frame(side, bg=PANEL)

        self._log_btn = tk.Button(logging_container, text="⏺  START LOGGING", bg=BTN_BG, fg=DIM,
                                  activebackground=BTN_ACTIVE_BG, activeforeground=TEXT,
                                  font=("Segoe UI", 9, "bold"), bd=0, pady=8,
                                  cursor="hand2", command=self._toggle_logging,
                                  state="disabled")
        self._log_btn.pack(fill="x", padx=16, pady=(2, 2))

        self._log_name_var = tk.StringVar(value="no log active")
        tk.Label(logging_container, textvariable=self._log_name_var, bg=PANEL, fg=META_C,
                 font=("Courier New", 6), wraplength=196, justify="left",
                 anchor="w").pack(fill="x", padx=16, pady=(0, 4))

        view_row = tk.Frame(logging_container, bg=PANEL)
        view_row.pack(fill="x", padx=16, pady=(2, 4))
        view_row.columnconfigure(0, weight=1, uniform="logbtn")
        view_row.columnconfigure(1, weight=1, uniform="logbtn")
        _btn_kw = dict(bg=BTN_BG, fg=DIM, activebackground=BTN_ACTIVE_BG,
                       activeforeground=TEXT, font=("Segoe UI", 9, "bold"),
                       bd=0, pady=8, cursor="hand2")
        self._view_log_btn = tk.Button(
            view_row, text="📊 VIEW LOG", command=self._view_log, **_btn_kw)
        self._view_log_btn.grid(row=0, column=0, sticky="nsew")
        self._replay_btn = tk.Button(
            view_row, text="🔄 REPLAY", command=self._replay_action, **_btn_kw)
        self._replay_btn.grid(row=0, column=1, sticky="nsew", padx=(2, 0))
        self._replay_name_var = tk.StringVar(value="")
        self._replay_name_lbl = tk.Label(
            logging_container, textvariable=self._replay_name_var, bg=PANEL, fg=META_C,
            font=("Courier New", 6), wraplength=196, justify="left", anchor="w")
        self._replay_name_lbl.pack(fill="x", padx=16, pady=(0, 2))
        self._replay_name_lbl.pack_forget()

        def _toggle_logging_controls(_event=None):
            if self._logging_expanded:
                logging_container.pack_forget()
                self._logging_arrow.configure(text="▸")
                self._logging_expanded = False
            else:
                logging_container.pack(fill="x", pady=(0, 2), after=logging_hdr)
                self._logging_arrow.configure(text="▾")
                self._logging_expanded = True

        logging_hdr.bind("<Button-1>", _toggle_logging_controls)
        for child in logging_hdr.winfo_children():
            child.bind("<Button-1>", _toggle_logging_controls)

        # ── Sensor list (collapsible) ──
        self._sep(side)
        self._sensor_expanded = False
        sensor_hdr = tk.Frame(side, bg=PANEL, cursor="hand2")
        sensor_hdr.pack(fill="x", pady=(4, 0))
        self._sensor_arrow = tk.Label(sensor_hdr, text="▸", bg=PANEL, fg=DIM,
                                      font=("Segoe UI", 8), cursor="hand2")
        self._sensor_arrow.pack(side="left", padx=(8, 0))
        tk.Label(sensor_hdr, text="SENSOR LIST", bg=PANEL, fg=DIM,
                 font=("Segoe UI", 8, "bold"), anchor="w",
                 cursor="hand2").pack(side="left", padx=2)

        SENSOR_LIST_HEIGHT = 160
        self._sensor_container = tk.Frame(side, bg=PANEL, height=SENSOR_LIST_HEIGHT)
        self._sensor_container.pack_propagate(False)

        # Sensor management buttons
        _mgmt_row = tk.Frame(self._sensor_container, bg=PANEL)
        _mgmt_row.pack(fill="x", padx=12, pady=(4, 4))
        _mgmt_kw = dict(bg=BTN_BG, fg=DIM, activebackground=BTN_ACTIVE_BG,
                        activeforeground=TEXT, font=("Segoe UI", 7), bd=0,
                        cursor="hand2", padx=4)
        tk.Button(_mgmt_row, text="+ Add", command=self._add_sensor_dialog, **_mgmt_kw
                  ).pack(side="left", padx=(0, 2))
        tk.Button(_mgmt_row, text="Edit…", command=self._edit_sensor_dialog, **_mgmt_kw
                  ).pack(side="left", padx=(0, 2))
        tk.Button(_mgmt_row, text="Delete…", command=self._delete_sensor_dialog, **_mgmt_kw
                  ).pack(side="left")

        sensor_canvas = tk.Canvas(self._sensor_container, bg=PANEL, bd=0, highlightthickness=0)
        self._sensor_inner = tk.Frame(sensor_canvas, bg=PANEL)

        def _canvas_yview(*args):
            sensor_canvas.yview(*args)
            first, last = sensor_canvas.yview()
            sensor_scroll.set(first, last)

        sensor_scroll = CanvasScrollbar(
            self._sensor_container, command=_canvas_yview,
            troughcolor=BORDER, thumbactive=LABEL_C
        )
        self._sensor_win_id = sensor_canvas.create_window((0, 0), window=self._sensor_inner, anchor="nw")
        sensor_canvas.configure(yscrollcommand=sensor_scroll.set)
        self._sensor_canvas = sensor_canvas
        self._sensor_scroll = sensor_scroll

        def _update_sensor_scroll_region(*_):
            sensor_canvas.update_idletasks()
            try:
                cw = max(sensor_canvas.winfo_width() or 1, self._sensor_inner.winfo_reqwidth() or 1)
                ch = self._sensor_inner.winfo_reqheight() or self._sensor_inner.winfo_height() or 1
                if ch > 0:
                    sensor_canvas.configure(scrollregion=(0, 0, cw, ch))
            except Exception:
                sensor_canvas.configure(scrollregion=sensor_canvas.bbox("all"))
            first, last = sensor_canvas.yview()
            sensor_scroll.set(first, last)
        self._sensor_inner.bind("<Configure>", _update_sensor_scroll_region)
        self._update_sensor_scroll_region = _update_sensor_scroll_region

        def _on_sensor_canvas_configure(event):
            sensor_canvas.itemconfig(self._sensor_win_id, width=event.width)
        sensor_canvas.bind("<Configure>", _on_sensor_canvas_configure)

        def _sync_scrollbar():
            first, last = sensor_canvas.yview()
            sensor_scroll.set(first, last)

        def _sensor_mousewheel(event):
            sensor_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            self.after(0, _sync_scrollbar)
            return "break"
        sensor_canvas.bind("<MouseWheel>", _sensor_mousewheel)
        self._sensor_inner.bind("<MouseWheel>", _sensor_mousewheel)
        self._sensor_container.bind("<MouseWheel>", _sensor_mousewheel)
        self._sensor_mousewheel = _sensor_mousewheel

        self._sensor_list_rows = {}  # sensor_id -> (frame, l1, l2)
        self._rebuild_sensor_list_ui()

        sensor_scroll.pack(side="right", fill="y")
        sensor_canvas.pack(side="left", fill="both", expand=True)

        self._sensor_hdr = sensor_hdr

        def _toggle_sensor_list(_event=None):
            if self._sensor_expanded:
                self._sensor_container.pack_forget()
                self._sensor_arrow.configure(text="▸")
                self._sensor_expanded = False
            else:
                self._sensor_container.pack(fill="x", pady=(0, 2), after=sensor_hdr)
                self._sensor_arrow.configure(text="▾")
                self._sensor_expanded = True
                self.after(50, _update_sensor_scroll_region)

        sensor_hdr.bind("<Button-1>", _toggle_sensor_list)
        for child in sensor_hdr.winfo_children():
            child.bind("<Button-1>", _toggle_sensor_list)

        self._sep(side)
        tk.Label(side, text="  EVENT LOG", bg=PANEL, fg=DIM,
                 font=("Segoe UI", 8, "bold"), anchor="w").pack(fill="x", pady=(4, 4))

        log_frame = tk.Frame(side, bg=LOG_BG)
        log_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._log = tk.Text(log_frame, bg=LOG_BG, fg=META_C, font=("Courier New", 7),
                            bd=0, relief="flat", wrap="word",
                            padx=4, pady=4,
                            selectbackground=ACCENT, selectforeground=WHITE)
        self._log.pack(fill="both", expand=True)
        def _log_key_guard(e):
            if e.keysym in ("c", "C") and (e.state & 0x4):
                return
            return "break"
        self._log.bind("<Key>", _log_key_guard)
        self._log.tag_config("ok",   foreground=SUCCESS)
        self._log.tag_config("err",  foreground=ERROR_C)
        self._log.tag_config("warn", foreground=WARNING_C)
        self._log.tag_config("info", foreground=ACCENT)
        self._log.tag_config("vin",  foreground=VIN_C)
        self._log.tag_config("dim",  foreground=META_C)

        # ── Divider ──
        tk.Frame(body, bg=BORDER, width=1).pack(side="left", fill="y")

        # ── Gauge area ──
        gauge_outer = tk.Frame(body, bg=BG)
        gauge_outer.pack(side="left", fill="both", expand=True)

        strip = tk.Frame(gauge_outer, bg=STRIP_BG, height=28)
        strip.pack(fill="x"); strip.pack_propagate(False)
        tk.Label(strip, text="  LIVE SENSOR READOUT  \u00b7  ECU 0x12 (N55 DME)",
                 bg=STRIP_BG, fg=DIM, font=("Segoe UI", 7)).pack(side="left", pady=6)

        _sbtn = dict(bg=BTN_BG, fg=DIM, activebackground=BTN_ACTIVE_BG,
                     activeforeground=TEXT, font=("Segoe UI", 7), bd=0,
                     cursor="hand2", padx=6)
        tk.Button(strip, text="+ Add gauge",
                  command=self._add_gauge_dialog, **_sbtn
                  ).pack(side="right", padx=2, pady=4)
        tk.Button(strip, text="Save profile\u2026",
                  command=self._save_gauge_profile, **_sbtn
                  ).pack(side="right", padx=2, pady=4)
        tk.Button(strip, text="Load profile\u2026",
                  command=self._open_gauge_profile, **_sbtn
                  ).pack(side="right", padx=2, pady=4)
        tk.Button(strip, text="Reset layout",
                  command=self._reset_gauge_profile, **_sbtn
                  ).pack(side="right", padx=2, pady=4)
        tk.Button(strip, text="Fit to canvas",
                  command=self._grow_gauges_to_fill, **_sbtn
                  ).pack(side="right", padx=2, pady=4)
        tk.Button(strip, text="Clear canvas",
                  command=self._clear_gauge_canvas, **_sbtn
                  ).pack(side="right", padx=2, pady=4)
        self._canvas_edit_buttons = [
            w for w in strip.winfo_children()
            if isinstance(w, tk.Button)
            and w.cget("text") in {"+ Add gauge", "Load profile…", "Reset layout", "Fit to canvas", "Clear canvas"}
        ]

        tk.Frame(gauge_outer, bg=BORDER, height=1).pack(fill="x")

        self._gauge_host = GaugeHost(gauge_outer)
        self._gauge_host.pack(fill="both", expand=True, padx=0, pady=0)

        self._rebuild_poll_queue()

        self._gauges = {}  # sensor_id -> gauge widget (or None)
        self._apply_profile(self._default_layout_profile())
        self._set_canvas_editing_enabled(True)

        # ── Replay timeline bar ──
        self._timeline = tk.Frame(self, bg=STRIP_BG, height=38)
        self._timeline.pack_propagate(False)

        tl_btn_kw = dict(bg=BTN_BG, activebackground=BTN_ACTIVE_BG,
                         activeforeground=TEXT, font=("Segoe UI", 10),
                         bd=0, cursor="hand2", padx=6, pady=2)

        self._tl_start_btn = tk.Button(
            self._timeline, text="⏮", fg=DIM, command=self._replay_jump_start, **tl_btn_kw)
        self._tl_start_btn.pack(side="left", padx=(8, 2), pady=4)

        self._tl_play_btn = tk.Button(
            self._timeline, text="▶", fg=SUCCESS, command=self._replay_play_pause, **tl_btn_kw)
        self._tl_play_btn.pack(side="left", padx=2, pady=4)

        self._tl_end_btn = tk.Button(
            self._timeline, text="⏭", fg=DIM, command=self._replay_jump_end, **tl_btn_kw)
        self._tl_end_btn.pack(side="left", padx=(2, 8), pady=4)

        self._tl_row_var = tk.StringVar(value="0 / 0")
        tk.Label(self._timeline, textvariable=self._tl_row_var, bg=STRIP_BG,
                 fg=DIM, font=("Courier New", 7)).pack(side="right", padx=(4, 10))

        self._tl_time_var = tk.StringVar(value="00:00 / 00:00")
        tk.Label(self._timeline, textvariable=self._tl_time_var, bg=STRIP_BG,
                 fg=ACCENT, font=("Courier New", 8, "bold")).pack(side="right", padx=4)

        self._tl_canvas = tk.Canvas(self._timeline, bg=STRIP_BG, height=22,
                                    bd=0, highlightthickness=0)
        self._tl_canvas.pack(side="left", fill="both", expand=True, padx=(4, 4), pady=8)
        self._tl_canvas.bind("<Configure>", self._tl_on_resize)
        self._tl_canvas.bind("<Button-1>", self._tl_on_click)
        self._tl_canvas.bind("<B1-Motion>", self._tl_on_drag)
        self._tl_dragging = False
        self._tl_canvas_w = 1

        tk.Frame(self._timeline, bg=BORDER, width=1).pack(side="left", fill="y", pady=4)

        # ── Status bar ──
        self._status_sep = tk.Frame(self, bg=BORDER, height=1)
        self._status_sep.pack(fill="x")
        sb = tk.Frame(self, bg=PANEL, height=24)
        sb.pack(fill="x", side="bottom"); sb.pack_propagate(False)
        self._fvar = tk.StringVar(value="BMW FXX ENET Dashboard  ·  HSFZ / UDS  ·  Offline")
        tk.Label(sb, textvariable=self._fvar, bg=PANEL, fg=DIM,
                 font=SMALL_FONT).pack(side="left", padx=12, pady=4)
        self._poll_status = tk.StringVar(value="")
        tk.Label(sb, textvariable=self._poll_status, bg=PANEL, fg=DIM,
                 font=("Courier New", 7)).pack(side="right", padx=12)

    # ── Sensor list UI ──
    def _rebuild_sensor_list_ui(self):
        for child in self._sensor_inner.winfo_children():
            child.destroy()
        self._sensor_list_rows = {}
        mw = self._sensor_mousewheel
        sensors = get_sensors()
        for s in sensors:
            sid = s["sensor_id"]
            r = tk.Frame(self._sensor_inner, bg=PANEL, cursor="hand2")
            r.pack(fill="x", padx=12, pady=1)
            r.bind("<MouseWheel>", mw)
            l1 = tk.Label(r, text=f"0x{s['did']:04X}", bg=PANEL, fg=DIM,
                         font=("Courier New", 8), width=6, anchor="w", cursor="hand2")
            l1.pack(side="left")
            l1.bind("<MouseWheel>", mw)
            l2 = tk.Label(r, text=s["label"], bg=PANEL, fg=LABEL_C,
                          font=SMALL_FONT, anchor="w", cursor="hand2")
            l2.pack(side="left", padx=4)
            l2.bind("<MouseWheel>", mw)
            def _make_click(sensor_id):
                def _on_click(_event=None):
                    self._toggle_sensor_by_id(sensor_id)
                return _on_click
            _row_click = _make_click(sid)
            r.bind("<Button-1>", _row_click)
            l1.bind("<Button-1>", _row_click)
            l2.bind("<Button-1>", _row_click)
            # Right-click context menu
            def _make_rclick(sensor_id):
                def _on_rclick(event):
                    menu = tk.Menu(self, tearoff=False)
                    menu.add_command(label="Edit Sensor…",
                                    command=lambda: self._edit_sensor(sensor_id))
                    menu.add_command(label="Delete Sensor",
                                    command=lambda: self._delete_sensor(sensor_id))
                    menu.tk_popup(event.x_root, event.y_root)
                return _on_rclick
            _rclick = _make_rclick(sid)
            r.bind("<Button-3>", _rclick)
            l1.bind("<Button-3>", _rclick)
            l2.bind("<Button-3>", _rclick)
            self._sensor_list_rows[sid] = (r, l1, l2)
            self._update_sensor_row_style(sid)

    def _rebuild_poll_queue(self):
        self._poll_queue = []
        for s in get_sensors():
            sid = s["sensor_id"]
            idx = index_of(sid)
            scale_fn = SENSORS[idx][4]
            self._poll_queue.append((s["ecu"], s["did"], s["size"], scale_fn, sid))

    # ── Focus management ──
    def _on_global_click(self, event):
        if not isinstance(event.widget, (tk.Entry, tk.Text)):
            self.focus_set()

    def _on_space(self, event):
        if isinstance(event.widget, tk.Entry):
            return
        if self._replay_state in ("paused", "playing"):
            self._replay_play_pause()
            return "break"

    # ── Sidebar helpers ──
    def _sep(self, p):
        tk.Frame(p, bg=BORDER, height=1).pack(fill="x", pady=(10, 0))

    def _field(self, p, lbl, var):
        tk.Label(p, text=lbl, bg=PANEL, fg=DIM, font=SMALL_FONT,
                 anchor="w").pack(fill="x", padx=16)
        tk.Entry(p, textvariable=var, bg=ENTRY_BG, fg=TEXT, insertbackground=ACCENT,
                 relief="flat", font=("Courier New", 9), bd=0,
                 highlightthickness=1, highlightcolor=ACCENT,
                 highlightbackground=BORDER).pack(fill="x", padx=16, pady=(2, 8), ipady=4)

    # ── Live-control enable / disable ──
    def _set_live_controls_enabled(self, enabled: bool):
        if enabled:
            self._cbtn.configure(state="normal", bg=ACCENT, fg=WHITE)
            self._poll_btn.configure(state="disabled", fg=DIM)
            self._log_btn.configure(state="disabled", fg=DIM)
            self._sdot.configure(fg=DIM)
            self._slbl.configure(fg=DIM, text="OFFLINE")
            self._cbtn.configure(text="⬡  CONNECT")
        else:
            self._cbtn.configure(state="disabled", bg=CBTN_BG_DISABLED, fg=DIM,
                                 text="⬡  CONNECT")
            self._poll_btn.configure(state="disabled", fg=DIM,
                                     text="▶  START POLLING", bg=BTN_BG)
            self._log_btn.configure(state="disabled", fg=DIM,
                                    text="⏺  START LOGGING", bg=BTN_BG)
            self._sdot.configure(fg=WARNING_C)
            self._slbl.configure(fg=WARNING_C, text="REPLAY")

    # ── Log ──
    def _evt(self, msg, tag="dim"):
        ts = datetime.now().strftime("%H:%M:%S")
        self._log.insert("end", f"[{ts}] {msg}\n", tag)
        self._log.see("end")

    def _toggle_sensor_by_id(self, sensor_id: str):
        if self._replay_state != "idle":
            self._evt("Cannot toggle sensors during replay", "warn")
            return
        if self._logging:
            self._evt("Cannot toggle sensors while logging", "warn")
            return
        s = get_sensor_by_id(sensor_id)
        if s is None:
            return
        w = self._gauges.get(sensor_id)
        if sensor_id in self._disabled_gauges:
            self._disabled_gauges.discard(sensor_id)
            if w is not None:
                w.set_active(True)
                w.set_stale()
            self._evt(f"{s['label']}: enabled", "ok")
        else:
            self._disabled_gauges.add(sensor_id)
            if w is not None:
                w.set_active(False)
            self._evt(f"{s['label']}: disabled", "warn")
        self._update_sensor_row_style(sensor_id)

    def _update_sensor_row_style(self, sensor_id: str):
        row = self._sensor_list_rows.get(sensor_id)
        if not row:
            return
        r, l1, l2 = row
        if sensor_id in self._disabled_gauges:
            r.configure(bg=DISABLED_ROW_BG)
            l1.configure(bg=DISABLED_ROW_BG, fg=DISABLED_ROW_FG)
            l2.configure(bg=DISABLED_ROW_BG, fg=DISABLED_ROW_FG)
        else:
            r.configure(bg=PANEL)
            l1.configure(bg=PANEL, fg=DIM)
            l2.configure(bg=PANEL, fg=LABEL_C)

    # ── Sensor CRUD ──
    def _add_sensor_dialog(self):
        if self._logging:
            self._evt("Cannot add sensors while logging", "warn")
            return
        dialog = SensorEditorDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            ok, msg = add_sensor(dialog.result)
            if ok:
                self._rebuild_poll_queue()
                self._rebuild_sensor_list_ui()
                self._evt(f"Added sensor: {dialog.result['label']}", "ok")
            else:
                self._evt(f"Add failed: {msg}", "err")

    def _edit_sensor_dialog(self):
        """Open a picker, then edit the selected sensor."""
        if self._logging:
            self._evt("Cannot edit sensors while logging", "warn")
            return
        sensors = get_sensors()
        if not sensors:
            self._evt("No sensors to edit", "warn")
            return
        self._pick_and_act_sensor("Edit Sensor", self._edit_sensor)

    def _delete_sensor_dialog(self):
        if self._logging:
            self._evt("Cannot delete sensors while logging", "warn")
            return
        sensors = get_sensors()
        if not sensors:
            self._evt("No sensors to delete", "warn")
            return
        self._pick_and_act_sensor("Delete Sensor", self._delete_sensor)

    def _pick_and_act_sensor(self, title, callback):
        """Open a simple list dialog to pick a sensor, then invoke *callback*."""
        win = tk.Toplevel(self)
        win.title(title)
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()
        w, h = 300, 340
        px = self.winfo_rootx() + (self.winfo_width() - w) // 2
        py = self.winfo_rooty() + (self.winfo_height() - h) // 2
        win.geometry(f"{w}x{h}+{px}+{py}")
        sensors = get_sensors()
        lb = tk.Listbox(win, bg=ENTRY_BG, fg=TEXT, font=("Segoe UI", 9),
                        selectbackground=ACCENT, selectforeground=WHITE,
                        selectmode="browse", bd=0, highlightthickness=0,
                        relief="flat", activestyle="none")
        lb.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        for s in sensors:
            lb.insert("end", f"  {s['label']}")
        if sensors:
            lb.selection_set(0)
        btn_row = tk.Frame(win, bg=BG)
        btn_row.pack(fill="x", padx=12, pady=(4, 12))
        def _ok():
            sel = lb.curselection()
            if not sel:
                return
            sid = sensors[sel[0]]["sensor_id"]
            win.destroy()
            callback(sid)
        tk.Button(btn_row, text="Cancel", bg=BTN_BG, fg=DIM,
                  activebackground=BTN_ACTIVE_BG, activeforeground=TEXT,
                  font=("Segoe UI", 9), bd=0, cursor="hand2",
                  command=win.destroy).pack(side="right", ipadx=12, ipady=3)
        tk.Button(btn_row, text="OK", bg=ACCENT, fg=WHITE,
                  activebackground=ACCENT_ACTIVE, activeforeground=WHITE,
                  font=("Segoe UI", 9, "bold"), bd=0, cursor="hand2",
                  command=_ok).pack(side="right", padx=(0, 6), ipadx=16, ipady=3)
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        win.bind("<Return>", lambda _e: _ok())
        win.bind("<Escape>", lambda _e: win.destroy())

    def _edit_sensor(self, sensor_id):
        s = get_sensor_by_id(sensor_id)
        if s is None:
            return
        dialog = SensorEditorDialog(self, sensor_data=s)
        self.wait_window(dialog)
        if dialog.result:
            ok, msg = update_sensor(sensor_id, dialog.result)
            if ok:
                self._rebuild_poll_queue()
                self._rebuild_sensor_list_ui()
                # Recreate gauge if placed
                if sensor_id in self._gauges and self._gauges[sensor_id] is not None:
                    tile = self._gauge_host._tiles.get(sensor_id)
                    if tile:
                        bounds = tile.get_bounds()
                        kind = tile.kind
                        self._gauge_host.remove_tile(sensor_id)
                        new_tile = self._gauge_host.add_tile(
                            sensor_id, kind, *bounds,
                            on_delete=lambda si=sensor_id: self._on_gauge_delete(si),
                        )
                        self._gauges[sensor_id] = new_tile.gauge
                        self._wire_gauge_toggle(sensor_id, new_tile.gauge)
                self._evt(f"Updated sensor: {s['label']}", "ok")
            else:
                self._evt(f"Update failed: {msg}", "err")

    def _delete_sensor(self, sensor_id):
        s = get_sensor_by_id(sensor_id)
        if s is None:
            return
        if not messagebox.askyesno("Delete Sensor",
                                   f"Delete sensor '{s['label']}'?",
                                   parent=self):
            return
        if sensor_id in self._gauges:
            self._gauges.pop(sensor_id, None)
            self._gauge_host.remove_tile(sensor_id)
        self._disabled_gauges.discard(sensor_id)
        ok, msg = delete_sensor(sensor_id)
        if ok:
            self._rebuild_poll_queue()
            self._rebuild_sensor_list_ui()
            self._evt(f"Deleted sensor: {s['label']}", "ok")
        else:
            self._evt(f"Delete failed: {msg}", "err")

    # ── Gauge profile / canvas management ──
    def _apply_profile(self, profile):
        self._gauge_host.clear()
        self._gauges = {}
        for entry in profile["gauges"]:
            sid = entry["sensor_id"]
            if get_sensor_by_id(sid) is None:
                continue
            tile = self._gauge_host.add_tile(
                sid, entry["kind"],
                entry["relx"], entry["rely"],
                entry["relwidth"], entry["relheight"],
                on_delete=lambda si=sid: self._on_gauge_delete(si),
            )
            self._gauges[sid] = tile.gauge
            self._wire_gauge_toggle(sid, tile.gauge)
            if sid in self._disabled_gauges:
                tile.gauge.set_active(False)
        self.after_idle(self._gauge_host.fit_grid_layout)

    def _default_layout_profile(self):
        default_dir = os.path.dirname(_resolve_sensor_json_path())
        default_path = os.path.join(default_dir, "default.profile")
        profile = load_profile(default_path)
        if profile is not None:
            return profile

        # First-run seed: write a user-editable default profile if none exists.
        seeded = {
            "version": DEFAULT_GAUGE_PROFILE.get("version", 2),
            "gauges": [dict(g) for g in DEFAULT_GAUGE_PROFILE.get("gauges", [])],
        }
        if not os.path.exists(default_path):
            try:
                save_profile(seeded, default_path)
            except Exception:
                pass
        return seeded

    def _set_canvas_editing_enabled(self, enabled: bool):
        self._gauge_host.set_editing_enabled(enabled)
        state = "normal" if enabled else "disabled"
        for b in getattr(self, "_canvas_edit_buttons", []):
            b.configure(state=state)

    def _wire_gauge_toggle(self, sensor_id, widget):
        s = get_sensor_by_id(sensor_id)
        label = s["label"] if s else sensor_id
        def _toggle():
            if self._replay_state != "idle":
                self._evt("Cannot toggle sensors during replay", "warn")
                return
            if self._logging:
                self._evt("Cannot toggle sensors while logging", "warn")
                return
            if sensor_id in self._disabled_gauges:
                self._disabled_gauges.discard(sensor_id)
                widget.set_active(True)
                widget.set_stale()
                self._evt(f"{label}: enabled", "ok")
            else:
                self._disabled_gauges.add(sensor_id)
                widget.set_active(False)
                self._evt(f"{label}: disabled", "warn")
            self._update_sensor_row_style(sensor_id)
        widget.set_active(True, on_toggle=_toggle)

    def _on_gauge_delete(self, sensor_id):
        self._gauges.pop(sensor_id, None)
        self._gauge_host.remove_tile(sensor_id)
        s = get_sensor_by_id(sensor_id)
        self._evt(f"Removed {s['label'] if s else sensor_id} gauge", "warn")

    def _add_gauge_dialog(self):
        if self._replay_state != "idle":
            self._evt("Cannot edit gauge canvas during replay", "warn")
            return
        placed = self._gauge_host.placed_sensor_ids()
        dialog = GaugeEditorDialog(self, placed_ids=placed)
        self.wait_window(dialog)
        if dialog.result:
            sid, kind = dialog.result
            rx, ry, rw, rh = self._gauge_host.suggest_new_tile_rect(sid, kind)
            tile = self._gauge_host.add_tile(
                sid, kind, rx, ry, rw, rh,
                on_delete=lambda si=sid: self._on_gauge_delete(si),
            )
            self._gauges[sid] = tile.gauge
            self._wire_gauge_toggle(sid, tile.gauge)
            if sid in self._disabled_gauges:
                tile.gauge.set_active(False)
            s = get_sensor_by_id(sid)
            self._evt(f"Added {s['label'] if s else sid} ({kind})", "ok")

    def _save_gauge_profile(self):
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("Gauge profile", "*.json")],
            title="Save gauge profile",
        )
        if not path:
            return
        profile = self._gauge_host.get_profile()
        save_profile(profile, path)
        self._evt(f"Profile saved \u2192 {os.path.basename(path)}", "ok")

    def _open_gauge_profile(self):
        if self._replay_state != "idle":
            self._evt("Cannot edit gauge canvas during replay", "warn")
            return
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            filetypes=[("Gauge profile", "*.json")],
            title="Load gauge profile",
        )
        if not path:
            return
        profile = load_profile(path)
        if profile is None:
            self._evt("Invalid or unreadable profile file", "err")
            return
        self._apply_profile(profile)
        self._evt(f"Profile loaded \u2190 {os.path.basename(path)}", "ok")

    def _reset_gauge_profile(self):
        if self._replay_state != "idle":
            self._evt("Cannot edit gauge canvas during replay", "warn")
            return
        self._apply_profile(self._default_layout_profile())
        self._evt("Layout reset to default", "ok")

    def _grow_gauges_to_fill(self):
        if self._replay_state != "idle":
            self._evt("Cannot edit gauge canvas during replay", "warn")
            return
        changed = self._gauge_host.grow_tiles_to_fill_space()
        if changed > 0:
            self._evt("Fit to canvas applied", "ok")
        else:
            self._evt("Fit to canvas: cluster already fills available space", "info")

    def _clear_gauge_canvas(self):
        if self._replay_state != "idle":
            self._evt("Cannot edit gauge canvas during replay", "warn")
            return
        if not self._gauge_host.placed_sensor_ids():
            self._evt("Gauge canvas is already empty", "info")
            return
        if not messagebox.askyesno(
            "Clear gauge canvas",
            "Remove all gauges from the canvas?",
            parent=self,
        ):
            return
        self._gauge_host.clear()
        self._gauges = {}
        self._evt("Gauge canvas cleared", "ok")

    # ── Auto-discover ──
    def _discover_car(self):
        if getattr(self, '_discovering', False):
            return
        self._discovering = True
        self._discover_btn.configure(text="…", fg=WARNING_C, state="disabled")
        self._evt("Scanning for BMW on ENET…", "info")
        threading.Thread(target=self._discover_worker, daemon=True).start()

    def _discover_worker(self):
        port = 6801
        try:
            port = int(self._port_var.get().strip())
        except ValueError:
            pass
        found = None
        for ip in ["169.254.9.103", "169.254.9.104", "169.254.9.105",
                    "169.254.9.100", "169.254.9.1"]:
            if self._probe_port(ip, port):
                found = ip
                break
        if not found:
            found = self._scan_subnet("169.254.9", port)
        if not found:
            for prefix in self._find_link_local_subnets():
                if prefix == "169.254.9":
                    continue
                found = self._scan_subnet(prefix, port)
                if found:
                    break
        self._pkt_queue.put(("discover_result", found))

    def _probe_port(self, ip, port, timeout=0.15):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect((ip, port))
            s.close()
            return True
        except Exception:
            try: s.close()
            except Exception: pass
            return False

    def _scan_subnet(self, prefix, port):
        from concurrent.futures import ThreadPoolExecutor, as_completed
        hit = [None]
        def probe(ip):
            if hit[0] is not None:
                return False
            return self._probe_port(ip, port)
        pool = ThreadPoolExecutor(max_workers=32)
        futures = {pool.submit(probe, f"{prefix}.{i}"): f"{prefix}.{i}"
                   for i in range(1, 255)}
        for f in as_completed(futures):
            if f.result() and hit[0] is None:
                hit[0] = futures[f]
                break
        pool.shutdown(wait=False)
        return hit[0]

    def _find_link_local_subnets(self):
        subnets = set()
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                ip = info[4][0]
                if ip.startswith("169.254."):
                    parts = ip.split(".")
                    subnets.add(f"169.254.{parts[2]}")
        except Exception:
            pass
        return subnets

    # ── Connect / disconnect ──
    def _toggle_connect(self):
        if self._running: self._disconnect()
        else:             self._connect()

    def _connect(self):
        if self._replay_state != "idle":
            self._replay_unload()
        ip   = self._ip_var.get().strip()
        port = self._port_var.get().strip()
        try: port = int(port)
        except ValueError:
            self._evt("Port must be an integer", "err"); return
        self._evt(f"Connecting → {ip}:{port} …", "info")
        threading.Thread(target=self._worker, args=(ip, port), daemon=True).start()

    def _worker(self, ip, port):
        try:
            s = socket.socket(); s.settimeout(5.0)
            s.connect((ip, port)); s.settimeout(None)
        except Exception as e:
            self._pkt_queue.put(("err", str(e))); return
        self._sock = s; self._running = True
        self._pkt_queue.put(("connected", (ip, port)))
        self._do_send(0x10, bytes([0x22, 0xF1, 0x90]))
        self._rx_buf = b""
        while self._running:
            try:
                chunk = s.recv(4096)
                if not chunk: break
                self._rx_buf += chunk
                self._parse_rx()
            except Exception: break
        self._pkt_queue.put(("disconnected", None))
        try: s.close()
        except Exception: pass

    def _parse_rx(self):
        while len(self._rx_buf) >= 6:
            res = parse_hsfz(self._rx_buf)
            if res is None: break
            src, dst, uds, consumed, msg_type = res
            self._rx_buf = self._rx_buf[consumed:]
            if msg_type == 0x0002:
                continue
            if msg_type == 0x0043:
                self._pkt_queue.put(("ecu_reset", None))
                continue
            if msg_type != 0x0001:
                continue
            if uds and len(uds) >= 1 and uds[0] == 0x7F:
                self._pkt_queue.put(("nrc", uds))
                continue
            if (uds and len(uds) >= 4
                    and uds[0] == 0x6C and uds[1] == 0x01
                    and uds[2] == DYN_H and uds[3] == DYN_L):
                snapshot = self._poll_pending
                if snapshot:
                    _, _, _, _, gen, ecu = snapshot
                    if gen == self._poll_gen and self._polling and self._running:
                        self._do_send(ecu, bytes([0x22, DYN_H, DYN_L]))
                continue
            if (uds and len(uds) >= 4
                    and uds[0] == 0x6C and uds[1] == 0x03
                    and uds[2] == DYN_H and uds[3] == DYN_L):
                if self._polling and self._running:
                    self._poll_next()
                continue
            if (uds and len(uds) >= 3
                    and uds[0] == 0x62 and uds[1] == DYN_H and uds[2] == DYN_L):
                snapshot = self._poll_pending
                self._poll_pending = None
                if snapshot:
                    self._pkt_queue.put(("sensor", uds[3:], snapshot))
            elif (uds and len(uds) >= 3
                  and uds[0] == 0x62 and uds[1] == 0xF1 and uds[2] == 0x90):
                try:
                    vin = uds[3:].decode("ascii").strip()
                except Exception:
                    vin = uds[3:].hex().upper()
                self._pkt_queue.put(("vin", vin))

    def _do_send(self, dst: int, uds: bytes):
        try:
            with self._send_lock:
                self._sock.sendall(hsfz(TESTER, dst, uds))
        except Exception as e:
            self._pkt_queue.put(("err", f"Send failed: {e}"))

    def _disconnect(self):
        self._polling = False
        self._running = False
        self._stop_watchdog()
        if self._sock:
            try: self._sock.shutdown(socket.SHUT_RDWR); self._sock.close()
            except Exception: pass
            self._sock = None

    _polling     = False
    _poll_timeout_id = None

    def _toggle_polling(self):
        if self._polling:
            self._polling = False
            if self._poll_timeout_id:
                self.after_cancel(self._poll_timeout_id)
                self._poll_timeout_id = None
            self._stop_watchdog()
            self._poll_btn.configure(text="▶  START POLLING", bg=BTN_BG, fg=DIM)
            self._delay_var.set("— ms")
            self._last_sensor_time = None
            self._delay_samples.clear()
            self._evt("Polling stopped", "warn")
        else:
            self._polling = True
            self._poll_idx = 0
            self._poll_pending = None
            self._last_gauge_update = time.monotonic()
            self._poll_btn.configure(text="■  STOP POLLING", bg=WARNING_C, fg=BLACK)
            self._evt("Polling started", "ok")
            self._start_watchdog()
            self._poll_next()

    def _poll_next(self):
        if not self._polling or not self._running: return
        if not self._poll_queue: return
        active_queue = [e for e in self._poll_queue if e[4] not in self._disabled_gauges]
        if not active_queue:
            return
        ecu, did, sz, scale_fn, sensor_id = active_queue[self._poll_idx % len(active_queue)]
        self._poll_idx += 1
        self._poll_gen += 1
        gen = self._poll_gen
        dh = (did >> 8) & 0xFF
        dl = did & 0xFF
        self._poll_pending = (did, sz, scale_fn, sensor_id, gen, ecu)
        self._do_send(ecu, bytes([0x2C, 0x01, DYN_H, DYN_L, dh, dl, 0x01, sz]))
        if self._poll_timeout_id:
            self.after_cancel(self._poll_timeout_id)
        self._poll_timeout_id = self.after(500, self._poll_stall_timeout, gen)

    _stall_count = 0

    def _poll_stall_timeout(self, gen: int):
        if gen != self._poll_gen:
            return
        self._poll_pending    = None
        self._poll_timeout_id = None
        self._stall_count     = 0
        self._evt("ECU stall — reconnecting…", "warn")
        ip   = self._ip_var.get().strip()
        port = self._port_var.get().strip()
        try: port = int(port)
        except ValueError: return
        self._stall_reconnecting = True
        def _do_reconnect():
            if self._sock:
                try: self._sock.shutdown(socket.SHUT_RDWR)
                except Exception: pass
                try: self._sock.close()
                except Exception: pass
            time.sleep(0.15)
            threading.Thread(target=self._worker, args=(ip, port), daemon=True).start()
        threading.Thread(target=_do_reconnect, daemon=True).start()

    # ── Polling watchdog ──
    WATCHDOG_INTERVAL = 1000
    WATCHDOG_TIMEOUT  = 1.5

    def _start_watchdog(self):
        self._stop_watchdog()
        self._watchdog_id = self.after(self.WATCHDOG_INTERVAL, self._watchdog_check)

    def _stop_watchdog(self):
        if self._watchdog_id:
            self.after_cancel(self._watchdog_id)
            self._watchdog_id = None

    def _watchdog_check(self):
        self._watchdog_id = None
        if not self._polling or not self._running:
            return
        if self._stall_reconnecting:
            self._watchdog_id = self.after(self.WATCHDOG_INTERVAL, self._watchdog_check)
            return
        now = time.monotonic()
        elapsed = now - self._last_gauge_update if self._last_gauge_update else 0
        if elapsed > self.WATCHDOG_TIMEOUT:
            self._evt(f"Watchdog: no updates for {elapsed:.1f}s — restarting polling", "warn")
            self._polling = False
            if self._poll_timeout_id:
                self.after_cancel(self._poll_timeout_id)
                self._poll_timeout_id = None
            self._poll_pending = None
            self.after(500, self._watchdog_restart)
            return
        self._watchdog_id = self.after(self.WATCHDOG_INTERVAL, self._watchdog_check)

    def _watchdog_restart(self):
        if not self._running:
            return
        self._polling = True
        self._poll_idx = 0
        self._poll_pending = None
        self._last_gauge_update = time.monotonic()
        self._evt("Watchdog: polling restarted", "ok")
        self._start_watchdog()
        self._poll_next()

    # ── JSON Logging ──
    def _toggle_logging(self):
        if self._logging: self._log_stop()
        else:             self._log_start()

    def _log_start(self):
        ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"bmw_log_{ts}.jsonl"
        self._log_path  = os.path.join(application_base_dir(), filename)
        try:
            self._log_file = open(self._log_path, "w", encoding="utf-8")
            # Write header line
            sensors = get_sensors()
            header = {
                "type": "header",
                "version": 2,
                "sensors": [
                    {"sensor_id": s["sensor_id"], "label": s["label"], "unit": s["unit"]}
                    for s in sensors
                ],
            }
            self._log_file.write(_json.dumps(header, ensure_ascii=False) + "\n")
            self._log_file.flush()
            self._logging = True
            self._log_latest.clear()
            self._log_row_count = 0
            self._log_btn.configure(text="⏹  STOP LOGGING", bg=LOGGING_ACTIVE, fg=WHITE)
            self._log_name_var.set(filename)
            self._evt(f"Logging → {filename}", "ok")
        except Exception as e:
            self._evt(f"Log open failed: {e}", "err")

    def _log_stop(self):
        self._logging = False
        if self._log_file:
            try:
                self._log_file.flush()
                self._log_file.close()
            except Exception: pass
            self._log_file = None
        self._log_btn.configure(text="⏺  START LOGGING", bg=BTN_BG, fg=DIM)
        self._log_name_var.set("no log active")
        self._evt("Logging stopped", "warn")

    def _log_write(self, sensor_id: str, phys: float):
        if not self._logging or not self._log_file: return
        self._log_latest[sensor_id] = phys
        ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        entry = {"ts": ts, "d": dict(self._log_latest)}
        try:
            self._log_file.write(_json.dumps(entry, ensure_ascii=False) + "\n")
            self._log_row_count += 1
            if self._log_row_count % 50 == 0:
                self._log_file.flush()
        except Exception as e:
            self._evt(f"Log write error: {e}", "err")
            self._log_stop()

    # ── View log file ──
    def _view_log(self):
        from tkinter import filedialog
        if self._log_path and os.path.isfile(self._log_path):
            start_dir = os.path.dirname(self._log_path)
        else:
            start_dir = application_base_dir()
        path = filedialog.askopenfilename(
            title="Select BMW Log",
            initialdir=start_dir,
            filetypes=[("Log files", "*.jsonl *.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        self._evt("Opening log viewer\u2026", "info")
        p = multiprocessing.Process(target=_launch_log_viewer, args=(path,), daemon=True)
        p.start()

    # ── Log replay ──
    def _replay_action(self):
        if self._replay_state == "idle":
            self._replay_load()
        else:
            self._replay_unload()

    def _replay_load(self):
        from tkinter import filedialog
        if self._log_path and os.path.isfile(self._log_path):
            start_dir = os.path.dirname(self._log_path)
        else:
            start_dir = application_base_dir()
        path = filedialog.askopenfilename(
            title="Select BMW Log for Replay",
            initialdir=start_dir,
            filetypes=[("Log files", "*.jsonl *.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        self._replay_load_gen += 1
        load_gen = self._replay_load_gen
        self._replay_btn.configure(state="disabled")
        self._fvar.set("Loading replay log…")
        self._evt("Loading replay file\u2026", "info")

        def worker():
            err = None
            rows = None
            t0 = tN = None
            try:
                raw = None
                for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
                    try:
                        with open(path, "r", encoding=enc, errors="replace") as f:
                            raw = f.read()
                        break
                    except Exception:
                        continue
                if raw is None:
                    with open(path, "r", errors="replace") as f:
                        raw = f.read()
                rows, t0, tN = self._parse_log_file(raw, path)
            except Exception as e:
                err = str(e)
            self.after(
                0,
                lambda g=load_gen, p=path, r=rows, a=t0, b=tN, e=err: self._replay_load_finish(
                    g, p, r, a, b, e
                ),
            )

        threading.Thread(target=worker, daemon=True).start()

    def _parse_log_file(self, raw_text, path):
        """Parse a log file (JSONL or CSV) into replay rows.

        Returns ``(rows, t0, tN)`` where each row is ``(ts_str, {sensor_id: phys})``.
        """
        lines = raw_text.splitlines()
        if not lines:
            return [], None, None

        # Detect JSON vs CSV by trying to parse the first non-empty line
        first = ""
        for line in lines:
            if line.strip():
                first = line.strip()
                break

        if first.startswith("{"):
            return self._parse_jsonl_log(lines)
        return self._parse_csv_log(raw_text)

    def _parse_jsonl_log(self, lines):
        """Parse JSONL log format."""
        rows = []
        sensor_map = {}  # populated from header
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entry = _json.loads(line)
            except Exception:
                continue
            if entry.get("type") == "header":
                for info in entry.get("sensors", []):
                    sensor_map[info["sensor_id"]] = info
                continue
            ts = entry.get("ts", "")
            readings = entry.get("d", {})
            if readings:
                rows.append((ts, {k: float(v) for k, v in readings.items()
                                  if v is not None}))
        t0 = Dashboard._parse_replay_ts_static(rows[0][0]) if rows else None
        tN = Dashboard._parse_replay_ts_static(rows[-1][0]) if rows else None
        return rows, t0, tN

    def _parse_csv_log(self, raw_text):
        """Parse legacy CSV log format, mapping columns to sensor_ids."""
        import csv
        reader = csv.reader(raw_text.splitlines())
        header = next(reader, None)
        if not header:
            return [], None, None

        # Map CSV columns to sensor_ids by matching header labels
        col_to_sid = {}
        sensors = get_sensors()
        for col_idx, col_name in enumerate(header[1:], start=1):
            name = col_name.split("(")[0].strip()
            for s in sensors:
                if s["label"] == name:
                    col_to_sid[col_idx] = s["sensor_id"]
                    break
            else:
                # Fallback: try positional index
                pos = col_idx - 1
                if 0 <= pos < len(sensors):
                    col_to_sid[col_idx] = sensors[pos]["sensor_id"]

        rows = []
        for r in reader:
            if not any(c.strip() for c in r):
                continue
            ts = r[0] if r else ""
            readings = {}
            for col_idx, sid in col_to_sid.items():
                if col_idx < len(r):
                    val = r[col_idx].strip()
                    if val:
                        try:
                            readings[sid] = float(val)
                        except (ValueError, TypeError):
                            pass
            rows.append((ts, readings))

        t0 = Dashboard._parse_replay_ts_static(rows[0][0]) if rows else None
        tN = Dashboard._parse_replay_ts_static(rows[-1][0]) if rows else None
        return rows, t0, tN

    @staticmethod
    def _parse_replay_ts_static(ts_str):
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(ts_str.strip(), fmt)
            except (ValueError, TypeError):
                continue
        return None

    def _replay_load_finish(self, load_gen, path, rows, t0, tN, err):
        if not self.winfo_exists():
            return
        if load_gen != self._replay_load_gen:
            return
        self._replay_btn.configure(state="normal")
        if err:
            self._evt(f"Replay load failed: {err}", "err")
            self._fvar.set("BMW FXX ENET Dashboard  ·  HSFZ / UDS  ·  Offline")
            return
        if not rows:
            self._evt("Log file has no data rows", "err")
            self._fvar.set("BMW FXX ENET Dashboard  ·  HSFZ / UDS  ·  Offline")
            return

        self._replay_data = rows
        self._replay_t0 = t0
        self._replay_tN = tN

        if self._running:
            if self._logging:
                self._log_stop()
            if self._polling:
                self._polling = False
                if self._poll_timeout_id:
                    self.after_cancel(self._poll_timeout_id)
                    self._poll_timeout_id = None
                self._stop_watchdog()
            self._disconnect()
            self._evt("Disconnected for replay", "warn")

        self._replay_idx = 0
        self._replay_state = "paused"
        self._replay_btn.configure(text="✕", fg=ERROR_C, bg=BTN_BG)
        name = os.path.basename(path)
        self._replay_name_var.set(name)
        self._replay_name_lbl.pack(fill="x", padx=16, pady=(0, 2))
        self._evt(f"Loaded {len(self._replay_data)} rows from {name}", "ok")
        self._fvar.set(f"Replay loaded  ·  {len(self._replay_data)} rows  ·  ready")
        self._set_live_controls_enabled(False)
        self._set_canvas_editing_enabled(False)
        self._timeline.pack(fill="x", side="bottom", before=self._status_sep)
        self._tl_play_btn.configure(text="▶", fg=SUCCESS)
        self._replay_apply_row(0)
        self._tl_update()
        self._replay_shared_idx = multiprocessing.Value('i', 0)
        p = multiprocessing.Process(target=_launch_log_viewer_synced,
                                    args=(path, self._replay_shared_idx), daemon=True)
        p.start()

    def _replay_unload(self):
        if self._replay_after_id:
            self.after_cancel(self._replay_after_id)
            self._replay_after_id = None
        self._replay_state = "idle"
        self._replay_data = []
        self._replay_idx = 0
        if hasattr(self, '_replay_shared_idx') and self._replay_shared_idx is not None:
            try:
                self._replay_shared_idx.value = -1
            except Exception:
                pass
        self._replay_btn.configure(text="🔄 REPLAY", fg=DIM, bg=BTN_BG)
        self._replay_name_var.set("")
        self._replay_name_lbl.pack_forget()
        self._timeline.pack_forget()
        for g in self._gauges.values():
            if g is not None:
                g.set_stale()
        self._poll_status.set("")
        self._set_live_controls_enabled(True)
        self._set_canvas_editing_enabled(True)
        self._fvar.set("BMW FXX ENET Dashboard  ·  HSFZ / UDS  ·  Offline")
        self._evt("Replay unloaded", "warn")

    def _replay_play_pause(self):
        if self._replay_state == "paused":
            self._replay_play()
        elif self._replay_state == "playing":
            self._replay_pause()

    def _replay_play(self):
        if not self._replay_data:
            return
        if self._replay_idx >= len(self._replay_data):
            self._replay_idx = 0
        self._replay_state = "playing"
        self._tl_play_btn.configure(text="⏸", fg=WARNING_C)
        self._evt("Replay playing", "ok")
        self._replay_step()

    def _replay_pause(self):
        self._replay_state = "paused"
        self._tl_play_btn.configure(text="▶", fg=SUCCESS)
        if self._replay_after_id:
            self.after_cancel(self._replay_after_id)
            self._replay_after_id = None
        self._tl_update()
        self._poll_status.set(
            f"replay: row {self._replay_idx}/{len(self._replay_data)}")
        self._fvar.set(
            f"Replay paused  ·  row {self._replay_idx}/{len(self._replay_data)}")

    def _replay_step(self):
        if self._replay_state != "playing":
            return
        if self._replay_idx >= len(self._replay_data):
            self._replay_finish()
            return
        row = self._replay_data[self._replay_idx]
        delay_ms = 50
        if self._replay_idx + 1 < len(self._replay_data):
            nxt = self._replay_data[self._replay_idx + 1]
            t_now  = self._parse_replay_ts(row[0])
            t_next = self._parse_replay_ts(nxt[0])
            if t_now and t_next:
                delta = (t_next - t_now).total_seconds() * 1000
                delay_ms = max(10, min(int(delta), 2000))
        self._replay_apply_row(self._replay_idx)
        self._replay_idx += 1
        self._tl_update()
        self._poll_status.set(
            f"replay: row {self._replay_idx}/{len(self._replay_data)}")
        self._fvar.set(
            f"Replaying log  ·  row {self._replay_idx}/{len(self._replay_data)}")
        self._replay_after_id = self.after(delay_ms, self._replay_step)

    def _replay_apply_row(self, idx):
        if not self._replay_data or idx < 0 or idx >= len(self._replay_data):
            return
        ts_str, readings = self._replay_data[idx]
        for sensor_id, phys in readings.items():
            g = self._gauges.get(sensor_id)
            if g is not None:
                g.update_value(phys, 0)
        if hasattr(self, '_replay_shared_idx') and self._replay_shared_idx is not None:
            try:
                self._replay_shared_idx.value = idx
            except Exception:
                pass

    def _replay_seek(self, idx):
        was_playing = self._replay_state == "playing"
        if was_playing:
            if self._replay_after_id:
                self.after_cancel(self._replay_after_id)
                self._replay_after_id = None
        idx = max(0, min(idx, len(self._replay_data) - 1))
        self._replay_idx = idx
        self._replay_apply_row(idx)
        self._tl_update()
        self._poll_status.set(
            f"replay: row {self._replay_idx + 1}/{len(self._replay_data)}")
        if was_playing:
            self._replay_idx += 1
            self._replay_after_id = self.after(30, self._replay_step)

    def _replay_jump_start(self):
        if not self._replay_data:
            return
        if self._replay_state == "playing":
            if self._replay_after_id:
                self.after_cancel(self._replay_after_id)
                self._replay_after_id = None
            self._replay_state = "paused"
            self._tl_play_btn.configure(text="▶", fg=SUCCESS)
        self._replay_idx = 0
        self._replay_apply_row(0)
        self._tl_update()
        self._poll_status.set(
            f"replay: row 1/{len(self._replay_data)}")
        self._fvar.set(
            f"Replay  ·  row 1/{len(self._replay_data)}  ·  start")

    def _replay_jump_end(self):
        if not self._replay_data:
            return
        if self._replay_state == "playing":
            if self._replay_after_id:
                self.after_cancel(self._replay_after_id)
                self._replay_after_id = None
            self._replay_state = "paused"
            self._tl_play_btn.configure(text="▶", fg=SUCCESS)
        last = len(self._replay_data) - 1
        self._replay_idx = last
        self._replay_apply_row(last)
        self._tl_update()
        self._poll_status.set(
            f"replay: row {last + 1}/{len(self._replay_data)}")
        self._fvar.set(
            f"Replay  ·  row {last + 1}/{len(self._replay_data)}  ·  end")

    def _replay_finish(self):
        if self._replay_after_id:
            self.after_cancel(self._replay_after_id)
            self._replay_after_id = None
        self._replay_state = "paused"
        self._replay_idx = len(self._replay_data)
        self._tl_play_btn.configure(text="▶", fg=SUCCESS)
        self._tl_update()
        self._fvar.set(
            f"Replay finished  ·  {len(self._replay_data)} rows")
        self._evt("Replay reached end", "ok")

    def _parse_replay_ts(self, ts_str):
        return self._parse_replay_ts_static(ts_str)

    # ── Timeline bar drawing and interaction ──
    def _tl_format_time(self, idx):
        if not self._replay_data or idx < 0 or idx >= len(self._replay_data):
            return "00:00"
        ts_str = self._replay_data[idx][0]
        ts = self._parse_replay_ts(ts_str)
        if ts and self._replay_t0:
            delta = (ts - self._replay_t0).total_seconds()
            m, s = divmod(max(0, int(delta)), 60)
            return f"{m:02d}:{s:02d}"
        return "00:00"

    def _tl_total_time(self):
        if self._replay_t0 and self._replay_tN:
            delta = (self._replay_tN - self._replay_t0).total_seconds()
            m, s = divmod(max(0, int(delta)), 60)
            return f"{m:02d}:{s:02d}"
        return "00:00"

    def _tl_update(self):
        if not self._replay_data:
            return
        total = len(self._replay_data)
        idx = max(0, min(self._replay_idx, total - 1))
        frac = idx / max(1, total - 1) if total > 1 else 0
        elapsed = self._tl_format_time(idx)
        duration = self._tl_total_time()
        self._tl_time_var.set(f"{elapsed} / {duration}")
        self._tl_row_var.set(f"{idx + 1} / {total}")
        self._tl_draw_bar(frac)

    def _tl_draw_bar(self, frac):
        c = self._tl_canvas
        c.delete("all")
        w = self._tl_canvas_w
        h = c.winfo_height() or 22
        cy = h // 2
        track_y0, track_y1 = cy - 3, cy + 3
        c.create_rectangle(0, track_y0, w, track_y1, fill=BORDER, outline="")
        fill_x = int(frac * w)
        if fill_x > 0:
            c.create_rectangle(0, track_y0, fill_x, track_y1,
                               fill=ACCENT, outline="")
        thumb_r = 6
        tx = max(thumb_r, min(fill_x, w - thumb_r))
        c.create_oval(tx - thumb_r, cy - thumb_r, tx + thumb_r, cy + thumb_r,
                      fill=ACCENT, outline=STRIP_BG, width=1)

    def _tl_on_resize(self, event):
        self._tl_canvas_w = event.width
        if self._replay_data:
            self._tl_update()

    def _tl_idx_from_x(self, x):
        w = self._tl_canvas_w or 1
        frac = max(0.0, min(1.0, x / w))
        total = len(self._replay_data)
        return int(frac * max(0, total - 1))

    def _tl_on_click(self, event):
        if not self._replay_data:
            return
        self._tl_dragging = True
        idx = self._tl_idx_from_x(event.x)
        self._replay_seek(idx)

    def _tl_on_drag(self, event):
        if not self._replay_data or not self._tl_dragging:
            return
        was_playing = self._replay_state == "playing"
        if was_playing:
            if self._replay_after_id:
                self.after_cancel(self._replay_after_id)
                self._replay_after_id = None
            self._replay_state = "paused"
            self._tl_play_btn.configure(text="▶", fg=SUCCESS)
        idx = self._tl_idx_from_x(event.x)
        self._replay_idx = max(0, min(idx, len(self._replay_data) - 1))
        self._replay_apply_row(self._replay_idx)
        self._tl_update()
        self._poll_status.set(
            f"replay: row {self._replay_idx + 1}/{len(self._replay_data)}")
        self._fvar.set(
            f"Replay  ·  row {self._replay_idx + 1}/{len(self._replay_data)}")

    # ── Drain main-thread queue ──
    def _drain_queue(self):
        try:
            while True:
                item = self._pkt_queue.get_nowait()
                kind = item[0]
                data = item[1] if len(item) > 1 else None

                if kind == "connected":
                    ip, port = data
                    if self._replay_state != "idle":
                        self._disconnect()
                        self._cbtn.configure(state="disabled", bg=BTN_BG, fg=DIM, text="⬡  CONNECT")
                        continue
                    was_reconnecting = self._stall_reconnecting
                    self._stall_reconnecting = False
                    self._evt(f"TCP connected {ip}:{port}", "ok")
                    self._cbtn.configure(text="■  DISCONNECT", bg=ERROR_C)
                    self._sdot.configure(fg=SUCCESS)
                    self._slbl.configure(fg=SUCCESS, text="LIVE")
                    self._fvar.set(f"Connected  {ip}:{port}  ·  HSFZ/UDS active")
                    self._poll_btn.configure(state="normal", fg=TEXT)
                    self._log_btn.configure(state="normal", fg=TEXT)
                    if was_reconnecting and self._polling:
                        self._poll_pending = None
                        self._last_gauge_update = time.monotonic()
                        self._poll_next()

                elif kind == "disconnected":
                    if self._stall_reconnecting:
                        self._evt("Reconnecting…", "warn")
                    else:
                        self._evt("Disconnected", "warn")
                        self._running = False; self._sock = None; self._polling = False
                        if self._logging: self._log_stop()
                        cbtn_bg = BTN_BG if self._replay_state != "idle" else ACCENT
                        self._cbtn.configure(text="⬡  CONNECT", bg=cbtn_bg)
                        self._sdot.configure(fg=DIM)
                        self._slbl.configure(fg=DIM, text="OFFLINE")
                        self._fvar.set("Offline  ·  BMW F10 ENET Dashboard")
                        self._poll_btn.configure(text="▶  START POLLING",
                                                bg=BTN_BG, fg=DIM, state="disabled")
                        self._log_btn.configure(text="⏺  START LOGGING",
                                               bg=BTN_BG, fg=DIM, state="disabled")
                        for g in self._gauges.values():
                            if g is not None:
                                g.set_stale()
                        self._vin_var.set("——————————————————")

                elif kind == "ecu_reset":
                    self._evt("Gateway reset detected — re-establishing session…", "warn")
                    self._pkt_queue.put(("reinit", None))

                elif kind == "nrc":
                    nrc_bytes = data
                    nrc_code  = nrc_bytes[2] if len(nrc_bytes) >= 3 else 0
                    svc       = nrc_bytes[1] if len(nrc_bytes) >= 2 else 0
                    self._evt(f"NRC 0x{nrc_code:02X} svc 0x{svc:02X} — skipping", "warn")
                    if self._poll_timeout_id:
                        self.after_cancel(self._poll_timeout_id)
                        self._poll_timeout_id = None
                    self._poll_pending = None
                    self.after(self._poll_delay, self._poll_next)

                elif kind == "vin":
                    self._vin = data
                    self._vin_var.set(data)
                    self._evt(f"VIN: {data}", "vin")

                elif kind == "sensor":
                    value_bytes, snapshot = data, item[2]
                    did, sz, scale_fn, sensor_id, gen, ecu = snapshot
                    if gen != self._poll_gen:
                        continue
                    self._do_send(ecu, bytes([0x2C, 0x03, DYN_H, DYN_L]))
                    if self._poll_timeout_id:
                        self.after_cancel(self._poll_timeout_id)
                        self._poll_timeout_id = None
                    self._stall_count = 0
                    now = time.monotonic()
                    self._last_gauge_update = now
                    if self._last_sensor_time is not None:
                        ms = (now - self._last_sensor_time) * 1000
                        self._delay_samples.append(ms)
                        if len(self._delay_samples) > 30:
                            self._delay_samples.pop(0)
                        avg = sum(self._delay_samples) / len(self._delay_samples)
                        self._delay_var.set(f"{avg:.1f} ms")
                    self._last_sensor_time = now
                    raw = int.from_bytes(value_bytes[:sz], "big")
                    try: phys = scale_fn(raw)
                    except Exception: phys = float(raw)
                    g = self._gauges.get(sensor_id)
                    if g is not None:
                        g.update_value(phys, raw)
                    self._log_write(sensor_id, phys)
                    s = get_sensor_by_id(sensor_id)
                    lbl = s["label"] if s else sensor_id
                    self._poll_status.set(
                        f"last: {lbl} = {phys:.2f}  raw={raw}  DID=0x{did:04X}")

                elif kind == "discover_result":
                    self._discovering = False
                    self._discover_btn.configure(
                        text="🔍", fg=TEXT, state="normal")
                    if data:
                        self._ip_var.set(data)
                        self._evt(f"Found BMW at {data}", "ok")
                    else:
                        self._evt("No BMW found on network", "err")

                elif kind == "err":
                    self._evt(str(data), "err")
                    self._running = False; self._sock = None; self._polling = False
                    cbtn_bg = BTN_BG if self._replay_state != "idle" else ACCENT
                    self._cbtn.configure(text="⬡  CONNECT", bg=cbtn_bg)
                    self._sdot.configure(fg=DIM)
                    self._slbl.configure(fg=DIM, text="OFFLINE")
                    self._poll_btn.configure(text="▶  START POLLING",
                                            bg=BTN_BG, fg=DIM, state="disabled")

        except queue.Empty:
            pass
        finally:
            self.after(10, self._drain_queue)


def main():
    multiprocessing.freeze_support()
    Dashboard().mainloop()
