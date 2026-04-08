# BMW ENET Live Sensor Dashboard - N55 Engine

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://python.org)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-green.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Real-time engine sensor monitoring for BMW N55 engines via ENET interface**

---

## Table of Contents

- [Demo](#demo)
- [Overview](#overview)
- [Features](#features)
- [Technical Architecture](#technical-architecture)
- [Development Journey](#development-journey)
- [Installation](#installation)
- [Usage](#usage)
- [Contributing](#contributing)
- [License](#license)

---

## Demo

### Live Dashboard with Log Replay Feature

![Replay GIF](/media/bmw-dashboard.gif)

### Interactive Log Viewer

![Log Viewer](/media/bmwenetlogger.PNG)

---

## Overview

This project provides a **live, real-time dashboard** for monitoring BMW N55 engine sensors through the ENET (Ethernet) diagnostic interface. Built from scratch after extensive reverse-engineering of BMW's HSFZ/UDS protocol, it delivers professional-grade telemetry without expensive commercial tools.

**Why this exists:** Commercial diagnostic tools are expensive (I was unable to find one without payment) and often don't provide the level of real-time data visualization and logging capability needed for diagnostics. This solution fills that gap with an open-source, customizable alternative. Although this program only supports F chassis N55 engines due to how I reverse engineered the ENET communication protocol, I did not add decoding for every type of sensor. You can request changes or apply them yourself with a github pull request.

**Main problem I was trying to solve:** is figuring out why my engine sometimes stumbles on coldstarts when the weather is below 0c. This happens consistently on every coldstart of the day on my n55, and I wanted to be able to log all the engine information to see what is going on. Unfortunately, I could not find a single free logging tool out there. So I resorted to making my own. 

**Here is the cold start stumble:**
[![Watch the video](https://img.youtube.com/vi/QyVEl4P64RY/maxresdefault.jpg)](https://youtu.be/QyVEl4P64RY)

The issue is determined to be (drumroll please): Pressure sag on the low pressure fuel pump due to voltage sag. When the engine starts up in cold weather, the battery voltage sags down to 11 volts. At the same time the engine high pressure fuel pump is pulling fuel away from the low pressure supply, and the voltage sag is reducing the low pressure supply by reducing the power to the low pressure fuel pump. As a result, we get this odd startup stumble as the engine is starved for fuel:

![image](/media/fuelpressuredrop.PNG)

---

## Features

- **🔌 Live Sensor Monitoring** - Real-time data from built-in engine parameters (and any sensors you define). Disable sensors by clicking their gauge or the sensor list row
- **➕ User-Defined Sensors** - **Add**, **edit**, or **delete** sensors in the UI: label, DID (hex), ECU address, response size, units, gauge range, warning/danger thresholds, and calibration (raw hex → physical value). Each sensor gets a stable **`sensor_id`** used everywhere in the app and in saved layouts
- **🎚️ Tk Canvas Gauge Surface** - Gauges are drawn on a **`tk.Canvas`**-based tile grid (circular, digital, bar styles), with layout saved per **`sensor_id`** in JSON profiles not hard-coded widget_positions so custom sensors slot into the same system as the defaults
- **💾 JSONL Logging** - Logs are **newline-delimited JSON** (`.jsonl`): a header object (version, sensor metadata + **`sensor_id`**), then one JSON object per timestamp with all current readings keyed by **`sensor_id`**. Millisecond timestamps, easy to parse and extend. **Legacy CSV logs** still load in the plot viewer for older recordings
- **🔄 Log Replay** - Replay recorded sessions with synchronized cursor. ENET disconnects while replay is active
- **📈 Interactive Plotter** - Time-series visualization with zoom/pan; show/hide sensors from the legend. Works with **JSONL** and **CSV**
- **🎯 Auto-Discovery** - Automatic detection of BMW ENET interface. Will scan the usual expected port range from 169.254.x.xxx. Generally all F chassis cars have a similar or same port 6801
- **⚡ High Performance** - Sub-90ms sensor polling intervals. De-activating sensors speeds up polling for the rest
- **🎨 Dark Theme UI** - “Precision Dark” instrument look. List areas use a **custom canvas-drawn scrollbar** (native `tk.Scrollbar` does not honor dark colours reliably on Windows)
- **⚠️ Warning Indicators** - Visual alerts for out-of-range values based on per-sensor thresholds

---

## Technical Architecture

### TCP packet format:

```text
PC → Car:  00 00 00 05 00 01 f4 12 22 f3 00      (Read DID F300)
Car → PC:  00 00 00 05 00 02 f4 12 22 f3 00      (ZGW echo)
Car → PC:  00 00 00 06 00 01 12 f4 62 f3 00 42   (ECU response: value = 0x42)

PC → Car:  00 00 00 06 00 01 f4 12 2c 03 f3 00   (Define data block by DID F300)
Car → PC:  00 00 00 06 00 02 f4 12 2c 03 f3 00   (ZGW echo)
Car → PC:  00 00 00 06 00 01 12 f4 6c 03 f3 00   (ECU response: block defined)

PC → Car:  00 00 00 0a 00 01 f4 12 2c 01 f3 00 44 02 01 02  (Read data block)
Car → PC:  00 00 00 07 00 02 f4 12 2c 01 f3 00 44            (ZGW echo)
Car → PC:  00 00 00 06 00 01 12 f4 6c 01 f3 00               (ECU response: sending data)
```

### Protocol Stack
![stack](/media/protocolstack1.png)

            
## Development Journey

### Challenge 1: Protocol Discovery
Approach:
Captured network traffic using Wireshark
- Analyzed ISTA/D diagnostic software behavior for initial TCP handshake
- Reverse-engineered HSFZ frame structure

Key Findings:
- HSFZ uses 6-byte header: 4-byte length + 2-byte message type
- Type 0x0001 = real ECU data
- Type 0x0002 = gateway echo (must be ignored)
- UDS service 0x2C allows dynamic DID definition

**Packet Construction:**

```python
def hsfz(src, dst, uds: bytes) -> bytes:
    body = bytes([src, dst]) + uds
    return struct.pack(">I", len(body)) + b"\x00\x01" + body
```

**Capturing and replaying handshake packets:**

![image](/media/IMG20260303211802.jpg)


### Challenge 2: Sensor Mapping

Approach:
- Sniff ISTA network messages and map them to sensor definitions
- Cross-referenced community documentation (Bimmerforums, NCSExpert forums)
- Validated scale factors against known conditions

Challenges:
- Many scale factors were estimates from community docs
- Needed real-world validation (e.g., battery at rest ≈ 12.5V)
- Some DIDs returned unexpected data formats

All of the mapping and sensor value decoding was done using wireshark and packet inspection, corrosponding to their live-data view displayed in BMW/ISTA

![image](/media/IMG20260303182619.jpg)

## Challenge 3: Silent Recovery

HSFZ gateway sends echo frames (type 0x0002) that corrupted data parsing. so in the packet parser, I filter message types and ignore echo frames.

Additionally, sometimes the ECU sometimes stops responding after 2-3 seconds, requiring manual reconnect. So I implemented a timeout watchdog with auto reconnect based on the last received message

```python
def _poll_stall_timeout(self, gen: int):
    """ECU didn't respond within 500ms — reconnect"""
    if gen != self._poll_gen:
        return  # Response arrived late
    self._evt("ECU stall — reconnecting…", "warn")
    threading.Thread(target=_do_reconnect, daemon=True).start()
```

Also ran into some issues with the socket thread and GUI thread competing for resource accesses, so there is a drain queue implemented that clears itself every 10ms.

```python
self._pkt_queue = queue.Queue()
# Worker thread puts messages
self._pkt_queue.put(("sensor", uds[3:], snapshot))
# GUI thread drains queue
self.after(10, self._drain_queue)
```

## Challenge 4: Optimizations and Logging

We have:
- Threaded socket handling - Network I/O separate from GUI
- Queue-based communication - Thread-safe data passing
- Polling state machine - Define → Read → Clear cycle
- Watchdog timer - Auto-recovery from ECU stalls

And logging capabilities:
- **JSONL** logging with millisecond timestamps, discrete **`sensor_id`** keys, and a structured header line
- Multiprocess log viewer (doesn't block main dashboard)
- Shared memory for cursor synchronization during replay
- Multiple visualization modes (Raw, Min-Max %, Z-Score, Dual-Y)

```python
# Dashboard → Viewer sync via shared memory
self._replay_shared_idx = multiprocessing.Value('i', 0)
p = multiprocessing.Process(
    target=_launch_log_viewer_synced,
    args=(path, self._replay_shared_idx)
)
```

## Challenge 5: GUI iterations

The GUI went through several iterations before settling on a hybrid **bar**, **digital**, and **circular** gauge UI hosted on a shared **`tk.Canvas`** “gauge host” so tiles can be placed, resized, and persisted in JSON by **`sensor_id`**. Tkinter’s native **scrollbar** ignored custom colours on Windows, so the **sensor list** (and scrollable dialogs such as **add/edit sensor**) use a small **canvas-drawn scrollbar** (`CanvasScrollbar`) with theme-matched trough and thumb. The **sensor editor** is a scrollable form so long calibration sections stay usable on small displays.

![image](/media/IMG20260304003506.jpg)


## Installation

**Prerequisites**
- Python 3.8+
- BMW ENET cable (or compatible OBD-to-Ethernet adapter)
- Windows/Linux (macOS untested)

```bash
pip install numpy pandas matplotlib
```
*(Tkinter ships with most Python installs on Windows.)*

Then clone the repository, install dependencies, and run from the **`src`** folder:

```bash
git clone https://github.com/kaiwen-z/bmw-enet-tool-public-wenz77-on-bimmerforums.git
cd bmw-enet-tool-public-wenz77-on-bimmerforums/src
pip install -r requirements.txt
python -m bmw_enet_tool
```

**Building an `.exe` (PyInstaller):** from `src`, run `build_exe.bat` (see `dashboard_launcher.py`) or use `python -m PyInstaller` as documented in the batch file.

**OR** use a pre-built **`BMW_ENET_Dashboard.exe`** if you distribute a standalone build.

## Usage

**Quickstart:**

1. Connect ENET cable to BMW OBD port and ethernet port
2. Ensure the connection shows up in device manager
3. Open the bmw_dashboard program and wait on the main dashboard page
4. Click the auto-discovery tool for the IP. The port should be already correct for all N55 engines.
5. Click connect! When the connection is successful, your vin will show up in the top status bar
6. Click start polling to begin reading sensors

![image](/media/dashboard.PNG)

**Controls guide**

1. Connection panel
    - Enter IP/port or use auto-discovery (🔍 button)
    - Click CONNECT to establish TCP connection
    - VIN automatically read on connect

2. Polling Controls
    - START POLLING begins sensor reads
    - Average delay shown in header (target: <50ms)
    - Click sensor rows to enable/disable individual gauges

3. Logging
    - START LOGGING creates a timestamped **`.jsonl`** file next to the app (exe directory when frozen, or `src` when running from source)
    - Each line is JSON; the first special line is a **header** (`type: header`, sensor list with **`sensor_id`**); following lines are readings keyed by **`sensor_id`**
    - VIEW LOG opens the interactive plotter (**JSONL** or legacy **CSV**)
4. Sensors
    - Use **+ Add** / **Edit…** / **Delete…** in the sensor list to define any DID you want (hex address, ECU, size, calibration). New sensors can be added to the gauge canvas like built-ins (**sensor_id**-stable across saves)

5. Replay Mode
    - REPLAY loads existing log
    - Timeline bar appears at bottom
    - Use ⏮ ▶ ⏭ controls or drag slider
    - Spacebar toggles play/pause

6. Log Viewer
    - Click sensor rows to show/hide lines
    - Scroll wheel to zoom in/out
    - Click-drag to pan left/right
    - Bottom slider for quick navigation
    - Mode buttons: Raw | Min-Max % | Z-Score | Dual Y

**📊 Built-in sensors (extend or replace via Add / Edit in the UI)**

```text
Engine RPM — DID: 0x4807 | ECU: 0x12 | Range: 0-8000 | Unit: RPM
Battery Voltage — DID: 0x5815 | ECU: 0x12 | Range: 9-16 | Unit: V
LP Fuel Pressure — DID: 0x58F3 | ECU: 0x12 | Range: 0-145 | Unit: PSI
HP Rail Pressure — DID: 0x58F0 | ECU: 0x12 | Range: 0-2900 | Unit: PSI
Coolant Temp — DID: 0x4300 | ECU: 0x12 | Range: 0-130 | Unit: °C
Oil Pressure — DID: 0x586F | ECU: 0x12 | Range: 0-90 | Unit: PSI
Engine Oil Temp — DID: 0x4402 | ECU: 0x12 | Range: 0-150 | Unit: °C
Boost Pressure — DID: 0x58DD | ECU: 0x12 | Range: 0-30 | Unit: PSI
Throttle Angle — DID: 0x4600 | ECU: 0x12 | Range: 0-100 | Unit: %
Intake Pressure — DID: 0x580B | ECU: 0x12 | Range: 0-15 | Unit: PSI
Valvetronic Angle — DID: 0x58A2 | ECU: 0x12 | Range: 0-60 | Unit: deg
```

## Contributing

Contributions welcome! Areas needing help:
- More built-in DIDs / vehicle coverage (transmission, chassis, other engines)
- Create mobile companion app
- Packaging and docs for Linux/macOS

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

Open-source BMW ENET live dashboard and **JSONL** logger with **tk.Canvas** gauges, **user-defined sensors** (DID / ECU / calibration) keyed by **`sensor_id`**, log replay, and a matplotlib log viewer—built for real-time N55 diagnostics without extra hardware beyond an ENET cable.