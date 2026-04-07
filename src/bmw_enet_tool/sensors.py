# -*- coding: utf-8 -*-
# Sensor definitions (same data as sourcecode/bmw_dashboard.py).
#
# Each entry: (label, did, ecu, size, scale_fn, unit, lo, hi, warn, danger, decimals)
# scale_fn(raw_int) -> float physical value


def _rpm(r):
    return r * 0.25  # confirmed: 3374 raw -> 843.5 RPM


def _bat(r):
    return r * 0.1  # confirmed: 147 raw -> 14.70 V


def _lp(r):
    return r * 0.0145038  # confirmed: 6015 raw -> 87.23 PSI


def _hp(r):
    return r * 0.0725  # confirmed: 10230 raw -> 741.68 PSI


def _clt(r):
    return r * 0.5 - 3.5  # confirmed with offset correction


def _oil(r):
    return r * 0.0145675  # confirmed: 2732 raw -> 39.80 PSI


def _oilt(r):
    return r * 0.51275510  # confirmed: 196 raw -> 100.50 deg C


def _bst(r):
    return r * 0.00113310  # confirmed: 12985 raw -> 14.71 PSI


def _thr(r):
    return r * 0.02437500  # confirmed: 112 raw -> 2.73 %


def _ivac(r):
    return r * 0.00056536  # confirmed: 24752 raw -> 13.99 PSI


def _vtec(r):
    return r * 0.10000000  # confirmed: 253 raw -> 25.30 deg


# Unit uses Unicode degree sign via escape (avoids cp1252/utf-8 mismatch on Windows).
_DEG_C = "\u00b0C"

SENSORS = [
    # label                   DID     ECU   sz  scale   unit    lo      hi    warn   danger  dec
    ("Engine RPM", 0x4807, 0x12, 2, _rpm, "RPM", 0, 8000, 5500, 7000, 0),
    ("Battery Voltage", 0x5815, 0x12, 1, _bat, "V", 9, 16, 14.8, 11.0, 2),
    ("LP Fuel Pressure", 0x58F3, 0x12, 2, _lp, "PSI", 0, 145, 116, 130, 1),
    ("HP Rail Pressure", 0x58F0, 0x12, 2, _hp, "PSI", 0, 2900, 2610, 2830, 1),
    ("Coolant Temp", 0x4300, 0x12, 1, _clt, _DEG_C, 0, 130, 100, 115, 1),
    ("Oil Pressure", 0x586F, 0x12, 2, _oil, "PSI", 0, 90, 75, 85, 1),
    ("Engine Oil Temp", 0x4402, 0x12, 2, _oilt, _DEG_C, 0, 150, 120, 135, 1),
    ("Boost Pressure", 0x58DD, 0x12, 2, _bst, "PSI", 0, 30, 25, 28, 2),
    ("Throttle Angle", 0x4600, 0x12, 2, _thr, "%", 0, 100, 90, 95, 1),
    ("Intake Pressure", 0x580B, 0x12, 2, _ivac, "PSI", 0, 15, 13, 14, 2),
    ("Valvetronic Angle", 0x58A2, 0x12, 2, _vtec, "deg", 0, 60, 50, 55, 1),
]
