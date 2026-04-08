"""Gauge profile schema, validation, and JSON persistence."""
import json

from .sensors import get_sensor_by_id, sensor_id_at

VALID_KINDS = ("circular", "bar", "digital")

DEFAULT_GAUGE_PROFILE = {
    "version": 2,
    "gauges": [
        {"sensor_id": "engine_rpm",       "kind": "circular", "relx": 0.000, "rely": 0.000, "relwidth": 0.325, "relheight": 0.325},
        {"sensor_id": "battery_voltage",  "kind": "circular", "relx": 0.000, "rely": 0.325, "relwidth": 0.325, "relheight": 0.325},
        {"sensor_id": "throttle_angle",   "kind": "digital",  "relx": 0.000, "rely": 0.650, "relwidth": 0.325, "relheight": 0.325},
        {"sensor_id": "oil_pressure",     "kind": "circular", "relx": 0.325, "rely": 0.000, "relwidth": 0.325, "relheight": 0.300},
        {"sensor_id": "boost_pressure",   "kind": "circular", "relx": 0.325, "rely": 0.300, "relwidth": 0.325, "relheight": 0.300},
        {"sensor_id": "lp_fuel_pressure", "kind": "bar",      "relx": 0.325, "rely": 0.600, "relwidth": 0.325, "relheight": 0.125},
        {"sensor_id": "hp_rail_pressure", "kind": "bar",      "relx": 0.325, "rely": 0.725, "relwidth": 0.325, "relheight": 0.125},
        {"sensor_id": "intake_pressure",  "kind": "bar",      "relx": 0.325, "rely": 0.850, "relwidth": 0.325, "relheight": 0.125},
        {"sensor_id": "engine_oil_temp",  "kind": "circular", "relx": 0.650, "rely": 0.000, "relwidth": 0.325, "relheight": 0.325},
        {"sensor_id": "coolant_temp",     "kind": "circular", "relx": 0.650, "rely": 0.325, "relwidth": 0.325, "relheight": 0.325},
        {"sensor_id": "valvetronic_angle","kind": "digital",  "relx": 0.650, "rely": 0.650, "relwidth": 0.325, "relheight": 0.325},
    ],
}


def _migrate_entry(g, idx):
    """Convert a legacy ``sensor_index`` entry to ``sensor_id``."""
    if "sensor_id" in g:
        return g
    legacy_idx = g.get("sensor_index")
    if isinstance(legacy_idx, int):
        sid = sensor_id_at(legacy_idx)
        if sid:
            migrated = dict(g)
            migrated["sensor_id"] = sid
            migrated.pop("sensor_index", None)
            return migrated
    return None


def validate_profile(profile):
    """Return ``(ok, error_message)``."""
    if not isinstance(profile, dict):
        return False, "Profile must be a dict"
    if "gauges" not in profile:
        return False, "Missing 'gauges' key"
    gauges = profile["gauges"]
    if not isinstance(gauges, list):
        return False, "'gauges' must be a list"
    seen = set()
    for i, g in enumerate(gauges):
        g = _migrate_entry(g, i)
        if g is None:
            return False, f"Entry {i}: cannot resolve sensor"
        sid = g.get("sensor_id")
        if not sid or get_sensor_by_id(sid) is None:
            return False, f"Entry {i}: unknown sensor_id '{sid}'"
        if sid in seen:
            return False, f"Entry {i}: duplicate sensor_id '{sid}'"
        seen.add(sid)
        kind = g.get("kind")
        if kind not in VALID_KINDS:
            return False, f"Entry {i}: invalid kind '{kind}'"
        for key in ("relx", "rely", "relwidth", "relheight"):
            v = g.get(key)
            if not isinstance(v, (int, float)) or v < 0 or v > 1:
                return False, f"Entry {i}: invalid {key}={v}"
    return True, ""


def normalize_profile(profile):
    """Return a profile with all entries migrated to ``sensor_id``."""
    gauges = []
    for i, g in enumerate(profile.get("gauges", [])):
        migrated = _migrate_entry(g, i)
        if migrated is not None:
            sid = migrated.get("sensor_id")
            if sid and get_sensor_by_id(sid) is not None:
                gauges.append(migrated)
    return {"version": 2, "gauges": gauges}


def load_profile(path):
    """Load, validate, and migrate a profile from JSON.  Returns dict or None."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            profile = json.load(f)
    except Exception:
        return None
    ok, _msg = validate_profile(profile)
    if not ok:
        norm = normalize_profile(profile)
        if norm["gauges"]:
            return norm
        return None
    return normalize_profile(profile)


def save_profile(profile, path):
    """Write profile dict as pretty-printed JSON."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2)
