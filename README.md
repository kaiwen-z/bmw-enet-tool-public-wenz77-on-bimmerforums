# BMW ENET Live Sensor Dashboard - N55 Engine

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://python.org)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-green.svg)]()
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

**Real-time engine sensor monitoring for BMW N55 engines via ENET interface**

---

## 📖 Table of Contents

- [Demo](#demo)
- [Overview](#overview)
- [Features](#features)
- [Technical Architecture](#technical-architecture)
- [Development Journey](#development-journey)
- [Challenges & Solutions](#challenges--solutions)
- [Installation](#installation)
- [Usage](#usage)
- [Supported Sensors](#supported-sensors)
- [Log Viewer](#log-viewer)
- [Contributing](#contributing)
- [License](#license)

---

## 🎬 Demo

### Live Dashboard with Log Replay Feature

![Replay GIF](/media/bmw-dashboard.gif)

### Interactive Log Viewer

![Log Viewer](/media/bmwenetlogger.PNG)

---

## 📋 Overview

This project provides a **live, real-time dashboard** for monitoring BMW N55 engine sensors through the ENET (Ethernet) diagnostic interface. Built from scratch after extensive reverse-engineering of BMW's HSFZ/UDS protocol, it delivers professional-grade telemetry without expensive commercial tools.

**Why this exists:** Commercial diagnostic tools are expensive (I was unable to find one without payment) and often don't provide the level of real-time data visualization and logging capability needed for diagnostics. This solution fills that gap with an open-source, customizable alternative. Although this program only supports F chassis N55 engines due to how I reverse engineered the ENET communication protocol, I did not add decoding for every type of sensor. You can request changes or apply them yourself with a github pull request.

**Main problem I was trying to solve:** is figuring out why my engine sometimes stumbles on coldstarts when the weather is below 0c. This happens consistently on every coldstart of the day on my n55, and I wanted to be able to log all the engine information to see what is going on. Unfortunately, I could not find a single free logging tool out there. So I resorted to making my own. 

**Here is the cold start stumble:**
[![Watch the video](https://img.youtube.com/vi/QyVEl4P64RY/maxresdefault.jpg)](https://youtu.be/QyVEl4P64RY)
---

## ✨ Features

- **🔌 Live Sensor Monitoring** - Real-time data from 11+ engine parameters. Disable sensors by clicking on their gauge or the sensor list dropdown
- **💾 CSV Logging** - Timestamped data logging for later analysis. Files are created in the same directory as the livedashboard runs
- **🔄 Log Replay** - Replay recorded sessions with synchronized cursor. ENET will disconnect when replay function is active
- **📈 Interactive Plotter** - Advanced time-series visualization with zoom/pan to help you see the relationship between sensors. Activate / deactivate plotting of sensor data by clicking on their coloured box in the legend.
- **🎯 Auto-Discovery** - Automatic detection of BMW ENET interface. Will scan the usual expected port range from 169.254.x.xxx. Generally all F chassis cars have a similar or same port 6801
- **⚡ High Performance** - Sub-90ms sensor polling intervals. Note that de-activating sensors will make polling faster for all remaining ones.
- **🎨 Dark Theme UI** - Professional "Precision Dark" instrument aesthetic. I love my dark themes.
- **🔧 Configurable Sensors** - Enable/disable individual sensors by clicking on them
- **⚠️ Warning Indicators** - Visual alerts for out-of-range values

---

## 🏗️ Technical Architecture

### Protocol Stack
┌─────────────────────────────────────────┐
│         Tkinter GUI (Dashboard)         │
├─────────────────────────────────────────┤
│      HSFZ Protocol Handler              │
│  (Header: 4-byte length + 2-byte type)  │
├─────────────────────────────────────────┤
│    UDS Diagnostic Protocol              │
│  - 0x2C DynamicDefineDataIdentifier     │
│  - 0x22 ReadDataByIdentifier            │
├─────────────────────────────────────────┤
│      TCP Socket (Port 6801)             │
├─────────────────────────────────────────┤
│        BMW ENET Interface               │
│     (169.254.9.103:6801)                │
└─────────────────────────────────────────┘

### Sensor Data Flow
ECU (DME 0x12) → HSFZ Frame → UDS Response → Scale Function → Gauge Display
     │              │              │              │              │
  Raw Value    0x0001 Type    0x62 Response   × 0.25 RPM     Circular
  DID 0x4807   Checksum       DID F300       × 0.1 V        Digital
               Validation     Payload        × 0.0145 PSI   Bar

            
## 🚀 Development Journey

### Iteration 1: Protocol Discovery