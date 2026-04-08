# -*- coding: utf-8 -*-
"""Sensor definitions: JSON-backed store with CRUD operations.

Loads sensor definitions from ``sensor.json`` at startup and maintains a
backward-compatible ``SENSORS`` tuple list that is rebuilt in-place whenever
the registry changes (so every module that imported it sees the update).
"""

import json
import os
import re
import sys

_DEG_C = "\u00b0C"

# ── Path resolution ──────────────────────────────────────
def _resolve_sensor_json_path():
    """Return path to sensor.json beside the exe (frozen) or at project root."""
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "sensor.json")
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "..", "sensor.json"))


# ── Scale function builder ───────────────────────────────
def _make_scale_fn(scale, offset=0.0):
    """Build a linear scale closure: ``phys = raw * scale + offset``."""
    if offset:
        def _fn(raw):
            return raw * scale + offset
    else:
        def _fn(raw):
            return raw * scale
    return _fn


# ── Internal registry ────────────────────────────────────
_sensor_list = []   # ordered list of sensor dicts
_sensor_map = {}    # sensor_id -> sensor dict

# Backward-compatible tuple list.  Mutated **in-place** so every module that
# did ``from .sensors import SENSORS`` keeps a live reference to the same
# object.
SENSORS = []


def _rebuild_compat():
    """Rebuild *SENSORS* from ``_sensor_list`` without replacing the object."""
    SENSORS.clear()
    for s in _sensor_list:
        scale_fn = _make_scale_fn(s.get("scale", 1.0), s.get("offset", 0.0))
        SENSORS.append((
            s["label"],
            s["did"],
            s["ecu"],
            s["size"],
            scale_fn,
            s["unit"],
            s.get("min", 0),
            s["max"],
            s.get("warn", s["max"] * 0.8),
            s.get("danger", s["max"] * 0.9),
            s.get("decimals", 1),
        ))


# ── Validation ───────────────────────────────────────────
def _validate_sensor(s):
    """Return ``(ok, error_message)`` for a sensor dict."""
    if not isinstance(s, dict):
        return False, "Sensor must be a dict"
    for key in ("sensor_id", "label", "did", "ecu", "size", "unit", "max"):
        if key not in s:
            return False, f"Missing required field: {key}"
    if not isinstance(s["sensor_id"], str) or not s["sensor_id"].strip():
        return False, "sensor_id must be a non-empty string"
    if not isinstance(s["did"], int) or s["did"] < 0:
        return False, "did must be a non-negative integer"
    if not isinstance(s["ecu"], int) or s["ecu"] < 0:
        return False, "ecu must be a non-negative integer"
    if not isinstance(s["size"], int) or s["size"] < 1:
        return False, "size must be a positive integer"
    return True, ""


# ── Public API ───────────────────────────────────────────
def load_sensors(path=None):
    """Load sensors from *sensor.json*.  Returns ``(ok, error_message)``."""
    global _sensor_list, _sensor_map
    if path is None:
        path = _resolve_sensor_json_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return False, f"sensor.json not found at {path}"
    except Exception as e:
        return False, str(e)

    sensors = data.get("sensors", [])
    if not isinstance(sensors, list):
        return False, "'sensors' must be a list"

    loaded, seen_ids = [], set()
    for i, s in enumerate(sensors):
        ok, msg = _validate_sensor(s)
        if not ok:
            return False, f"Sensor {i}: {msg}"
        sid = s["sensor_id"]
        if sid in seen_ids:
            return False, f"Duplicate sensor_id: {sid}"
        seen_ids.add(sid)
        loaded.append(s)

    _sensor_list = loaded
    _sensor_map = {s["sensor_id"]: s for s in _sensor_list}
    _rebuild_compat()
    return True, ""


def save_sensors(path=None):
    """Persist the current sensor registry to *sensor.json*."""
    if path is None:
        path = _resolve_sensor_json_path()
    data = {"sensors": _sensor_list}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_sensors():
    """Return a shallow copy of the current sensor list (list of dicts)."""
    return list(_sensor_list)


def get_sensor_by_id(sensor_id):
    """Lookup a sensor dict by its stable ID, or ``None``."""
    return _sensor_map.get(sensor_id)


def sensor_id_at(index):
    """Return the ``sensor_id`` at the given list position, or ``None``."""
    if 0 <= index < len(_sensor_list):
        return _sensor_list[index]["sensor_id"]
    return None


def index_of(sensor_id):
    """Return the current list index for a *sensor_id*, or ``-1``."""
    for i, s in enumerate(_sensor_list):
        if s["sensor_id"] == sensor_id:
            return i
    return -1


def generate_sensor_id(label):
    """Derive a unique ``sensor_id`` slug from a human label."""
    sid = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    if not sid:
        sid = "sensor"
    base = sid
    n = 1
    while sid in _sensor_map:
        sid = f"{base}_{n}"
        n += 1
    return sid


def add_sensor(sensor_dict):
    """Add a new sensor and persist.  Returns ``(ok, error_msg)``."""
    ok, msg = _validate_sensor(sensor_dict)
    if not ok:
        return False, msg
    sid = sensor_dict["sensor_id"]
    if sid in _sensor_map:
        return False, f"sensor_id '{sid}' already exists"

    if "scale" not in sensor_dict:
        cal_raw = sensor_dict.get("calibration_raw", 1)
        cal_val = sensor_dict.get("calibration_value", 1)
        offset = sensor_dict.get("offset", 0.0)
        sensor_dict["scale"] = (cal_val - offset) / cal_raw if cal_raw else 1.0

    sensor_dict.setdefault("offset", 0.0)
    sensor_dict.setdefault("min", 0)
    sensor_dict.setdefault("warn", sensor_dict["max"] * 0.8)
    sensor_dict.setdefault("danger", sensor_dict["max"] * 0.9)
    sensor_dict.setdefault("decimals", 1)

    _sensor_list.append(sensor_dict)
    _sensor_map[sid] = sensor_dict
    _rebuild_compat()
    save_sensors()
    return True, ""


def update_sensor(sensor_id, updates):
    """Update fields of an existing sensor and persist.  Returns ``(ok, error_msg)``."""
    s = _sensor_map.get(sensor_id)
    if s is None:
        return False, f"sensor_id '{sensor_id}' not found"

    new = dict(s)
    new.update(updates)
    new["sensor_id"] = sensor_id  # prevent ID mutation

    ok, msg = _validate_sensor(new)
    if not ok:
        return False, msg

    if "calibration_raw" in updates or "calibration_value" in updates or "offset" in updates:
        cal_raw = new.get("calibration_raw", 1)
        cal_val = new.get("calibration_value", 1)
        offset = new.get("offset", 0.0)
        new["scale"] = (cal_val - offset) / cal_raw if cal_raw else 1.0

    for i, existing in enumerate(_sensor_list):
        if existing["sensor_id"] == sensor_id:
            _sensor_list[i] = new
            break
    _sensor_map[sensor_id] = new
    _rebuild_compat()
    save_sensors()
    return True, ""


def delete_sensor(sensor_id):
    """Remove a sensor by ID and persist.  Returns ``(ok, error_msg)``."""
    if sensor_id not in _sensor_map:
        return False, f"sensor_id '{sensor_id}' not found"
    _sensor_list[:] = [s for s in _sensor_list if s["sensor_id"] != sensor_id]
    del _sensor_map[sensor_id]
    _rebuild_compat()
    save_sensors()
    return True, ""


# ── Built-in defaults (used when sensor.json is missing) ─
_BUILTIN_DEFAULTS = [
    {"sensor_id": "engine_rpm",       "label": "Engine RPM",       "did": 0x4807, "ecu": 0x12, "size": 2, "unit": "RPM",    "min": 0,  "max": 8000, "warn": 5500,  "danger": 7000,  "decimals": 0, "scale": 0.25,         "offset": 0.0,  "calibration_raw": 3374,  "calibration_value": 843.5},
    {"sensor_id": "battery_voltage",  "label": "Battery Voltage",  "did": 0x5815, "ecu": 0x12, "size": 1, "unit": "V",      "min": 9,  "max": 16,   "warn": 14.8,  "danger": 11.0,  "decimals": 2, "scale": 0.1,          "offset": 0.0,  "calibration_raw": 147,   "calibration_value": 14.7},
    {"sensor_id": "lp_fuel_pressure", "label": "LP Fuel Pressure", "did": 0x58F3, "ecu": 0x12, "size": 2, "unit": "PSI",    "min": 0,  "max": 145,  "warn": 116,   "danger": 130,   "decimals": 1, "scale": 0.0145038,    "offset": 0.0,  "calibration_raw": 6015,  "calibration_value": 87.23},
    {"sensor_id": "hp_rail_pressure", "label": "HP Rail Pressure", "did": 0x58F0, "ecu": 0x12, "size": 2, "unit": "PSI",    "min": 0,  "max": 2900, "warn": 2610,  "danger": 2830,  "decimals": 1, "scale": 0.0725,       "offset": 0.0,  "calibration_raw": 10230, "calibration_value": 741.68},
    {"sensor_id": "coolant_temp",     "label": "Coolant Temp",     "did": 0x4300, "ecu": 0x12, "size": 1, "unit": _DEG_C,   "min": 0,  "max": 130,  "warn": 100,   "danger": 115,   "decimals": 1, "scale": 0.5,          "offset": -3.5, "calibration_raw": 207,   "calibration_value": 100.0},
    {"sensor_id": "oil_pressure",     "label": "Oil Pressure",     "did": 0x586F, "ecu": 0x12, "size": 2, "unit": "PSI",    "min": 0,  "max": 90,   "warn": 75,    "danger": 85,    "decimals": 1, "scale": 0.0145675,    "offset": 0.0,  "calibration_raw": 2732,  "calibration_value": 39.80},
    {"sensor_id": "engine_oil_temp",  "label": "Engine Oil Temp",  "did": 0x4402, "ecu": 0x12, "size": 2, "unit": _DEG_C,   "min": 0,  "max": 150,  "warn": 120,   "danger": 135,   "decimals": 1, "scale": 0.51275510,   "offset": 0.0,  "calibration_raw": 196,   "calibration_value": 100.50},
    {"sensor_id": "boost_pressure",   "label": "Boost Pressure",   "did": 0x58DD, "ecu": 0x12, "size": 2, "unit": "PSI",    "min": 0,  "max": 30,   "warn": 25,    "danger": 28,    "decimals": 2, "scale": 0.00113310,   "offset": 0.0,  "calibration_raw": 12985, "calibration_value": 14.71},
    {"sensor_id": "throttle_angle",   "label": "Throttle Angle",   "did": 0x4600, "ecu": 0x12, "size": 2, "unit": "%",      "min": 0,  "max": 100,  "warn": 90,    "danger": 95,    "decimals": 1, "scale": 0.02437500,   "offset": 0.0,  "calibration_raw": 112,   "calibration_value": 2.73},
    {"sensor_id": "intake_pressure",  "label": "Intake Pressure",  "did": 0x580B, "ecu": 0x12, "size": 2, "unit": "PSI",    "min": 0,  "max": 15,   "warn": 13,    "danger": 14,    "decimals": 2, "scale": 0.00056536,   "offset": 0.0,  "calibration_raw": 24752, "calibration_value": 13.99},
    {"sensor_id": "valvetronic_angle","label": "Valvetronic Angle", "did": 0x58A2, "ecu": 0x12, "size": 2, "unit": "deg",   "min": 0,  "max": 60,   "warn": 50,    "danger": 55,    "decimals": 1, "scale": 0.10000000,   "offset": 0.0,  "calibration_raw": 253,   "calibration_value": 25.30},
]


# ── Module initialisation ────────────────────────────────
_init_ok, _init_msg = load_sensors()
if not _init_ok:
    # sensor.json missing or invalid — seed from built-in defaults
    _sensor_list = [dict(s) for s in _BUILTIN_DEFAULTS]
    _sensor_map = {s["sensor_id"]: s for s in _sensor_list}
    _rebuild_compat()
    try:
        save_sensors()
    except Exception:
        pass
